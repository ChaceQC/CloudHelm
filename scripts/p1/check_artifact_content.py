"""Synthetic OCI content checks; no Docker or product acceptance."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path

from modules.artifacts.content_store import ArtifactStore
from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.build_artifacts import (
    ArtifactLimits, OCI_CONFIG, OCI_LAYER, OCI_LAYER_GZIP, OCI_MANIFEST,
    artifact_content_bytes, artifact_content_ref,
)

METHOD = "p1-artifact-content-r2"


def require(value: bool, code: str) -> None:
    if not value:
        raise RuntimeError(code)


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def descriptor(value: bytes, media_type: str) -> dict:
    return {"mediaType": media_type, "digest": digest(value), "size": len(value)}


def archive(members) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.size = kind, 0o644, len(data)
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                info.linkname = "../../outside"
            tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def image(*, compressed: bool = False, bad_size: bool = False):
    layer = archive([("synthetic.txt", b"synthetic artifact content\n", tarfile.REGTYPE)])
    blob = gzip.compress(layer, mtime=0) if compressed else layer
    config = encoded({
        "architecture": "amd64", "os": "linux", "config": {},
        "rootfs": {"type": "layers", "diff_ids": [digest(layer)]},
    })
    config_descriptor = descriptor(config, OCI_CONFIG)
    if bad_size:
        config_descriptor["size"] += 1
    manifest = encoded({
        "schemaVersion": 2, "mediaType": OCI_MANIFEST, "config": config_descriptor,
        "layers": [descriptor(blob, OCI_LAYER_GZIP if compressed else OCI_LAYER)],
    })
    members = [
        ("oci-layout", encoded({"imageLayoutVersion": "1.0.0"}), tarfile.REGTYPE),
        ("index.json", encoded({"schemaVersion": 2, "manifests": [descriptor(manifest, OCI_MANIFEST)]}),
         tarfile.REGTYPE),
    ]
    members.extend(("blobs/sha256/" + digest(value)[7:], value, tarfile.REGTYPE)
                   for value in (manifest, config, blob))
    return members


def rejection(call, expected: str) -> None:
    try:
        call()
    except ArtifactContentError as failure:
        require(failure.code == expected, "unexpected_rejection_" + failure.code)
    else:
        raise RuntimeError("expected_rejection_missing_" + expected)


def content_checks(base: Path, store: ArtifactStore, source: Path):
    members = image()
    good = archive(members)
    source.write_bytes(good)
    receipt = store.publish(source, expected_archive_digest=digest(good))
    require(store.query(receipt.storage_id) == receipt, "query_receipt_changed")
    require(store.publish(source) == receipt, "publish_not_idempotent")
    require(receipt.archive_bytes == len(good), "archive_size_wrong")
    require(receipt.archive_digest == digest(good), "archive_digest_wrong")
    require(receipt.image_id == receipt.config.digest, "image_identity_wrong")
    ref = artifact_content_ref(receipt)
    require(ref.digest == digest(artifact_content_bytes(receipt)), "metadata_digest_wrong")
    require(ref.digest != receipt.archive_digest, "metadata_reuses_archive_digest")
    with store.open_archive(receipt.storage_id) as stream:
        require(not stream.writable(), "archive_stream_writable")
        require(digest(stream.read()) == receipt.archive_digest, "archive_stream_digest_wrong")

    stored = base / "content" / receipt.storage_id
    archive_path = stored / "archive.oci.tar"
    original = archive_path.read_bytes()
    archive_path.chmod(0o600)
    rejection(lambda: store.query(receipt.storage_id), "artifact_published_content_writable")
    archive_path.write_bytes(original.replace(b"synthetic artifact", b"tampered artifact", 1))
    archive_path.chmod(0o400)
    rejection(lambda: store.query(receipt.storage_id), "artifact_blob_digest_mismatch")
    archive_path.chmod(0o600)
    archive_path.write_bytes(original)
    archive_path.chmod(0o400)

    compressed = archive(image(compressed=True))
    source.write_bytes(compressed)
    require(store.publish(source).layers[0].media_type == OCI_LAYER_GZIP, "gzip_layer_type_missing")
    source.write_bytes(good)
    rejection(lambda: store.publish(
        source, expected_archive_digest="sha256:" + "0" * 64),
        "artifact_expected_digest_mismatch")

    damaged = list(members)
    name, data, kind = damaged[-1]
    damaged[-1] = (name, data.replace(b"synthetic artifact", b"tampered artifact", 1), kind)
    cases = (
        (archive(damaged), "artifact_blob_digest_mismatch"),
        (archive(image(bad_size=True)), "artifact_descriptor_mismatch"),
        (archive(members + [("../outside", b"", tarfile.REGTYPE)]), "artifact_member_path_invalid"),
        (archive(members + [("link", b"", tarfile.SYMTYPE)]), "artifact_member_type_unsupported"),
        (archive(members + [members[0]]), "artifact_member_duplicate"),
        (archive(members[:-1]), "artifact_blob_missing"),
        (good + b"trailing", "artifact_tar_trailing_content"),
        (good[:300], "artifact_tar_truncated"),
    )
    for payload, expected in cases:
        source.write_bytes(payload)
        rejection(lambda: store.publish(source), expected)
        require(not list((base / "content").glob("stage-*")), "failed_intake_left_staging")
    source.write_bytes(good)
    return receipt


def boundary_checks(base: Path, store: ArtifactStore, source: Path, receipt) -> None:
    linked = base / "incoming" / "linked.tar"
    linked.symlink_to(source.name)
    rejection(lambda: store.publish(linked), "artifact_storage_not_service_owned")
    linked.unlink()
    os.link(source, linked)
    rejection(lambda: store.publish(source), "artifact_storage_hardlink_forbidden")
    linked.unlink()
    rejection(lambda: store.query("../outside"), "artifact_storage_id_invalid")

    for limits, expected in (
        (ArtifactLimits(max_archive_bytes=1024), "artifact_archive_too_large"),
        (ArtifactLimits(max_members=4), "artifact_member_limit_exceeded"),
        (ArtifactLimits(max_json_bytes=256), "artifact_json_too_large"),
        (ArtifactLimits(max_layers=0), "artifact_layers_invalid"),
    ):
        with ArtifactStore(base / "content", limits=limits) as limited:
            rejection(lambda: limited.publish(source), expected)
    require(store.query(receipt.storage_id) == receipt, "restored_query_failed")
    require(not list((base / "content").glob("stage-*")), "staging_cleanup_incomplete")


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="cloudhelm-artifact-content-") as temporary:
            base = Path(temporary)
            (base / "incoming").mkdir(mode=0o700)
            (base / "content").mkdir(mode=0o700)
            source = base / "incoming" / "image.oci.tar"
            with ArtifactStore(base / "content") as store:
                receipt = content_checks(base, store, source)
                boundary_checks(base, store, source, receipt)
        print(json.dumps({
            "status": "passed", "method": METHOD,
            "archive_digest": receipt.archive_digest, "image_id": receipt.image_id,
            "scope": "synthetic OCI content only", "docker_load": "not_run",
        }))
        return 0
    except Exception as failure:
        reason = failure.code if isinstance(failure, ArtifactContentError) else type(failure).__name__
        if type(failure) is RuntimeError:
            reason = str(failure)
        print(json.dumps({"status": "failed", "method": METHOD, "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
