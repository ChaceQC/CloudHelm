"""Read one bounded live Docker output window without retaining raw logs."""

from __future__ import annotations

import socket
import time
from datetime import UTC, datetime

from modules.agent_runtime.source_context import safe_context_text
from modules.execution.docker_endpoint import socket_path

from .toolchain import ProbeFailure

_WINDOW_SECONDS = 1.0
_MAX_HEADER_BYTES = 8192
_MAX_CAPTURE_BYTES = 65536
_MAX_WIRE_BYTES = 131072
_MAX_CAPTURE_LINES = 160


def read_live_logs(container_id: str, *, max_lines: int, max_bytes: int) -> dict:
    """Observe stdout/stderr only; closing this socket does not signal the container."""
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(_WINDOW_SECONDS)
        connection.connect(socket_path())
        started_at = datetime.now(UTC).isoformat()
        deadline = time.monotonic() + _WINDOW_SECONDS
        request = (
            f"POST /containers/{container_id}/attach?stream=1&stdout=1&stderr=1&stdin=0&logs=0 HTTP/1.1\r\n"
            "Host: localhost\r\nConnection: Upgrade\r\nUpgrade: tcp\r\nContent-Length: 0\r\n\r\n"
        ).encode("ascii")
        connection.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or len(response) >= _MAX_HEADER_BYTES:
                raise ProbeFailure("workspace_development_log_attach_unavailable")
            connection.settimeout(remaining)
            chunk = connection.recv(_MAX_HEADER_BYTES - len(response))
            if not chunk:
                raise ProbeFailure("workspace_development_log_attach_unavailable")
            response.extend(chunk)
        header, _, pending = response.partition(b"\r\n\r\n")
        status = header.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"101":
            raise ProbeFailure("workspace_development_log_attach_unavailable")

        data = bytearray()
        wire_bytes = len(pending)
        frame_remaining = 0
        captured_lines = 0
        truncated = False
        while True:
            while pending:
                if frame_remaining == 0:
                    if len(pending) < 8:
                        break
                    if pending[0] not in (1, 2) or pending[1:4] != b"\x00\x00\x00":
                        raise ProbeFailure("workspace_development_log_stream_invalid")
                    frame_remaining = int.from_bytes(pending[4:8], "big")
                    del pending[:8]
                    if frame_remaining == 0:
                        continue
                count = min(frame_remaining, len(pending), _MAX_CAPTURE_BYTES - len(data))
                part = pending[:count]
                new_lines = part.count(b"\n")
                allowed_lines = _MAX_CAPTURE_LINES - captured_lines
                if allowed_lines == 0 and part:
                    part = b""
                    truncated = True
                elif new_lines > allowed_lines:
                    end = 0
                    for _ in range(allowed_lines):
                        end = part.find(b"\n", end) + 1
                    part = part[:end]
                    truncated = True
                data.extend(part)
                captured_lines += min(new_lines, allowed_lines)
                del pending[:count]
                frame_remaining -= count
                if len(data) >= _MAX_CAPTURE_BYTES:
                    truncated = True
                if truncated:
                    break
            if truncated:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if wire_bytes >= _MAX_WIRE_BYTES:
                truncated = True
                break
            connection.settimeout(remaining)
            try:
                chunk = connection.recv(min(8192, _MAX_WIRE_BYTES - wire_bytes))
            except socket.timeout:
                break
            if not chunk:
                raise ProbeFailure("workspace_development_log_stream_unavailable")
            wire_bytes += len(chunk)
            pending.extend(chunk)
        if frame_remaining or pending:
            truncated = True
        observed_at = datetime.now(UTC).isoformat()
    except (OSError, UnicodeError):
        raise ProbeFailure("workspace_development_log_attach_unavailable") from None
    finally:
        connection.close()

    lines = safe_context_text(data.decode("utf-8", errors="replace")).splitlines(keepends=True)
    if len(lines) > max_lines:
        truncated = True
        lines = lines[-max_lines:]
    encoded = "".join(lines).encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = True
        encoded = encoded[-max_bytes:]
    return {"source": "live", "history_available": False, "window_started_at": started_at,
            "observed_at": observed_at, "text": encoded.decode("utf-8", errors="ignore"),
            "truncated": truncated}
