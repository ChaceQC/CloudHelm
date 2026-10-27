"""Fixed Docker operations; daemon replies and injected secret values stay private."""

import http.client
import json
import os
import socket
import subprocess
from functools import partial

from .deadline import parent_death_signal
from .ledger import RemoteError, private_directory


class _Connection(http.client.HTTPConnection):
    def __init__(self, endpoint):
        super().__init__("localhost", timeout=30)
        self.endpoint = str(endpoint)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.endpoint)


class Docker:
    def __init__(self, directory, endpoint="/var/run/docker.sock"):
        self.directory = private_directory(directory)
        self.endpoint = str(endpoint)
        if (self.directory / "config.json").exists():
            raise RemoteError("remote_public_docker_config_required")

    def api(self, method, path, payload=None, *, expected=(200, 201, 204)):
        connection = _Connection(self.endpoint)
        try:
            raw = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
            connection.request(method, path, body=raw, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read(2_000_001)
            if response.status not in expected or len(data) > 2_000_000:
                raise RemoteError("remote_docker_request_unresolved")
            return json.loads(data) if data else None
        except (OSError, ValueError, http.client.HTTPException):
            raise RemoteError("remote_docker_connection_unresolved") from None
        finally:
            connection.close()

    def command(self, *arguments, input_bytes=None, stdin=None, timeout=30, supervised=False):
        try:
            result = subprocess.run(["/usr/bin/docker", "--config", str(self.directory),
                "--host", "unix://" + self.endpoint, *arguments], input=input_bytes, stdin=stdin,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                preexec_fn=partial(parent_death_signal, os.getpid()) if supervised else None,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
            if result.returncode or len(result.stdout) + len(result.stderr) > 2_000_000:
                raise RemoteError("remote_docker_command_unresolved")
            return result.stdout
        except (OSError, subprocess.TimeoutExpired):
            raise RemoteError("remote_docker_command_unresolved") from None

    def inspect(self, name):
        return self.api("GET", "/containers/" + name + "/json")
