"""Outbound authenticated HTTPS, bounded JSON and content-addressed archive transfer."""

import os
import stat
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from packages.contracts.p1.remote_delivery import RemoteBindings, RemotePermit, RemotePoll, RemotePollResult, RemoteTimeSample
from .ledger import RemoteError


def read_private(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        value = os.fstat(descriptor)
        if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                or value.st_mode & 0o077 or value.st_size > 16384):
            raise RemoteError("remote_secret_file_permissions_invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(16385)
    finally:
        os.close(descriptor)


class Channel:
    def __init__(self, url, token_file, *, verify=True):
        parts = urlsplit(url)
        if (parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}
                or parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "::1"})
                or verify is False):
            raise RemoteError("remote_authenticated_tls_required")
        self._token = SecretStr(read_private(token_file).decode("ascii").strip())
        self.client = httpx.Client(base_url=url.rstrip("/"), verify=verify, follow_redirects=False,
            trust_env=False, timeout=httpx.Timeout(30, read=60))

    def _headers(self):
        return {"Authorization": "Bearer " + self._token.get_secret_value()}

    def post(self, action, body, schema=None):
        try:
            with self.client.stream("POST", "/remote/v1/" + action, headers=self._headers(),
                    json=body.model_dump(mode="json")) as response:
                if response.status_code != 200:
                    raise RemoteError("remote_waiting_authorization")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 131072:
                        raise RemoteError("remote_response_too_large")
            return schema.model_validate_json(data) if schema else None
        except httpx.HTTPError:
            raise RemoteError("remote_connection_unavailable") from None

    def sample(self, hello):
        return self.post("sample", hello, RemoteTimeSample)

    def poll(self, executor, generation):
        return self.post("poll", RemotePoll(executor_instance=executor, generation=generation), RemotePollResult)

    def bindings(self, executor, generation):
        return self.post("bindings", RemotePoll(executor_instance=executor, generation=generation), RemoteBindings)

    def permit(self, request):
        return self.post("permits", request, RemotePermit)

    def report(self, result):
        return self.post("results", result)

    def observe(self, observation):
        from packages.contracts.p1.remote_delivery import RemoteObservationRequest

        return self.post("observations", RemoteObservationRequest(observation=observation))

    def download(self, operation, artifact, output):
        count = 0
        try:
            with self.client.stream("GET", f"/remote/v1/artifacts/{operation}/{artifact.storage_id}",
                    headers=self._headers()) as response:
                if response.status_code != 200:
                    raise RemoteError("remote_archive_unavailable")
                for block in response.iter_bytes(65536):
                    count += len(block)
                    if count > artifact.archive_bytes:
                        raise RemoteError("remote_archive_bound_exceeded")
                    output.write(block)
            if count != artifact.archive_bytes:
                raise RemoteError("remote_archive_incomplete")
        except httpx.HTTPError:
            raise RemoteError("remote_archive_transfer_unknown") from None

    def close(self):
        self.client.close()
