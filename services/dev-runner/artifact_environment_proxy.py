"""One bounded loopback TCP entrance to the fixed internal frontend endpoint."""

import ipaddress
import select
import socket
import socketserver
import threading
import time

from .toolchain import ProbeFailure


class LoopbackEntrance:
    def __init__(self, address: str):
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4 or not parsed.is_private or parsed.is_loopback:
            raise ProbeFailure("artifact_environment_frontend_address_invalid")
        self.address = address

        class Handler(socketserver.BaseRequestHandler):
            def handle(handler):
                try:
                    with socket.create_connection((address, 80), timeout=2) as upstream:
                        handler.request.settimeout(2)
                        peers = {handler.request: upstream, upstream: handler.request}
                        total, deadline = 0, time.monotonic() + 15
                        while peers and time.monotonic() < deadline:
                            readable, _, _ = select.select(list(peers), [], [], 0.5)
                            for source in readable:
                                data = source.recv(65536)
                                if not data:
                                    peers[source].shutdown(socket.SHUT_WR)
                                    del peers[source]
                                    continue
                                total += len(data)
                                if total > 8 * 1024**2:
                                    return
                                peers[source].sendall(data)
                except OSError:
                    return  # No request, response, credential, or connection error is logged.

        class Server(socketserver.TCPServer):
            request_queue_size = 8

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.thread.is_alive() or self.server.fileno() != -1:
            raise ProbeFailure("artifact_environment_loopback_entrance_stop_unconfirmed")
