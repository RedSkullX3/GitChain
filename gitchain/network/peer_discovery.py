
import asyncio
import logging
import socket
from typing import Callable, Optional

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

log = logging.getLogger(__name__)

SERVICE_TYPE = "_gitchain._tcp.local."


def _get_local_ip() -> str:
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class PeerDiscovery:
    #We were trying, but it does not seem to work.

    def __init__(
        self,
        node_id: str,
        port: int,
        on_peer_found: Callable[[str, int], None],
        on_peer_lost: Optional[Callable[[str, int], None]] = None,
    ):
        self.node_id = node_id
        self.port = port
        self.on_peer_found = on_peer_found
        self.on_peer_lost = on_peer_lost or (lambda h, p: None)

        self._zeroconf: Optional[AsyncZeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._browser: Optional[ServiceBrowser] = None
        self._local_ip = _get_local_ip()

    async def start(self) -> None:
        
        self._zeroconf = AsyncZeroconf()

        # Build the ServiceInfo for this node
        service_name = f"{self.node_id}.{SERVICE_TYPE}"
        self._service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(self._local_ip)],
            port=self.port,
            properties={"node_id": self.node_id},
        )

        await self._zeroconf.async_register_service(self._service_info)
        log.info("mDNS: registered %s at %s:%d", self.node_id, self._local_ip, self.port)

        # Start browsing — this calls our listener as peers come and go
        self._browser = ServiceBrowser(
            self._zeroconf.zeroconf,
            SERVICE_TYPE,
            listener=self._Listener(
                local_node_id=self.node_id,
                on_found=self.on_peer_found,
                on_lost=self.on_peer_lost,
                zeroconf=self._zeroconf.zeroconf,
            ),
        )

    async def stop(self) -> None:
        
        if self._zeroconf:
            if self._service_info:
                await self._zeroconf.async_unregister_service(self._service_info)
            await self._zeroconf.async_close()
            log.info("mDNS: unregistered %s", self.node_id)

    class _Listener:
        

        def __init__(self, local_node_id, on_found, on_lost, zeroconf):
            self.local_node_id = local_node_id
            self.on_found = on_found
            self.on_lost = on_lost
            self.zeroconf = zeroconf
            self._known: dict[str, tuple[str, int]] = {}

        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if not info:
                return
            peer_id = info.properties.get(b"node_id", b"").decode()
            if peer_id == self.local_node_id:
                return  # don't connect to ourselves
            host = socket.inet_ntoa(info.addresses[0])
            port = info.port
            self._known[name] = (host, port)
            log.info("mDNS: discovered peer %s at %s:%d", peer_id, host, port)
            self.on_found(host, port)

        def remove_service(self, zc, type_, name):
            entry = self._known.pop(name, None)
            if entry:
                host, port = entry
                log.info("mDNS: peer left %s:%d", host, port)
                self.on_lost(host, port)

        def update_service(self, zc, type_, name):
            pass  # re-announced — treat as add
