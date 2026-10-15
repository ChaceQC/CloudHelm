"""Strict, bounded OCI tar inspection; no layer is extracted or executed."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
from dataclasses import dataclass
from typing import BinaryIO

from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.build_artifacts import (
    ArtifactContent, ArtifactLimits, OciDescriptor,
    OCI_CONFIG, OCI_LAYER, OCI_LAYER_GZIP, OCI_MANIFEST,
)

_BLOB = re.compile(r"blobs/sha256/([0-9a-f]{64})\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INDEX = "application/vnd.oci.image.index.v1+json"
_BLOCK = 512


@dataclass(frozen=True)
class _Entry:
    offset: int
    size: int
    digest: str


def _reject(code: str) -> None:
    raise ArtifactContentError(code)


def _members(stream: BinaryIO, limits: ArtifactLimits) -> tuple[dict[str, _Entry], str, int]:
    stream.seek(0)
    archive_hash, total, members, seen, entries = hashlib.sha256(), 0, 0, set(), {}

    def read(size: int) -> bytes:
        nonlocal total
        data = stream.read(size)
        total += len(data)
        if total > limits.max_archive_bytes:
            _reject("artifact_archive_too_large")
        archive_hash.update(data)
        return data

    while True:
        header = read(_BLOCK)
        if len(header) != _BLOCK:
            _reject("artifact_tar_truncated")
        if header == bytes(_BLOCK):
            if read(_BLOCK) != bytes(_BLOCK):
                _reject("artifact_tar_end_invalid")
            while tail := read(65536):
                if any(tail):
                    _reject("artifact_tar_trailing_content")
            if total % _BLOCK:
                _reject("artifact_tar_alignment_invalid")
            return entries, "sha256:" + archive_hash.hexdigest(), total
        members += 1
        if members > limits.max_members:
            _reject("artifact_member_limit_exceeded")
        try:
            entry = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError, ValueError):
            _reject("artifact_tar_header_invalid")
        if header[257:263] not in {b"ustar\0", b"ustar "}:
            _reject("artifact_tar_format_unsupported")
        if entry.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE} or entry.linkname:
            _reject("artifact_member_type_unsupported")
        name = entry.name.removesuffix("/") if entry.isdir() else entry.name
        if (not name or any(part in {"", ".", ".."} for part in name.split("/"))
                or name.startswith("/") or "\\" in name or ":" in name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            _reject("artifact_member_path_invalid")
        if name in seen:
            _reject("artifact_member_duplicate")
        seen.add(name)
        if entry.isdir():
            if name not in {"blobs", "blobs/sha256"} or entry.size != 0:
                _reject("artifact_member_unrecognized")
            continue
        if name not in {"oci-layout", "index.json"} and not _BLOB.fullmatch(name):
            _reject("artifact_member_unrecognized")
        if entry.size < 0 or total + entry.size > limits.max_archive_bytes:
            _reject("artifact_member_too_large")
        if name in {"oci-layout", "index.json"} and entry.size > limits.max_json_bytes:
            _reject("artifact_json_too_large")
        offset, remaining, member_hash = total, entry.size, hashlib.sha256()
        while remaining:
            data = read(min(65536, remaining))
            if not data:
                _reject("artifact_tar_truncated")
            remaining -= len(data)
            member_hash.update(data)
        padding = read((-entry.size) % _BLOCK)
        if len(padding) != (-entry.size) % _BLOCK or any(padding):
            _reject("artifact_tar_padding_invalid")
        digest = "sha256:" + member_hash.hexdigest()
        if (match := _BLOB.fullmatch(name)) and digest != "sha256:" + match[1]:
            _reject("artifact_blob_digest_mismatch")
        entries[name] = _Entry(offset, entry.size, digest)


def _json(stream: BinaryIO, entry: _Entry, limits: ArtifactLimits) -> dict:
    if entry.size > limits.max_json_bytes:
        _reject("artifact_json_too_large")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                _reject("artifact_json_duplicate_key")
            result[key] = value
        return result

    def invalid_number(_):
        _reject("artifact_json_invalid")

    try:
        stream.seek(entry.offset)
        data = stream.read(entry.size)
        if len(data) != entry.size or "sha256:" + hashlib.sha256(data).hexdigest() != entry.digest:
            _reject("artifact_content_changed")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_number)
    except ArtifactContentError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _reject("artifact_json_invalid")
    if not isinstance(value, dict):
        _reject("artifact_json_object_required")
    return value


def _annotations(value) -> None:
    if not isinstance(value, dict) or len(value) > 128 or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        _reject("artifact_annotations_invalid")


def _platform(value) -> None:
    if (not isinstance(value, dict) or set(value) - {"os", "architecture", "variant"}
            or value.get("os") != "linux" or value.get("architecture") != "amd64"
            or value.get("variant", "") != ""):
        _reject("artifact_platform_unsupported")


def _descriptor(value, allowed: set[str], *, platform: bool = False) -> OciDescriptor:
    keys = {"mediaType", "digest", "size", "annotations"} | ({"platform"} if platform else set())
    if not isinstance(value, dict) or set(value) - keys:
        _reject("artifact_descriptor_unsupported")
    if not isinstance(value.get("mediaType"), str) or value["mediaType"] not in allowed:
        _reject("artifact_media_type_unsupported")
    if "annotations" in value:
        _annotations(value["annotations"])
    if "platform" in value:
        _platform(value["platform"])
    try:
        return OciDescriptor(media_type=value["mediaType"], digest=value["digest"], size_bytes=value["size"])
    except (KeyError, ValueError):
        _reject("artifact_descriptor_invalid")


def _described(entries: dict[str, _Entry], descriptor: OciDescriptor) -> _Entry:
    entry = entries.get("blobs/sha256/" + descriptor.digest.removeprefix("sha256:"))
    if entry is None:
        _reject("artifact_blob_missing")
    if entry.size != descriptor.size_bytes or entry.digest != descriptor.digest:
        _reject("artifact_descriptor_mismatch")
    return entry


def _image(stream, entries, manifest, limits):
    value = _json(stream, _described(entries, manifest), limits)
    if (set(value) - {"schemaVersion", "mediaType", "config", "layers", "annotations"}
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 2
            or value.get("mediaType") != OCI_MANIFEST):
        _reject("artifact_manifest_unsupported")
    if "annotations" in value:
        _annotations(value["annotations"])
    config = _descriptor(value.get("config"), {OCI_CONFIG})
    raw_layers = value.get("layers")
    if not isinstance(raw_layers, list) or len(raw_layers) > limits.max_layers:
        _reject("artifact_layers_invalid")
    layers = tuple(_descriptor(layer, {OCI_LAYER, OCI_LAYER_GZIP}) for layer in raw_layers)
    for layer in layers:
        _described(entries, layer)
    config_json = _json(stream, _described(entries, config), limits)
    _platform({key: config_json[key] for key in ("os", "architecture", "variant") if key in config_json})
    rootfs = config_json.get("rootfs")
    if (not isinstance(rootfs, dict) or set(rootfs) != {"type", "diff_ids"}
            or rootfs.get("type") != "layers" or not isinstance(rootfs.get("diff_ids"), list)
            or len(rootfs["diff_ids"]) != len(layers)
            or any(not isinstance(item, str) or not _DIGEST.fullmatch(item) for item in rootfs["diff_ids"])):
        _reject("artifact_rootfs_invalid")
    for layer, diff_id in zip(layers, rootfs["diff_ids"], strict=True):
        if layer.media_type == OCI_LAYER and layer.digest != diff_id:
            _reject("artifact_uncompressed_layer_identity_mismatch")
    return config, layers


def inspect_oci_archive(stream: BinaryIO, limits: ArtifactLimits) -> ArtifactContent:
    """Hash all stored bytes and descriptors; compressed-layer decoding is downstream."""
    entries, digest, size = _members(stream, limits)
    if not {"oci-layout", "index.json"}.issubset(entries):
        _reject("artifact_layout_missing")
    if _json(stream, entries["oci-layout"], limits) != {"imageLayoutVersion": "1.0.0"}:
        _reject("artifact_layout_unsupported")
    index = _json(stream, entries["index.json"], limits)
    if (set(index) - {"schemaVersion", "mediaType", "manifests", "annotations"}
            or type(index.get("schemaVersion")) is not int or index["schemaVersion"] != 2
            or index.get("mediaType", _INDEX) != _INDEX
            or not isinstance(index.get("manifests"), list) or len(index["manifests"]) != 1):
        _reject("artifact_single_image_required")
    if "annotations" in index:
        _annotations(index["annotations"])
    manifest = _descriptor(index["manifests"][0], {OCI_MANIFEST}, platform=True)
    config, layers = _image(stream, entries, manifest, limits)
    expected = {"oci-layout", "index.json"} | {
        "blobs/sha256/" + item.digest.removeprefix("sha256:") for item in (manifest, config, *layers)
    }
    if set(entries) != expected:
        _reject("artifact_unreferenced_member")
    try:
        receipt = ArtifactContent(
            storage_id="oci-" + digest.removeprefix("sha256:"), archive_digest=digest,
            archive_bytes=size, manifest=manifest, config=config, image_id=config.digest, layers=layers,
        )
    except ValueError:
        _reject("artifact_descriptor_identity_conflict")
    stream.seek(0)
    return receipt
