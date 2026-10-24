"""Bounded local Runner transport; requests contain identities only, never paths or commands."""

import json
import socket

from packages.contracts.p1.resource_protocol import ExecutorReceipt

SOCKET = "/run/cloudhelm-resource-control.sock"
MAX_MESSAGE = 65536


class ResourceChannel:
    def __init__(self, registration):
        self.registration = registration

    def _call(self, action, reservation_id, network_id=None):
        request = {"action": action, "executor_id": self.registration.executor_instance_id,
                   "reservation_id": reservation_id}
        if network_id is not None:
            request["network_id"] = network_id
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(45)
            connection.connect(SOCKET)
            connection.sendall(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
            data = bytearray()
            while not data.endswith(b"\n"):
                block = connection.recv(min(4096, MAX_MESSAGE + 1 - len(data)))
                if not block or len(data) + len(block) > MAX_MESSAGE:
                    raise OSError("resource_channel_response_unavailable")
                data.extend(block)
            response = json.loads(data)
        if response.get("status") != "ok":
            raise OSError("resource_channel_request_rejected")
        return None if response["receipt"] is None else ExecutorReceipt.model_validate(response["receipt"])

    def accept(self, request, *, backend):
        if backend != self.registration.backend:
            raise ValueError("resource_channel_backend_mismatch")
        return self._call("accept", request.identity.reservation_id)

    def start(self, reservation_id, check_current_start):
        # The root controller rechecks the Hub gate under its own durable host lock.
        return self._call("start", reservation_id)

    def query(self, reservation_id):
        return self._call("query", reservation_id)

    def stop(self, reservation_id):
        return self._call("stop", reservation_id)

    def authorize_network(self, reservation_id, network_id):
        return self._call("network", reservation_id, network_id)
