"""Fixed anonymous HTTPS transport and bounded input I/O; never runs npm."""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import ssl
import stat
import time
from pathlib import Path

from modules.artifacts.content_files import file_shape
from packages.contracts.p1.npm_cache import MAX_TARBALL_BYTES, REGISTRY, LockedNpmTarball


class NpmDownloadError(RuntimeError):
    """Only fixed codes cross the boundary; no network/configuration exception text."""


def source_inputs(frontend: Path) -> dict[str, bytes]:
    if not frontend.is_absolute() or any(part in {".", ".."} for part in frontend.parts):
        raise NpmDownloadError("npm_source_path_invalid")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in frontend.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        result = {}
        for name in ("package.json", "package-lock.json"):
            pinned = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            try:
                before = os.fstat(pinned)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 1024 * 1024:
                    raise NpmDownloadError("npm_source_file_unsupported")
                fd = os.open(f"/proc/self/fd/{pinned}", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                with os.fdopen(fd, "rb") as stream:
                    result[name] = stream.read(1024 * 1024 + 1)
                    after = os.fstat(stream.fileno())
                if file_shape(before) != file_shape(after) or len(result[name]) != before.st_size:
                    raise NpmDownloadError("npm_source_changed")
            finally:
                os.close(pinned)
        return result
    finally:
        os.close(directory)


class RegistryDownloads:
    def __init__(self):
        self.deadline = time.monotonic() + 600
        context = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
        self.connection = http.client.HTTPSConnection("registry.npmjs.org", timeout=15, context=context)

    def close(self) -> None:
        self.connection.close()

    def fetch(self, item: LockedNpmTarball, target, remaining: int) -> dict:
        # Revalidate before issuing a request, even for callers with model_copy() objects.
        item = LockedNpmTarball.model_validate(item.model_dump())
        if time.monotonic() >= self.deadline:
            raise NpmDownloadError("npm_download_deadline_exceeded")
        limit = min(remaining, MAX_TARBALL_BYTES)
        try:
            self.connection.request("GET", item.url.removeprefix(REGISTRY), headers={
                "Accept-Encoding": "identity", "Accept": "application/octet-stream",
                "User-Agent": "CloudHelm-fixed-npm-seed/1"})
            with self.connection.getresponse() as response:
                if response.status != 200:
                    raise NpmDownloadError("npm_https_status_or_redirect_rejected")
                advertised = response.headers.get_all("Content-Length", [])
                transfer = response.headers.get_all("Transfer-Encoding", [])
                encoding = response.headers.get_all("Content-Encoding", [])
                if (len(advertised) > 1 or (advertised and transfer)
                        or transfer not in ([], ["chunked"]) or encoding not in ([], ["identity"])):
                    raise NpmDownloadError("npm_https_framing_unsupported")
                length = None
                if advertised:
                    if not re.fullmatch(r"[0-9]{1,10}", advertised[0]):
                        raise NpmDownloadError("npm_https_length_unsupported")
                    length = int(advertised[0])
                    if not 0 < length <= limit:
                        raise NpmDownloadError("npm_download_bytes_exceeded")
                size, sha256, sha512 = 0, hashlib.sha256(), hashlib.sha512()
                while chunk := response.read(min(65536, limit - size + 1)):
                    size += len(chunk)
                    if size > limit or time.monotonic() >= self.deadline:
                        raise NpmDownloadError("npm_download_bytes_or_deadline_exceeded")
                    sha256.update(chunk)
                    sha512.update(chunk)
                    target.write(chunk)
                if not size or (length is not None and size != length):
                    raise NpmDownloadError("npm_https_actual_length_mismatch")
                if "sha512:" + sha512.hexdigest() != item.content_digest:
                    raise NpmDownloadError("npm_download_integrity_mismatch")
                return {**item.model_dump(), "filename": item.blob_name, "bytes": size,
                        "sha256": "sha256:" + sha256.hexdigest(), "sha512": item.content_digest}
        except NpmDownloadError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise NpmDownloadError("npm_anonymous_https_download_failed") from None
