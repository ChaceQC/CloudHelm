"""Verify real OCI bytes, measure unpacked layers, then load the registered identity mode."""

import gzip
import io
import json
import os
import tarfile

from modules.artifacts.oci_archive import inspect_oci_archive
from packages.contracts.p1.build_artifacts import ArtifactLimits
from .ledger import RemoteError


def _member(archive, name, size, stream):
    entry = tarfile.TarInfo(name)
    entry.size, entry.mode = size, 0o400
    archive.addfile(entry, stream)


def _layer(archive, descriptor):
    raw = archive.extractfile("blobs/sha256/" + descriptor["digest"][7:])
    return gzip.GzipFile(fileobj=raw) if descriptor["mediaType"].endswith("+gzip") else raw


def prepare(channel, docker, deployment, directory, *, check_resources):
    artifacts = deployment.manifest.artifacts
    budget = deployment.plan.configuration.resources.disk_bytes
    paths, unpacked = {}, {}
    for artifact in artifacts:
        limits = check_resources()
        if limits["available_bytes"] < artifact.archive_bytes:
            raise RemoteError("remote_archive_space_insufficient")
        path = directory / (artifact.storage_id + ".tar")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            channel.download(deployment.operation_id, artifact, output)
            output.flush()
            os.fsync(output.fileno())
        with path.open("rb") as stream:
            receipt = inspect_oci_archive(stream, ArtifactLimits())
            if (receipt.archive_digest != artifact.archive_digest or receipt.archive_bytes != artifact.archive_bytes
                    or receipt.manifest.digest != artifact.manifest_digest or receipt.config.digest != artifact.config_digest):
                raise RemoteError("remote_archive_content_mismatch")
        sizes = []
        with tarfile.open(path, "r:") as archive:
            manifest = json.load(archive.extractfile("blobs/sha256/" + artifact.manifest_digest[7:]))
            for layer in manifest["layers"]:
                size = 0
                with _layer(archive, layer) as stream:
                    while chunk := stream.read(65536):
                        size += len(chunk)
                        if size + sum(sizes) + sum(unpacked.values()) > budget:
                            raise RemoteError("remote_unpack_bound_exceeded")
                sizes.append(size)
        paths[artifact.role], unpacked[artifact.role] = (path, manifest, sizes), sum(sizes)
    required = sum(unpacked.values()) + max(unpacked.values()) + sum(item.archive_bytes for item in artifacts)
    if required > check_resources()["available_bytes"]:
        raise RemoteError("remote_load_coexistence_space_insufficient")
    for artifact in artifacts:
        check_resources()
        path, manifest, sizes = paths[artifact.role]
        tag = deployment.plan.step_inputs["artifact_prepare"]["local_tags"][artifact.role]
        if deployment.plan.docker_identity_kind == "oci_manifest":
            with path.open("rb") as stream:
                docker.command("image", "load", "--quiet", stdin=stream, timeout=120)
            expected = artifact.manifest_digest
            docker.command("image", "tag", expected, tag)
        else:
            expected = artifact.config_digest
            _load_classic(docker, directory, artifact, path, manifest, sizes, tag)
        actual = json.loads(docker.command("image", "inspect", tag))
        with tarfile.open(path, "r:") as archive:
            configuration = json.load(archive.extractfile("blobs/sha256/" + artifact.config_digest[7:]))
        if (len(actual) != 1 or actual[0]["Id"] != expected
                or actual[0].get("Os") != "linux" or actual[0].get("Architecture") != "amd64"
                or actual[0].get("RootFS", {}).get("Layers") != configuration["rootfs"]["diff_ids"]):
            raise RemoteError("remote_loaded_image_identity_mismatch")
    return {item.role: item.archive_digest for item in artifacts}


def _load_classic(docker, directory, artifact, path, manifest, sizes, tag):
    converted = directory / (artifact.role + ".docker.tar")
    layers = [str(index) + "/layer.tar" for index in range(len(sizes))]
    index = json.dumps([{"Config": "config.json", "RepoTags": [tag], "Layers": layers}], separators=(",", ":")).encode("utf-8")
    descriptor = os.open(converted, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output, tarfile.open(fileobj=output, mode="w|") as target, tarfile.open(path, "r:") as source:
            config = source.extractfile("blobs/sha256/" + artifact.config_digest[7:]).read(1024 * 1024 + 1)
            if len(config) > 1024 * 1024:
                raise RemoteError("remote_image_config_too_large")
            _member(target, "manifest.json", len(index), io.BytesIO(index))
            _member(target, "config.json", len(config), io.BytesIO(config))
            for name, layer, size in zip(layers, manifest["layers"], sizes):
                with _layer(source, layer) as stream:
                    _member(target, name, size, stream)
        with converted.open("rb") as stream:
            docker.command("image", "load", "--quiet", stdin=stream, timeout=120)
    finally:
        converted.unlink(missing_ok=True)
