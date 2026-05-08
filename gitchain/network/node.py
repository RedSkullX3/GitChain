import asyncio
import json
import logging
import uuid
from typing import Dict, Optional, Set

from gitchain.core.blockchain import Blockchain
from gitchain.core.mempool import Mempool
from gitchain.core.miner import mine_block
from gitchain.core.transaction import Transaction
from gitchain.network.messages import MessageType, encode, decode
from gitchain.network.sync import handle_chain_response, handle_new_block, request_chain

log = logging.getLogger(__name__)

PING_INTERVAL = 30        # seconds between heartbeats
MINE_POLL_INTERVAL = 0.1  # seconds between mempool checks


class PeerConnection:
    #Represents one live TCP connection to a peer node.

    def __init__(self, host: str, port: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.host = host
        self.port = port
        self.reader = reader
        self.writer = writer
        self.addr = f"{host}:{port}"

    async def send(self, msg_type: MessageType, payload=None) -> None:
        try:
            self.writer.write(encode(msg_type, payload))
            await self.writer.drain()
        except Exception as e:
            log.warning("send to %s failed: %s", self.addr, e)

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass


class GitChainNode:
    
    #The full GitChain node daemon.

    def __init__(
        self,
        port: int = 6331,
        difficulty: int = 3,
        data_path: str = "chain.json",
        node_id: Optional[str] = None,
        enable_mdns: bool = True,
    ):
        self.port = port
        self.difficulty = difficulty
        self.node_id = node_id or str(uuid.uuid4())[:8]
        self.enable_mdns = enable_mdns

        self.blockchain = Blockchain(difficulty=difficulty, data_path=data_path)
        self.mempool = Mempool()

        # host:port → PeerConnection
        self._peers: Dict[str, PeerConnection] = {}
        self._peers_lock = asyncio.Lock()

        # Tracks addresses we are currently connecting to (avoid duplicates)
        self._connecting: Set[str] = set()

        # Tracks per-peer read loop tasks so we can cancel them on shutdown
        self._peer_tasks: Dict[str, asyncio.Task] = {}

        self._server: Optional[asyncio.Server] = None
        self._discovery = None
        self._stop_mining = False
        self._tasks: list[asyncio.Task] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

   
    async def start(self) -> None:
        #Start TCP server/ mining loop.
        
        self._loop = asyncio.get_running_loop()

        self._server = await asyncio.start_server(
            self._handle_incoming_connection, "0.0.0.0", self.port
        )
        log.info("node %s listening on port %d", self.node_id, self.port)

        if self.enable_mdns:
            from gitchain.network.peer_discovery import PeerDiscovery
            self._discovery = PeerDiscovery(
                node_id=self.node_id,
                port=self.port,
                on_peer_found=self._on_peer_found,
                on_peer_lost=self._on_peer_lost,
            )
            await self._discovery.start()

        self._tasks.append(asyncio.create_task(self._mining_loop(), name="miner"))
        self._tasks.append(asyncio.create_task(self._ping_loop(), name="pinger"))
        self._tasks.append(asyncio.create_task(self._server.serve_forever(), name="server"))

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._stop_mining = True

        # 1. Close all peer writers first so wait_closed doesn't block
        async with self._peers_lock:
            for peer in self._peers.values():
                peer.close()
            self._peers.clear()

        # 2. Cancel all per-peer read loop tasks
        for task in list(self._peer_tasks.values()):
            task.cancel()
        self._peer_tasks.clear()

        # 3. Stop mDNS
        if self._discovery:
            await self._discovery.stop()

        # 4. Cancel background tasks (miner, pinger, server)
        for t in self._tasks:
            t.cancel()

        # 5. Close TCP server with a timeout so we don't block forever
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

        log.info("node %s stopped", self.node_id)

 
    def _on_peer_found(self, host: str, port: int) -> None:
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._connect_to_peer(host, port))
        )

    def _on_peer_lost(self, host: str, port: int) -> None:
        addr = f"{host}:{port}"
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._drop_peer(addr))
        )

    async def connect_to_peer(self, host: str, port: int) -> bool:
        """Public API: manually connect to a known peer by address."""
        return await self._connect_to_peer(host, port)

    async def _connect_to_peer(self, host: str, port: int) -> bool:
        addr = f"{host}:{port}"
        async with self._peers_lock:
            if addr in self._peers or addr in self._connecting:
                return False
            self._connecting.add(addr)

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
        except Exception as e:
            log.warning("connect to %s failed: %s", addr, e)
            self._connecting.discard(addr)
            return False

        peer = PeerConnection(host, port, reader, writer)
        async with self._peers_lock:
            self._peers[addr] = peer
            self._connecting.discard(addr)

        log.info("connected to peer %s", addr)

        # Immediately request their chain so we can sync
        await request_chain(reader, writer)

        # Start reading loop for this peer (tracked so stop() can cancel it)
        task = asyncio.create_task(self._peer_read_loop(peer), name=f"peer-{addr}")
        self._peer_tasks[addr] = task
        return True

    async def _handle_incoming_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        
        host, port = writer.get_extra_info("peername")
        addr = f"{host}:{port}"
        peer = PeerConnection(host, port, reader, writer)

        async with self._peers_lock:
            self._peers[addr] = peer

        log.info("inbound peer connected: %s", addr)

        # Send our chain immediately so they can sync
        await peer.send(MessageType.CHAIN_RESPONSE, {"chain": self.blockchain.to_dict_list()})

        task = asyncio.create_task(self._peer_read_loop(peer), name=f"peer-{addr}")
        self._peer_tasks[addr] = task

    async def _drop_peer(self, addr: str) -> None:
        async with self._peers_lock:
            peer = self._peers.pop(addr, None)
        self._peer_tasks.pop(addr, None)
        if peer:
            peer.close()
            log.info("dropped peer %s", addr)



    async def _peer_read_loop(self, peer: PeerConnection) -> None:
        
        try:
            while True:
                raw = await peer.reader.readline()
                if not raw:
                    break   # peer closed connection

                try:
                    msg_type, payload = decode(raw.decode())
                except ValueError as e:
                    log.warning("bad message from %s: %s", peer.addr, e)
                    continue

                await self._dispatch(msg_type, payload, peer)

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            log.error("peer %s read error: %s", peer.addr, e)
        finally:
            await self._drop_peer(peer.addr)
            log.info("peer %s disconnected", peer.addr)

    async def _dispatch(self, msg_type: MessageType, payload: dict, peer: PeerConnection) -> None:
        #Route an incoming message to the correct handler.

        if msg_type == MessageType.PING:
            await peer.send(MessageType.PONG)

        elif msg_type == MessageType.PONG:
            pass  # heartbeat acknowledged

        elif msg_type == MessageType.GET_CHAIN:
            await peer.send(
                MessageType.CHAIN_RESPONSE,
                {"chain": self.blockchain.to_dict_list()},
            )

        elif msg_type == MessageType.CHAIN_RESPONSE:
            await handle_chain_response(payload, self.blockchain)

        elif msg_type == MessageType.NEW_TRANSACTION:
            await self._handle_new_transaction(payload, peer)

        elif msg_type == MessageType.NEW_BLOCK:
            accepted = await handle_new_block(
                payload,
                self.blockchain,
                broadcast_fn=self._broadcast,
                writer=peer.writer,
            )
            if accepted:
                # Remove the block's transactions from our mempool so we don't re-mine them. Without this, every node would mine a competing block containing the same transactions as the received block.
                
                commit_hashes = [
                    tx.get("commit_hash")
                    for tx in payload.get("transactions", [])
                    if tx.get("commit_hash")
                ]
                if commit_hashes:
                    self.mempool.remove(commit_hashes)


    async def submit_transaction(self, tx: Transaction) -> bool:
        """
        Accept a transaction (from the API or a peer).
        Validate signature, add to mempool, broadcast to peers.
        Returns True if accepted.
        """
        added = self.mempool.add(tx, verify=True)
        if added:
            log.info("mempool: accepted tx %s…", tx.commit_hash[:12])
            await self._broadcast(MessageType.NEW_TRANSACTION, tx.to_dict())
        return added

    async def _handle_new_transaction(self, payload: dict, sender: PeerConnection) -> None:
        """Process a NEW_TRANSACTION received from a peer."""
        try:
            tx = Transaction.from_dict(payload)
        except Exception as e:
            log.warning("invalid transaction from %s: %s", sender.addr, e)
            return

        added = self.mempool.add(tx, verify=True)
        if added:
            log.info("mempool: relayed tx %s… from %s", tx.commit_hash[:12], sender.addr)
            # Gossip forward to all peers except the sender
            await self._broadcast(MessageType.NEW_TRANSACTION, payload, exclude_writer=sender.writer)


    async def _mining_loop(self) -> None:
        
        loop = asyncio.get_running_loop()

        while not self._stop_mining:
            pending = self.mempool.get_pending(limit=10)

            if not pending:
                await asyncio.sleep(MINE_POLL_INTERVAL)
                continue

            tip = self.blockchain.tip
            index = self.blockchain.height()

            log.info("mining: starting block #%d with %d tx(s)…", index, len(pending))

            # mine_block is CPU-bound — run in thread pool so we don't block I/O
            block = await loop.run_in_executor(
                None,
                mine_block,
                pending,
                tip.hash,
                index,
                self.difficulty,
                lambda: self._stop_mining,
            )

            if block is None:
                # stop_flag triggered (node shutting down)
                break

            # Double-check we're still at the same tip (a peer may have mined first)
            if self.blockchain.tip.hash != tip.hash:
                log.info("mining: tip changed while mining — discarding block, retrying")
                continue

            ok, reason = self.blockchain.append_block(block)
            if ok:
                mined_commit_hashes = [tx.get("commit_hash") for tx in pending]
                self.mempool.remove(mined_commit_hashes)

                log.info(
                    "mining: mined block #%d hash=%s… nonce=%d",
                    block.index, block.hash[:12], block.nonce,
                )
                await self._broadcast(MessageType.NEW_BLOCK, block.to_dict())
            else:
                log.warning("mining: freshly mined block rejected: %s", reason)


    async def _ping_loop(self) -> None:
        """Send PING to all peers every PING_INTERVAL seconds."""
        while not self._stop_mining:
            await asyncio.sleep(PING_INTERVAL)
            async with self._peers_lock:
                peers = list(self._peers.values())
            for peer in peers:
                await peer.send(MessageType.PING)


    async def _broadcast(
        self,
        msg_type: MessageType,
        payload=None,
        exclude_writer: Optional[asyncio.StreamWriter] = None,
    ) -> None:
        """Send a message to all connected peers, optionally skipping one."""
        async with self._peers_lock:
            peers = list(self._peers.values())

        for peer in peers:
            if exclude_writer and peer.writer is exclude_writer:
                continue
            await peer.send(msg_type, payload)


    def status(self) -> dict:
        return {
            "node_id": self.node_id,
            "chain_height": self.blockchain.height(),
            "mempool_size": self.mempool.size(),
            "peer_count": len(self._peers),
            "peers": list(self._peers.keys()),
        }
