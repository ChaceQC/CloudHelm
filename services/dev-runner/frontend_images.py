"""Prepare two pinned frontend bases as local OCI layouts and verify the build output."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import resource
import subprocess
import tarfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.artifacts.content_files import ArtifactRoot, directory_at, publish_directory, regular_at
from modules.artifacts.errors import ArtifactContentError
from modules.workspaces.safe_paths import exists_at
from packages.contracts.p1.npm_cache import NODE_IMAGE
from packages.contracts.p1.workspace_git import content_digest

from .offline_images import (
    MAX_JSON_BYTES, OCI_CONFIG, OCI_INDEX, OCI_LAYERS, OCI_MANIFEST,
    _blob, _descriptor, _write_new,
)
from .toolchain import DOCKER, DockerClient, ProbeFailure, private_directory, safe_diagnostic

NGINX_IMAGE = "nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de"
BASES = {"node": NODE_IMAGE, "nginx": NGINX_IMAGE}
FRONTEND_IMAGE_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/engineering-seeds/frontend-images")
AMD64 = {"os": "linux", "architecture": "amd64"}
LAYOUT_VERSION = b'{"imageLayoutVersion":"1.0.0"}\n'
MAX_EXPORT_BYTES = 384 * 1024**2
MAX_LAYER_BYTES = 256 * 1024**2
HTML_ROOT = "usr/share/nginx/html"
NGINX_CONFIG = "etc/nginx/conf.d/default.conf"
PROTECTED_DIRECTORIES = {"usr", "usr/share", "usr/share/nginx", HTML_ROOT,
                         "etc", "etc/nginx", "etc/nginx/conf.d"}


def _export(client: DockerClient, reference: str, target: Path) -> None:
    digest = reference.rsplit("@", 1)[1]
    inspected = client.run("image", "inspect", reference, "--format", "{{json .Descriptor}}", required=False)
    if inspected.returncode:
        raise ProbeFailure("frontend_base_local_image_unavailable")
    metadata = json.loads(inspected.stdout)
    if not isinstance(metadata, dict) or metadata.get("digest") != digest:
        raise ProbeFailure("frontend_base_local_reference_mismatch")
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "DOCKER_CONFIG": str(client.config_directory)}

    def limit_file():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_EXPORT_BYTES, MAX_EXPORT_BYTES))

    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            result = subprocess.run([DOCKER, "--host", "unix://" + client.endpoint,
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


def frontend_layout_path(name: str) -> Path:
    return FRONTEND_IMAGE_ROOT / BASES[name].rsplit("@sha256:", 1)[1]


def _amd64_manifest(raw: bytes, digest: str) -> dict:
    if content_digest(raw) != digest:
        raise ProbeFailure("frontend_base_index_digest_mismatch")
    root = json.loads(raw)
    if (not isinstance(root, dict) or root.get("schemaVersion") != 2
            or root.get("mediaType") != OCI_INDEX or not isinstance(root.get("manifests"), list)):
        raise ProbeFailure("frontend_base_index_unsupported")
    matches = [item for item in root["manifests"] if isinstance(item, dict) and item.get("platform") == AMD64]
    if len(matches) != 1:
        raise ProbeFailure("frontend_base_amd64_manifest_not_unique")
    manifest = _descriptor(matches[0], {OCI_MANIFEST})
    if manifest["size"] > MAX_JSON_BYTES:
        raise ProbeFailure("frontend_base_manifest_too_large")
    return manifest


def _layout_index(manifest: dict) -> bytes:
    index = {"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [manifest | {"platform": AMD64}]}
    return json.dumps(index, separators=(",", ":")).encode("utf-8")


def _verify_graph(reference, raw, manifest, read_blob) -> dict:
    value = json.loads(read_blob(manifest))
    if value.get("mediaType") != OCI_MANIFEST or value.get("schemaVersion") != 2:
        raise ProbeFailure("frontend_base_manifest_unsupported")
    config = _descriptor(value.get("config"), {OCI_CONFIG})
    if config["size"] > MAX_JSON_BYTES:
        raise ProbeFailure("frontend_base_config_too_large")
    configuration = json.loads(read_blob(config))
    if {key: configuration.get(key) for key in AMD64} != AMD64:
        raise ProbeFailure("frontend_base_config_platform_mismatch")
    layers = tuple(_descriptor(item, OCI_LAYERS) for item in value.get("layers", []))
    layer_bytes = sum(item["size"] for item in layers)
    if not layers or len(layers) > 32 or layer_bytes > MAX_EXPORT_BYTES:
        raise ProbeFailure("frontend_base_layer_bounds_exceeded")
    for layer in layers:
        read_blob(layer)
    return {"reference": reference, "index_digest": reference.rsplit("@", 1)[1], "index_bytes": len(raw),
            "manifest": manifest, "config": config, "layers": layers, "platform": "linux/amd64",
            "layout_bytes": len(raw) + len(LAYOUT_VERSION) + len(_layout_index(manifest))
            + manifest["size"] + config["size"] + layer_bytes}


def _prepare_layout(work: Path, layout: Path, name: str) -> dict:
    reference = BASES[name]
    digest = reference.rsplit("@", 1)[1]
    client = DockerClient.create(work)
    raw = client.fetch_frontend_base_index(reference)
    manifest = _amd64_manifest(raw, digest)
    source = work / "export.tar"
    blobs = layout / "blobs" / "sha256"
    blobs.mkdir(mode=0o700, parents=True)
    _export(client, reference, source)
    try:
        with tarfile.open(source, "r:") as archive:
            members = archive.getmembers()
            entries = {item.name: item for item in members}
            if len(members) > 1024 or len(members) != len(entries):
                raise ProbeFailure("frontend_base_export_members_invalid")
            receipt = _verify_graph(reference, raw, manifest, lambda item: _blob(archive, entries, item, layout))
    except tarfile.TarError:
        raise ProbeFailure("frontend_base_export_invalid") from None
    _write_new(blobs / digest[7:], raw)
    _write_new(layout / "oci-layout", LAYOUT_VERSION)
    _write_new(layout / "index.json", _layout_index(manifest))
    for directory in (blobs, blobs.parent, layout):
        directory.chmod(0o500)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return receipt


def _verify_layout(root: int, name: str) -> dict:
    reference = BASES[name]
    digest = reference.rsplit("@", 1)[1]
    with (directory_at(root, frontend_layout_path(name).name, readonly=True) as layout,
          directory_at(layout, "blobs", readonly=True) as blobs,
          directory_at(blobs, "sha256", readonly=True) as sha256):
        with regular_at(sha256, digest[7:], MAX_JSON_BYTES, readonly=True) as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        manifest = _amd64_manifest(raw, digest)
        for filename, expected in (("oci-layout", LAYOUT_VERSION), ("index.json", _layout_index(manifest))):
            with regular_at(layout, filename, MAX_JSON_BYTES, readonly=True) as stream:
                if stream.read(len(expected) + 1) != expected:
                    raise ProbeFailure("frontend_base_layout_index_mismatch")

        def read_blob(item):
            with regular_at(sha256, item["digest"][7:], item["size"], readonly=True) as stream:
                if os.fstat(stream.fileno()).st_size != item["size"]:
                    raise ProbeFailure("frontend_base_blob_size_mismatch")
                if item["mediaType"] in {OCI_MANIFEST, OCI_CONFIG}:
                    data = stream.read(item["size"] + 1)
                    observed = content_digest(data)
                else:
                    data = None
                    observed = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
                if observed != item["digest"]:
                    raise ProbeFailure("frontend_base_blob_digest_mismatch")
            return data

        return _verify_graph(reference, raw, manifest, read_blob)


def prepare_frontend_layouts() -> dict:
    """Trusted maintenance only: use preloaded images and fetch each missing raw index."""
    private_directory(FRONTEND_IMAGE_ROOT.parent)
    private_directory(FRONTEND_IMAGE_ROOT)
    result = {}
    with closing(ArtifactRoot(FRONTEND_IMAGE_ROOT)) as seeds, seeds.exclusive() as root:
        for name in BASES:
            key = frontend_layout_path(name).name
            if exists_at(root, key):
                result[name] = _verify_layout(root, name)
                continue
            with (TemporaryDirectory(dir=FRONTEND_IMAGE_ROOT, prefix="stage-") as staging,
                  TemporaryDirectory(dir=FRONTEND_IMAGE_ROOT, prefix="export-") as scratch):
                layout = Path(staging)
                result[name] = _prepare_layout(Path(scratch), layout, name)
                publish_directory(root, layout.name, key)
    return result


def verify_frontend_layouts() -> dict:
    """Read and verify both immutable local layouts without Docker or Registry access."""
    try:
        with closing(ArtifactRoot(FRONTEND_IMAGE_ROOT)) as seeds:
            return {name: _verify_layout(seeds.fd, name) for name in BASES}
    except FileNotFoundError:
        raise ProbeFailure("frontend_base_seed_unavailable") from None
    except (ArtifactContentError, OSError, ValueError):
        raise ProbeFailure("frontend_base_seed_invalid") from None


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
