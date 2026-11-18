"""Physical close observations for the Hub's controlled Uvicorn listener."""

import asyncio
from datetime import datetime, timezone
from functools import partial
import socket
import struct
import time

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

from modules.workspaces.preview_timing import PreviewClock


EXTENSION = "cloudhelm.preview.transport"


def clock_mark(clock: PreviewClock):
    ns, digest = clock.sample()
    if ns is not None and digest is not None:
        return {"epoch": clock.epoch, "evidence_digest": digest, "boottime_ns": ns}
    return None


def observed_at(clock: PreviewClock | None = None):
    # This listener-local ordering stamp does not assert that the clock has a proven rate.
    ns = (time.clock_gettime_ns(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME")
          else time.monotonic_ns())
    stamp = {"boottime": ns / 1_000_000_000, "boottime_ns": ns, "utc": datetime.now(timezone.utc).isoformat()}
    if clock is not None:
        stamp["clock"] = clock_mark(clock)
    return stamp


class PreviewTransport:
    def __init__(self, owner, transport, loop):
        self.owner = owner
        self.transport = transport
        self.opened = observed_at()
        self.external_tls = transport.get_extra_info("ssl_object") is not None
        self.clock = None
        self.abort_requested = None
        self.connection_lost = None
        self.closed = loop.create_future()

    def abort(self):
        if not self.closed.done():
            if self.abort_requested is None:
                self.abort_requested = observed_at()
            # close() can wait forever for a paused writer; abort discards its buffer.
            # Reset TCP as well: abort alone can leave kernel-queued bytes behind a zero window.
            raw_socket = self.transport.get_extra_info("socket")
            if raw_socket.family in {socket.AF_INET, socket.AF_INET6}:
                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.transport.abort()

    def lost(self):
        if not self.closed.done():
            self.connection_lost = observed_at(self.clock)
            self.closed.set_result(None)

    async def wait_closed(self):
        await asyncio.shield(self.closed)

    def receipt(self):
        return {"opened": self.opened, "abort_requested": self.abort_requested,
                "connection_lost": self.connection_lost, "external_tls": self.external_tls}


class PreviewConnection:
    def __init__(self, task, downstream, clock: PreviewClock):
        self.task, self.downstream = task, downstream
        self.downstream.clock = clock
        self.stream = self.socket = None
        self.connected = self.descriptor_closed = None
        self.finishing = False

    async def trace(self, name, info):
        if name in {"connection.connect_tcp.complete", "connection.start_tls.complete"}:
            self.stream = info["return_value"]
            if self.socket is None:
                self.socket = self.stream.get_extra_info("socket")
                self.connected = observed_at()

    def abort(self):
        self.downstream.abort()
        if not self.finishing and self.task is not asyncio.current_task():
            self.task.cancel()

    async def wait_closed(self):
        if self.stream is not None:
            await self.stream.aclose()
            # httpx/AnyIO aclose initiates transport close; fd release is the observation.
            while self.socket.fileno() != -1:
                await asyncio.sleep(0.01)
            self.descriptor_closed = observed_at(self.downstream.clock)
        await self.downstream.wait_closed()

    def receipt(self):
        upstream = None if self.socket is None else {
            "connected": self.connected, "descriptor_closed": self.descriptor_closed,
        }
        return {"downstream": self.downstream.receipt(), "upstream": upstream}


class PreviewTransportOwner:
    def __init__(self):
        self.started = None
        self.external_tls = False

    def receipt(self):
        return {"protocol": "uvicorn_h11", "started": self.started, "external_tls": self.external_tls}


class PreviewH11Protocol(H11Protocol):
    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.preview_owner = owner
        self.preview_transport = None
        app = self.app

        async def controlled(scope, receive, send):
            scope.setdefault("extensions", {})[EXTENSION] = self.preview_transport
            await app(scope, receive, send)

        self.app = controlled

    def connection_made(self, transport):
        super().connection_made(transport)
        self.preview_transport = PreviewTransport(self.preview_owner, transport, self.loop)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self.preview_transport.lost()


class PreviewServer(uvicorn.Server):
    """Install one listener owner for both normal Hub serving modes and TLS entrances."""

    def __init__(self, config):
        self.preview_owner = PreviewTransportOwner()
        config.app.state.preview_transport_owner = self.preview_owner
        config.http = partial(PreviewH11Protocol, owner=self.preview_owner)
        super().__init__(config)

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            self.preview_owner.external_tls = self.config.is_ssl
            self.preview_owner.started = observed_at()
