"""Acquire only the fixed public Python base; no arbitrary registry or URL inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import subprocess
import tarfile
from pathlib import Path

from .toolchain import DockerClient, DOCKER, ProbeFailure, safe_diagnostic

SOURCE_TAG = "python:3.12.13-slim-bookworm"
SOURCE_DIGEST = "sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"
SOURCE_REFERENCE = SOURCE_TAG + "@" + SOURCE_DIGEST
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYERS = {"application/vnd.oci.image.layer.v1.tar", "application/vnd.oci.image.layer.v1.tar+gzip"}


def _descriptor(value: dict, media_types: set[str]) -> dict:
    if (not isinstance(value, dict) or value.get("mediaType") not in media_types
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("digest", ""))
            or type(value.get("size")) is not int or not 0 < value["size"] <= MAX_SOURCE_BYTES
            or value.get("urls") or value.get("data")):
        raise ProbeFailure("offline_source_descriptor_unsupported")
    return {key: value[key] for key in ("mediaType", "digest", "size")}


def _write_new(path: Path, data: bytes, mode: int = 0o400) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _limit_export_file() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SOURCE_BYTES, MAX_SOURCE_BYTES))


def _export_fixed_source(client: DockerClient, archive: Path) -> None:
    present = client.run("image", "inspect", SOURCE_REFERENCE, "--format", "{{.Id}}", required=False)
    if present.returncode:
        client.run("pull", "--platform=linux/amd64", SOURCE_REFERENCE, timeout=240)
    result = client.run("image", "inspect", SOURCE_REFERENCE, "--format",
                        "{{json .Descriptor}}")
    if json.loads(result.stdout).get("digest") != SOURCE_DIGEST:
        raise ProbeFailure("offline_source_local_reference_mismatch")
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "DOCKER_CONFIG": str(client.config_directory)}
    descriptor = os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            result = subprocess.run([DOCKER, "--host", "unix:///var/run/docker.sock",
                "image", "save", "--platform=linux/amd64", SOURCE_REFERENCE],
                env=environment, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE,
                preexec_fn=_limit_export_file, timeout=90, check=False)
            stream.flush()
            os.fsync(stream.fileno())
    except subprocess.TimeoutExpired:
        raise ProbeFailure("offline_source_export_timeout") from None
    if result.returncode or archive.stat().st_size > MAX_SOURCE_BYTES:
        raise ProbeFailure("offline_source_export_failed", detail=safe_diagnostic(
            result.stderr.decode("utf-8", errors="replace")))


def _blob(archive: tarfile.TarFile, entries: dict, descriptor: dict, destination: Path) -> bytes | None:
    name = "blobs/sha256/" + descriptor["digest"].removeprefix("sha256:")
    entry = entries.get(name)
    if entry is None or not entry.isfile() or entry.size != descriptor["size"]:
        raise ProbeFailure("offline_source_blob_missing_or_size_mismatch")
    source = archive.extractfile(entry)
    digest, collected = hashlib.sha256(), bytearray()
    descriptor_fd = os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
    with source, os.fdopen(descriptor_fd, "wb") as target:
        while chunk := source.read(65536):
            digest.update(chunk)
            target.write(chunk)
            if entry.size <= MAX_JSON_BYTES:
                collected.extend(chunk)
        target.flush()
        os.fsync(target.fileno())
    if "sha256:" + digest.hexdigest() != descriptor["digest"]:
        raise ProbeFailure("offline_source_blob_digest_mismatch")
    return bytes(collected) if entry.size <= MAX_JSON_BYTES else None


def prepare_python_layout(client: DockerClient, directory: Path) -> dict:
    """Export trusted Docker content, then retain only the pinned amd64 image graph."""
    root = json.loads(client.run("manifest", "inspect", SOURCE_REFERENCE, timeout=90).stdout)
    if root.get("mediaType") != OCI_INDEX:
        raise ProbeFailure("offline_source_index_unsupported")
    matches = [item for item in root.get("manifests", []) if item.get("platform") == {
        "architecture": "amd64", "os": "linux"}]
    if len(matches) != 1:
        raise ProbeFailure("offline_source_amd64_manifest_not_unique")
    manifest = _descriptor(matches[0], {OCI_MANIFEST})
    if manifest["size"] > MAX_JSON_BYTES:
        raise ProbeFailure("offline_source_manifest_too_large")
    source = directory / "source-export.tar"
    _export_fixed_source(client, source)
    layout = directory / "base-layout"
    (layout / "blobs" / "sha256").mkdir(mode=0o700, parents=True)
    try:
        with tarfile.open(source, "r:") as archive:
            members = archive.getmembers()
            if len(members) > 1024 or len({item.name for item in members}) != len(members):
                raise ProbeFailure("offline_source_export_members_invalid")
            entries = {item.name: item for item in members}
            raw_manifest = _blob(archive, entries, manifest, layout)
            value = json.loads(raw_manifest)
            if value.get("mediaType") != OCI_MANIFEST or value.get("schemaVersion") != 2:
                raise ProbeFailure("offline_source_manifest_unsupported")
            config = _descriptor(value.get("config"), {OCI_CONFIG})
            if config["size"] > MAX_JSON_BYTES:
                raise ProbeFailure("offline_source_config_too_large")
            configuration = json.loads(_blob(archive, entries, config, layout))
            if configuration.get("os") != "linux" or configuration.get("architecture") != "amd64":
                raise ProbeFailure("offline_source_config_platform_mismatch")
            layers = tuple(_descriptor(item, OCI_LAYERS) for item in value.get("layers", []))
            if not layers or len(layers) > 32 or sum(item["size"] for item in layers) > MAX_SOURCE_BYTES:
                raise ProbeFailure("offline_source_layer_bounds_exceeded")
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
        return {"reference": SOURCE_REFERENCE, "index_digest": SOURCE_DIGEST,
                "manifest": manifest, "config": config, "layers": layers,
                "layout_bytes": sum(item.stat().st_size for item in layout.rglob("*") if item.is_file()),
                "source_export_bytes": source.stat().st_size, "platform": "linux/amd64"}
    finally:
        source.unlink(missing_ok=True)
