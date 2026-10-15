"""Synthetic OCI content safety checks; no Docker, BuildRun or product acceptance."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from modules.artifacts.content_store import ArtifactStore
from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.build_artifacts import (
    ArtifactLimits, OCI_CONFIG, OCI_LAYER, OCI_LAYER_GZIP, OCI_MANIFEST,
    artifact_content_bytes, artifact_content_ref,
)

METHOD = "p1-artifact-content-r1"


def require(value: bool, code: str) -> None:
    if not value:
        raise RuntimeError(code)


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def descriptor(value, media_type):
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


def image(*, compressed=False, architecture="amd64", wrong_size=False,
          media_type=OCI_MANIFEST, remote=False, multiple=False):
    layer = archive([("synthetic.txt", b"synthetic artifact content\n", tarfile.REGTYPE)])
    blob = gzip.compress(layer, mtime=0) if compressed else layer
    layer_type = OCI_LAYER_GZIP if compressed else OCI_LAYER
    config = encoded({"architecture": architecture, "os": "linux", "config": {},
                      "rootfs": {"type": "layers", "diff_ids": [digest(layer)]}})
    config_descriptor = descriptor(config, OCI_CONFIG)
    if wrong_size:
        config_descriptor["size"] += 1
    if remote:
        config_descriptor["urls"] = ["https://invalid.example/never-fetch"]
    manifest = encoded({"schemaVersion": 2, "mediaType": OCI_MANIFEST,
                        "config": config_descriptor, "layers": [descriptor(blob, layer_type)]})
    manifests = [descriptor(manifest, media_type)]
    if multiple:
        manifests *= 2
    index = encoded({"schemaVersion": 2, "manifests": manifests})
    members = [("oci-layout", encoded({"imageLayoutVersion": "1.0.0"}), tarfile.REGTYPE),
               ("index.json", index, tarfile.REGTYPE)]
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


def content_checks(base: Path, store: ArtifactStore, source: Path) -> tuple[int, object]:
    good = archive(image())
    source.write_bytes(good)
    receipt = store.publish(source, expected_archive_digest=digest(good))
    require(store.query(receipt.storage_id) == receipt, "query_receipt_changed")
    require(store.publish(source) == receipt, "publish_not_idempotent")
    require(receipt.archive_bytes == len(good) and receipt.archive_digest == digest(good), "archive_identity_wrong")
    require(receipt.image_id == receipt.config.digest and len(receipt.layers) == 1, "image_identity_wrong")
    ref = artifact_content_ref(receipt)
    require(ref.digest == digest(artifact_content_bytes(receipt)), "metadata_reference_digest_wrong")
    require(ref.digest != receipt.archive_digest, "metadata_reference_uses_archive_digest")
    with store.open_archive(receipt.storage_id) as stream:
        require(not stream.writable() and digest(stream.read()) == receipt.archive_digest, "archive_stream_wrong")
        try:
            os.write(stream.fileno(), b"x")
        except OSError:
            pass
        else:
            raise RuntimeError("archive_fd_writable")
    stored = base / "content" / receipt.storage_id
    require(stored.stat().st_mode & 0o777 == 0o500, "published_directory_not_readonly")
    require(all(path.stat().st_mode & 0o777 == 0o400 for path in stored.iterdir()), "published_files_not_readonly")
    source.write_bytes(archive(image(compressed=True)))
    require(store.publish(source).layers[0].media_type == OCI_LAYER_GZIP, "gzip_identity_missing")

    cases = []
    tampered = image()
    name, data, kind = tampered[-1]
    tampered[-1] = (name, data.replace(b"synthetic artifact", b"tampered! artifact", 1), kind)
    cases.append((archive(tampered), "artifact_blob_digest_mismatch"))
    cases.append((archive(image(wrong_size=True)), "artifact_descriptor_mismatch"))
    cases.append((archive(image(architecture="arm64")), "artifact_platform_unsupported"))
    cases.append((archive(image(media_type="application/vnd.docker.distribution.manifest.v2+json")),
                  "artifact_media_type_unsupported"))
    cases.append((archive(image(remote=True)), "artifact_descriptor_unsupported"))
    cases.append((archive(image(multiple=True)), "artifact_single_image_required"))
    cases.append((archive(image()[:-1]), "artifact_blob_missing"))
    extra = b"unreferenced blob"
    cases.append((archive(image() + [("blobs/sha256/" + digest(extra)[7:], extra, tarfile.REGTYPE)]),
                  "artifact_unreferenced_member"))
    for name in ("../outside", "/outside", "blobs/../../outside"):
        cases.append((archive(image() + [(name, b"", tarfile.REGTYPE)]), "artifact_member_path_invalid"))
    cases.append((archive(image() + [image()[0]]), "artifact_member_duplicate"))
    for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.XHDTYPE):
        cases.append((archive(image() + [("untrusted", b"", kind)]), "artifact_member_type_unsupported"))
    cases.append((archive(image() + [("manifest.json", b"{}", tarfile.REGTYPE)]), "artifact_member_unrecognized"))
    duplicate_json = image()
    duplicate_json[1] = ("index.json", b'{"schemaVersion":2,"schemaVersion":2}', tarfile.REGTYPE)
    cases.append((archive(duplicate_json), "artifact_json_duplicate_key"))
    cases.append((good + b"nonzero trailing content", "artifact_tar_trailing_content"))
    cases.append((good[:300], "artifact_tar_truncated"))
    for payload, expected in cases:
        source.write_bytes(payload)
        rejection(lambda: store.publish(source), expected)
        require(not list((base / "content").glob("stage-*")), "failed_intake_left_staging")
    source.write_bytes(good)
    rejection(lambda: store.publish(source, expected_archive_digest="sha256:" + "0" * 64),
              "artifact_expected_digest_mismatch")
    for limits, expected in (
        (ArtifactLimits(max_archive_bytes=1024), "artifact_archive_too_large"),
        (ArtifactLimits(max_members=4), "artifact_member_limit_exceeded"),
        (ArtifactLimits(max_json_bytes=256), "artifact_json_too_large"),
        (ArtifactLimits(max_layers=0), "artifact_layers_invalid"),
    ):
        with ArtifactStore(base / "content", limits=limits) as limited:
            rejection(lambda: limited.publish(source), expected)
    return len(cases) + 5, receipt


def storage_checks(base: Path, store: ArtifactStore, source: Path, receipt) -> int:
    source_link = base / "incoming" / "linked.tar"
    source_link.symlink_to(source.name)
    rejection(lambda: store.publish(source_link), "artifact_storage_not_service_owned")
    source_link.unlink()
    os.link(source, source_link)
    rejection(lambda: store.publish(source), "artifact_storage_hardlink_forbidden")
    source_link.unlink()
    os.mkfifo(source_link)
    rejection(lambda: store.publish(source_link), "artifact_storage_not_service_owned")
    source_link.unlink()
    parent_link = base / "incoming-link"
    parent_link.symlink_to("incoming", target_is_directory=True)
    rejection(lambda: store.publish(parent_link / source.name), "artifact_storage_unavailable")
    rejection(lambda: store.query("../outside"), "artifact_storage_id_invalid")

    stored = base / "content" / receipt.storage_id
    archive_path, metadata_path = stored / "archive.oci.tar", stored / "receipt.json"
    original = archive_path.read_bytes()
    archive_path.chmod(0o600)
    rejection(lambda: store.query(receipt.storage_id), "artifact_published_content_writable")
    archive_path.write_bytes(original.replace(b"synthetic artifact", b"tampered! artifact", 1))
    archive_path.chmod(0o400)
    rejection(lambda: store.query(receipt.storage_id), "artifact_blob_digest_mismatch")
    archive_path.chmod(0o600)
    archive_path.write_bytes(original)
    archive_path.chmod(0o400)
    metadata = metadata_path.read_bytes()
    metadata_path.chmod(0o600)
    changed_metadata = json.loads(metadata)
    changed_metadata["image_id"] = "sha256:" + "0" * 64
    metadata_path.write_bytes(encoded(changed_metadata))
    metadata_path.chmod(0o400)
    rejection(lambda: store.query(receipt.storage_id), "artifact_receipt_invalid")
    metadata_path.chmod(0o600)
    metadata_path.write_bytes(metadata)
    metadata_path.chmod(0o400)
    require(store.query(receipt.storage_id) == receipt, "restored_query_failed")

    conflict_root = base / "conflict"
    conflict_root.mkdir(mode=0o700)
    conflict = conflict_root / receipt.storage_id
    conflict.mkdir(mode=0o700)
    sentinel = conflict / "sentinel"
    sentinel.write_bytes(b"do not replace")
    conflict.chmod(0o500)
    with ArtifactStore(conflict_root) as conflicting:
        rejection(lambda: conflicting.publish(source), "artifact_storage_members_mismatch")
    require(sentinel.read_bytes() == b"do not replace", "conflict_was_overwritten")
    require(not list(conflict_root.glob("stage-*")), "conflict_left_staging")
    return 9


def main() -> int:
    started_at = datetime.now(UTC).isoformat()
    try:
        with tempfile.TemporaryDirectory(prefix="cloudhelm-artifact-content-") as temporary:
            base = Path(temporary)
            (base / "incoming").mkdir(mode=0o700)
            (base / "content").mkdir(mode=0o700)
            source = base / "incoming" / "image.oci.tar"
            with ArtifactStore(base / "content") as store:
                content_rejections, receipt = content_checks(base, store, source)
                storage_rejections = storage_checks(base, store, source, receipt)
                require(not list((base / "content").glob("stage-*")), "staging_cleanup_incomplete")
        print(json.dumps({"status": "passed", "method": METHOD, "started_at": started_at,
                          "finished_at": datetime.now(UTC).isoformat(), "content_rejections": content_rejections,
                          "storage_rejections": storage_rejections, "archive_digest": receipt.archive_digest,
                          "archive_bytes": receipt.archive_bytes, "image_id": receipt.image_id,
                          "read_only_fd": True, "query_revalidates": True, "cleanup": "complete",
                          "input_kind": "development_worktree", "scope": "synthetic OCI content safety only",
                          "docker_load": "not_run", "complete_scope": False}))
        return 0
    except Exception as failure:
        reason = failure.code if isinstance(failure, ArtifactContentError) else type(failure).__name__
        if type(failure) is RuntimeError:
            reason = str(failure)
        print(json.dumps({"status": "failed", "method": METHOD, "started_at": started_at,
                          "finished_at": datetime.now(UTC).isoformat(), "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
