import asyncio
import logging
from typing import List, Optional

from gitchain.core.block import Block
from gitchain.core.blockchain import Blockchain
from gitchain.network.messages import MessageType, encode

log = logging.getLogger(__name__)


async def request_chain(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    #Send a GET_CHAIN request to an already-open peer connection.
    writer.write(encode(MessageType.GET_CHAIN))
    await writer.drain()


async def handle_chain_response(
    payload: dict,
    blockchain: Blockchain,
) -> bool:
    
    raw_chain = payload.get("chain", [])
    if not raw_chain:
        return False

    peer_chain = [Block.from_dict(b) for b in raw_chain]
    replaced, reason = blockchain.replace_chain(peer_chain)
    if replaced:
        log.info("sync: adopted peer chain (height=%d)", len(peer_chain))
    else:
        log.debug("sync: kept local chain — %s", reason)
    return replaced


async def handle_new_block(
    payload: dict,
    blockchain: Blockchain,
    broadcast_fn,          # async callable(msg_type, payload, exclude_writer)
    writer: asyncio.StreamWriter,
) -> bool:
    
    block = Block.from_dict(payload)
    ok, reason = blockchain.append_block(block)

    if ok:
        log.info("sync: appended block #%d (hash=%s…)", block.index, block.hash[:12])
        # Gossip the block onward to all other peers
        await broadcast_fn(
            MessageType.NEW_BLOCK,
            block.to_dict(),
            exclude_writer=writer,
        )
        return True
    else:
        log.warning("sync: block #%d rejected (%s) — requesting full chain", block.index, reason)
        writer.write(encode(MessageType.GET_CHAIN))
        await writer.drain()
        return False
