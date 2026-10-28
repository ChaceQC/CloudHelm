"""Trusted OCI loading and a strict archive of the fixed PostgreSQL dependency."""

from __future__ import annotations

import io
import json
import os
import resource
import tarfile
from pathlib import Path

from modules.artifacts.content_store import ArtifactStore
from packages.contracts.p1.build_artifacts import ArtifactContent
from packages.contracts.p1.development_environment import POSTGRES_MANIFEST, POSTGRES_REFERENCE

from .artifact_environment_docker import docker, engine
from .offline_images import OCI_CONFIG, OCI_INDEX, OCI_LAYERS, OCI_MANIFEST, _descriptor
from .toolchain import ProbeFailure

MAX_EXPORT_BYTES = 1024**3


def _new_file(path: Path):
    return os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "wb")


def load(store: ArtifactStore, receipt: ArtifactContent) -> dict:
    with store.open_archive(receipt.storage_id) as stream:
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            with archive.extractfile("blobs/sha256/" + receipt.config.digest[7:]) as configuration:
                expected = json.load(configuration)
        stream.seek(0)
        docker("image", "load", "--quiet", stdin=stream, timeout=120)
    # Docker 29's containerd image store identifies this loaded image by manifest.
    actual = engine("GET", "/images/" + receipt.manifest.digest + "/json")
    keys = ("User", "Cmd", "Entrypoint", "WorkingDir", "Env", "ExposedPorts", "Labels", "Volumes", "Healthcheck", "StopSignal")
    if (actual.get("Id") != receipt.manifest.digest or actual.get("Os") != "linux"
            or actual.get("Architecture") != "amd64"
            or actual.get("Descriptor", {}).get("digest") != receipt.manifest.digest
            or actual.get("RootFS", {}).get("Layers") != expected["rootfs"]["diff_ids"]
            or any((actual["Config"].get(key) or None) != (expected["config"].get(key) or None) for key in keys)):
        raise ProbeFailure("artifact_environment_loaded_image_identity_mismatch")
    return {"archive_digest": receipt.archive_digest, "manifest_digest": receipt.manifest.digest,
            "config_digest": receipt.config.digest, "oci_config_image_id": receipt.image_id,
            "actual_image_id": actual["Id"], "docker_identity_kind": "oci_manifest",
            "rootfs_diff_ids_and_runtime_configuration_verified": True, "platform": "linux/amd64"}


def _tar_member(target, name: str, size: int, source):
    member = tarfile.TarInfo(name)
    member.size, member.mode, member.mtime = size, 0o400, 0
    target.addfile(member, source)


def _blob(source, entries: dict, descriptor: dict):
    name = "blobs/sha256/" + descriptor["digest"][7:]
    entry = entries.get(name)
    if entry is None or not entry.isfile() or entry.size != descriptor["size"]:
        raise ProbeFailure("artifact_environment_postgres_blob_unavailable")
    return name, entry


def _filtered_export(source_path: Path, target_path: Path, manifest: dict):
    """Keep only the pinned manifest graph; Docker compatibility entries are omitted."""
    with tarfile.open(source_path, "r:") as source, _new_file(target_path) as output:
        members = source.getmembers()
        if len(members) > 1024 or len({item.name for item in members}) != len(members):
            raise ProbeFailure("artifact_environment_postgres_export_members_invalid")
        entries = {item.name: item for item in members}
        _, entry = _blob(source, entries, manifest)
        if entry.size > 1024**2:
            raise ProbeFailure("artifact_environment_postgres_manifest_too_large")
        value = json.load(source.extractfile(entry))
        if value.get("schemaVersion") != 2 or value.get("mediaType") != OCI_MANIFEST:
            raise ProbeFailure("artifact_environment_postgres_manifest_invalid")
        config = _descriptor(value.get("config"), {OCI_CONFIG})
        layers = tuple(_descriptor(item, OCI_LAYERS) for item in value.get("layers", []))
        if not layers or len(layers) > 64 or sum(item["size"] for item in layers) > MAX_EXPORT_BYTES:
            raise ProbeFailure("artifact_environment_postgres_layer_bounds_exceeded")
        index = {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
            manifest | {"platform": {"os": "linux", "architecture": "amd64"}}]}
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as target:
            for name, raw in (("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'),
                              ("index.json", json.dumps(index, separators=(",", ":")).encode("utf-8"))):
                _tar_member(target, name, len(raw), io.BytesIO(raw))
            for descriptor in (manifest, config, *layers):
                name, entry = _blob(source, entries, descriptor)
                with source.extractfile(entry) as stream:
                    _tar_member(target, name, entry.size, stream)
        output.flush()
        os.fsync(output.fileno())


def export_postgres(store: ArtifactStore, directory: Path, *, before_side_effect=None) -> ArtifactContent:
    gate = before_side_effect or (lambda: None)
    # Selected from the compose-pinned index and fixed independently for amd64.
    manifest = {"mediaType": OCI_MANIFEST, "digest": POSTGRES_MANIFEST, "size": 3628}
    present = docker("image", "inspect", POSTGRES_REFERENCE, "--format", "{{.Id}}", required=False)
    if present.returncode:
        gate()
        docker("pull", "--platform=linux/amd64", POSTGRES_REFERENCE, timeout=240)
    actual = json.loads(docker("image", "inspect", POSTGRES_REFERENCE, "--format", "{{json .Descriptor}}").stdout)
    if actual.get("digest") != POSTGRES_REFERENCE.rsplit("@", 1)[1]:
        raise ProbeFailure("artifact_environment_postgres_reference_drift")
    source, target = directory / "postgres-source.tar", directory / "postgres.oci.tar"

    def limit_export():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_EXPORT_BYTES, MAX_EXPORT_BYTES))

    try:
        # The file itself is on the admitted fixed-size filesystem.
        with _new_file(source) as output:
            gate()
            docker("image", "save", "--platform=linux/amd64", POSTGRES_REFERENCE,
                   stdout=output, timeout=120, preexec_fn=limit_export)
            output.flush()
            os.fsync(output.fileno())
        if not 0 < source.stat().st_size <= MAX_EXPORT_BYTES:
            raise ProbeFailure("artifact_environment_postgres_export_bound_exceeded")
        _filtered_export(source, target, manifest)
        gate()
        result = store.publish(target)
        if result.manifest.digest != manifest["digest"]:
            raise ProbeFailure("artifact_environment_postgres_manifest_mismatch")
        return result
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
