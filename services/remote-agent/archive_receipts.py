"""Durable archive completion and read-only original-operation reconciliation."""

import hashlib
import json
import os
import re
import tarfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from modules.artifacts.content_files import _directory, regular_at
from modules.artifacts.oci_archive import inspect_oci_archive
from packages.contracts.p1.build_artifacts import ArtifactLimits, artifact_content_ref
from .ledger import RemoteError


_RECEIPT = "artifact-prepare-completed.json"
_MAX_RECEIPT = 65536
_STORAGE = re.compile(r"oci-[0-9a-f]{64}\Z")


def _operation_directory(deployment, directory):
    operation = deployment.operation_id
    if (not operation or operation in {".", ".."} or "/" in operation or "\\" in operation
            or "\0" in operation or Path(directory).name != operation):
        raise RemoteError("remote_archive_directory_invalid")
    # Opens every component with O_NOFOLLOW and checks the existing private final directory.
    # Unlike private_directory this never creates a missing directory.
    return _directory(str(directory))


@contextmanager
def _private_file(directory_fd, name, limit):
    # regular_at pins the inode before opening it for I/O, rejects symlinks,
    # special files and hardlinks, and detects file changes across the read.
    with regular_at(directory_fd, name, limit) as stream:
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise RemoteError("remote_archive_file_not_private")
        yield stream
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise RemoteError("remote_archive_file_not_private")


def _completion(deployment):
    steps = [step for step in deployment.plan.steps
             if step.step_id == "artifact_prepare" and step.kind == "artifact_prepare"]
    artifacts = deployment.manifest.artifacts
    facts = {item.role: item.archive_digest for item in artifacts}
    if len(steps) != 1 or len(facts) != len(artifacts) or not facts:
        raise RemoteError("remote_archive_completion_binding_invalid")
    return {"operation_id": deployment.operation_id, "plan_digest": deployment.plan_digest,
        "input_digest": steps[0].input_digest, "archives": facts}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def record_completed(deployment, directory, facts):
    """Called inside the supervised worker after all physical preparation returned success."""
    expected = _completion(deployment)
    if facts != expected["archives"]:
        raise RemoteError("remote_archive_completion_binding_invalid")
    data = _encoded(expected)
    if len(data) > _MAX_RECEIPT:
        raise RemoteError("remote_archive_completion_binding_invalid")
    try:
        directory_fd = _operation_directory(deployment, directory)
        try:
            temporary = ".artifact-prepare-" + uuid4().hex + ".tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=directory_fd)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            # Publish only fully fsynced bytes; a leftover second link is rejected
            # by the reader if the parent crashes before removing the temporary link.
            os.link(temporary, _RECEIPT, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, ValueError) as error:
        raise RemoteError("remote_archive_receipt_unresolved") from error


def _archive_layers(directory_fd, artifact):
    if not _STORAGE.fullmatch(artifact.storage_id):
        raise RemoteError("remote_archive_identity_invalid")
    limits = ArtifactLimits()
    with _private_file(directory_fd, artifact.storage_id + ".tar", limits.max_archive_bytes) as stream:
        content = inspect_oci_archive(stream, limits)
        if (content.storage_id != artifact.storage_id or content.archive_digest != artifact.archive_digest
                or content.archive_bytes != artifact.archive_bytes or content.platform != artifact.platform
                or content.manifest.digest != artifact.manifest_digest or content.config.digest != artifact.config_digest
                or content.image_id != artifact.image_id or artifact_content_ref(content) != artifact.content_ref):
            raise RemoteError("remote_archive_content_mismatch")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            source = archive.extractfile("blobs/sha256/" + artifact.config_digest[7:])
            if source is None:
                raise RemoteError("remote_archive_content_mismatch")
            with source:
                raw = source.read(limits.max_json_bytes + 1)
        if (len(raw) > limits.max_json_bytes
                or "sha256:" + hashlib.sha256(raw).hexdigest() != artifact.config_digest):
            raise RemoteError("remote_archive_content_mismatch")
        return json.loads(raw)["rootfs"]["diff_ids"]


def _check_image(docker, deployment, artifact, layers):
    tags = deployment.plan.step_inputs["artifact_prepare"]["local_tags"]
    tag = tags[artifact.role]
    identity = deployment.plan.docker_identity_kind
    if identity not in {"oci_manifest", "oci_config"} or artifact.platform != "linux/amd64":
        raise RemoteError("remote_archive_identity_invalid")
    expected = artifact.manifest_digest if identity == "oci_manifest" else artifact.config_digest
    actual = docker.api("GET", "/images/" + quote(tag, safe="") + "/json")
    if (not isinstance(actual, dict) or actual.get("Id") != expected or actual.get("Os") != "linux"
            or actual.get("Architecture") != "amd64" or actual.get("RootFS", {}).get("Layers") != layers):
        raise RemoteError("remote_loaded_image_identity_mismatch")


def query_completed(docker, deployment, directory):
    """Only observe the original operation; absence or ambiguity always remains unknown."""
    try:
        completion = _completion(deployment)
        directory_fd = _operation_directory(deployment, directory)
        try:
            with _private_file(directory_fd, _RECEIPT, _MAX_RECEIPT) as stream:
                if stream.read(_MAX_RECEIPT + 1) != _encoded(completion):
                    return {"status": "unknown"}
            artifacts = deployment.manifest.artifacts
            if set(deployment.plan.step_inputs["artifact_prepare"]["local_tags"]) != set(completion["archives"]):
                return {"status": "unknown"}
            for artifact in artifacts:
                layers = _archive_layers(directory_fd, artifact)
                _check_image(docker, deployment, artifact, layers)
            return {"status": "succeeded", "archives": completion["archives"]}
        finally:
            os.close(directory_fd)
    except Exception:
        # Do not disclose paths, daemon output or file content in a reconciliation result.
        return {"status": "unknown"}
