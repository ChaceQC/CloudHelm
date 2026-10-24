"""Export only the two compose-pinned public frontend bases to read-only OCI."""

from __future__ import annotations
from modules.execution.docker_endpoint import socket_path

import gzip
import hashlib
import json
import os
import resource
import subprocess
import tarfile
from pathlib import Path

from packages.contracts.p1.npm_cache import NODE_IMAGE

from .offline_images import (
    MAX_JSON_BYTES, OCI_CONFIG, OCI_INDEX, OCI_LAYERS, OCI_MANIFEST,
    _blob, _descriptor, _write_new,
)
from .toolchain import DOCKER, DockerClient, ProbeFailure, safe_diagnostic

NGINX_IMAGE = "nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de"
BASES = {"node": NODE_IMAGE, "nginx": NGINX_IMAGE}
MAX_EXPORT_BYTES = 384 * 1024**2
MAX_LAYER_BYTES = 256 * 1024**2
HTML_ROOT = "usr/share/nginx/html"
NGINX_CONFIG = "etc/nginx/conf.d/default.conf"
PROTECTED_DIRECTORIES = {"usr", "usr/share", "usr/share/nginx", HTML_ROOT,
                         "etc", "etc/nginx", "etc/nginx/conf.d"}


def _export(client: DockerClient, reference: str, target: Path) -> None:
    digest = reference.rsplit("@", 1)[1]
    present = client.run("image", "inspect", reference, "--format", "{{.Id}}", required=False)
    if present.returncode:
        client.run("pull", "--platform=linux/amd64", reference, timeout=240)
    metadata = json.loads(client.run("image", "inspect", reference, "--format",
                                     "{{json .Descriptor}}").stdout)
    if metadata.get("digest") != digest:
        raise ProbeFailure("frontend_base_local_reference_mismatch")
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "DOCKER_CONFIG": str(client.config_directory)}

    def limit_file():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_EXPORT_BYTES, MAX_EXPORT_BYTES))

    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            result = subprocess.run([DOCKER, "--host", "unix://" + socket_path(),
                "image", "save", "--platform=linux/amd64", reference], env=environment,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE,
                preexec_fn=limit_file, timeout=90, check=False)
            stream.flush()
            os.fsync(stream.fileno())
    except subprocess.TimeoutExpired:
        raise ProbeFailure("frontend_base_export_timeout") from None
    if result.returncode or not 0 < target.stat().st_size <= MAX_EXPORT_BYTES:
        raise ProbeFailure("frontend_base_export_failed", detail=safe_diagnostic(
            result.stderr.decode("utf-8", errors="replace")))


def _layout(client: DockerClient, directory: Path, name: str) -> dict:
    reference = BASES[name]
    root = json.loads(client.run("manifest", "inspect", reference, timeout=90).stdout)
    if root.get("mediaType") != OCI_INDEX:
        raise ProbeFailure("frontend_base_index_unsupported")
    matches = [item for item in root.get("manifests", []) if item.get("platform") == {
        "architecture": "amd64", "os": "linux"}]
    if len(matches) != 1:
        raise ProbeFailure("frontend_base_amd64_manifest_not_unique")
    manifest = _descriptor(matches[0], {OCI_MANIFEST})
    if manifest["size"] > MAX_JSON_BYTES:
        raise ProbeFailure("frontend_base_manifest_too_large")
    source, layout = directory / (name + "-export.tar"), directory / (name + "-layout")
    (layout / "blobs/sha256").mkdir(mode=0o700, parents=True)
    try:
        _export(client, reference, source)
        with tarfile.open(source, "r:") as archive:
            members = archive.getmembers()
            if len(members) > 1024 or len({item.name for item in members}) != len(members):
                raise ProbeFailure("frontend_base_export_members_invalid")
            entries = {item.name: item for item in members}
            value = json.loads(_blob(archive, entries, manifest, layout))
            if value.get("mediaType") != OCI_MANIFEST or value.get("schemaVersion") != 2:
                raise ProbeFailure("frontend_base_manifest_unsupported")
            config = _descriptor(value.get("config"), {OCI_CONFIG})
            if config["size"] > MAX_JSON_BYTES:
                raise ProbeFailure("frontend_base_config_too_large")
            configuration = json.loads(_blob(archive, entries, config, layout))
            if configuration.get("os") != "linux" or configuration.get("architecture") != "amd64":
                raise ProbeFailure("frontend_base_config_platform_mismatch")
            layers = tuple(_descriptor(item, OCI_LAYERS) for item in value.get("layers", []))
            if not layers or len(layers) > 32 or sum(item["size"] for item in layers) > MAX_EXPORT_BYTES:
                raise ProbeFailure("frontend_base_layer_bounds_exceeded")
            for layer in layers:
                _blob(archive, entries, layer, layout)
        _write_new(layout / "oci-layout", b'{"imageLayoutVersion":"1.0.0"}\n')
        index = {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
            manifest | {"platform": {"os": "linux", "architecture": "amd64"}}]}
        _write_new(layout / "index.json", json.dumps(index, separators=(",", ":")).encode("utf-8"))
        for path in sorted(layout.rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o500)
        layout.chmod(0o500)
        return {"reference": reference, "manifest": manifest, "config": config, "layers": layers,
            "layout_bytes": sum(item.stat().st_size for item in layout.rglob("*") if item.is_file()),
            "source_export_bytes": source.stat().st_size, "platform": "linux/amd64"}
    finally:
        source.unlink(missing_ok=True)


def prepare_frontend_layouts(client: DockerClient, directory: Path) -> dict:
    return {name: _layout(client, directory, name) for name in BASES}


class _LayerReader:
    """Hash all uncompressed bytes, including padding beyond the tar end marker."""

    def __init__(self, source):
        self.source = gzip.GzipFile(fileobj=source)
        self.digest, self.size = hashlib.sha256(), 0

    def read(self, size: int = -1) -> bytes:
        size = MAX_LAYER_BYTES + 1 if size < 0 else size
        raw = self.source.read(min(size, MAX_LAYER_BYTES - self.size + 1))
        self.size += len(raw)
        if self.size > MAX_LAYER_BYTES:
            raise ProbeFailure("frontend_uncompressed_layer_too_large")
        self.digest.update(raw)
        return raw


def _runtime_member(files: dict, whiteouts: list[str], member, archive) -> None:
    name = member.name.removeprefix("./").removesuffix("/")
    if member.isdir() and name in {"", "."}:
        return
    if (name.startswith("/") or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ProbeFailure("frontend_layer_member_path_invalid")
    parent, _, leaf = name.rpartition("/")
    if leaf.startswith(".wh."):
        target = parent if leaf == ".wh..wh..opq" else (
            parent + "/" + leaf[4:] if parent else leaf[4:])
        whiteouts.append(target)
        return
    if name in PROTECTED_DIRECTORIES and not member.isdir():
        raise ProbeFailure("frontend_runtime_directory_replaced")
    if name != NGINX_CONFIG and not name.startswith(HTML_ROOT + "/"):
        return
    if member.isdir():
        if name == NGINX_CONFIG:
            raise ProbeFailure("frontend_nginx_configuration_not_file")
        return
    if not member.isfile() or not 0 < member.size <= 2 * 1024**2:
        raise ProbeFailure("frontend_runtime_file_unsupported")
    with archive.extractfile(member) as source:
        raw = source.read(2 * 1024**2 + 1)
    if len(raw) != member.size:
        raise ProbeFailure("frontend_runtime_file_truncated")
    files[name] = {"sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verify_frontend_image(store, receipt, dist: list[dict], nginx_input: bytes) -> dict:
    """Check layer identities and the effective final HTML tree, including whiteouts."""
    expected = {HTML_ROOT + "/" + item["path"]: {key: item[key] for key in ("sha256", "bytes")}
                for item in dist}
    expected[NGINX_CONFIG] = {"sha256": "sha256:" + hashlib.sha256(nginx_input).hexdigest(),
                              "bytes": len(nginx_input)}
    actual, uncompressed_bytes = {}, 0
    try:
        with store.open_archive(receipt.storage_id) as stream, tarfile.open(fileobj=stream, mode="r:") as archive:
            config = json.load(archive.extractfile("blobs/sha256/" + receipt.config.digest[7:]))
            settings = config["config"]
            if (settings.get("Entrypoint") != ["/docker-entrypoint.sh"]
                    or settings.get("Cmd") != ["nginx", "-g", "daemon off;"]):
                raise ProbeFailure("frontend_nginx_runtime_configuration_mismatch")
            for layer, diff_id in zip(receipt.layers, config["rootfs"]["diff_ids"], strict=True):
                if layer.media_type != "application/vnd.oci.image.layer.v1.tar+gzip":
                    raise ProbeFailure("frontend_output_layer_not_gzip")
                with archive.extractfile("blobs/sha256/" + layer.digest[7:]) as blob:
                    reader = _LayerReader(blob)
                    additions, whiteouts = {}, []
                    try:
                        with tarfile.open(fileobj=reader, mode="r|") as members:
                            for count, member in enumerate(members, start=1):
                                if count > 50000:
                                    raise ProbeFailure("frontend_layer_member_limit_exceeded")
                                _runtime_member(additions, whiteouts, member, members)
                        while reader.read(65536):
                            pass
                    finally:
                        reader.source.close()
                    if "sha256:" + reader.digest.hexdigest() != diff_id:
                        raise ProbeFailure("frontend_uncompressed_layer_digest_mismatch")
                    for target in whiteouts:
                        for path in list(actual):
                            if not target or path == target or path.startswith(target + "/"):
                                del actual[path]
                    actual.update(additions)
                    uncompressed_bytes += reader.size
                    if uncompressed_bytes > 512 * 1024**2:
                        raise ProbeFailure("frontend_uncompressed_image_too_large")
    except ProbeFailure:
        raise
    except (OSError, EOFError, ValueError, KeyError, tarfile.TarError):
        raise ProbeFailure("frontend_runtime_archive_decode_rejected") from None
    if actual != expected:
        raise ProbeFailure("frontend_dist_archive_content_mismatch")
    return {"nginx_entrypoint_verified": True, "gzip_layers": len(receipt.layers),
            "uncompressed_layers_verified": True, "uncompressed_image_bytes": uncompressed_bytes,
            "final_dist_exactly_matches": True, "verified_runtime_files": actual,
            "attestations": False}
