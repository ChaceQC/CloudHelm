"""Fixed source-only candidate used by the backend cache input method."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
from importlib import import_module
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

inputs = import_module("services.dev-runner.backend_build_inputs")
toolchain = import_module("services.dev-runner.toolchain")

FIXTURE_ID = "p1-backend-cache-fixture-b-v1"
SOURCE_REF = "fixed-notes-backend-cache-fixture-b-v1"
CONTEXT_NAME = "candidate-b"
ROUTE_PATH = "/api/cache-fixture"
EXPECTED_RESPONSE = {"source_marker": "cloudhelm-cache-fixture-b-v1"}
CHANGED_SOURCE = "app/main.py"


def builder_identity(probe) -> str:
    container_id = getattr(probe, "container_id", None)
    if not isinstance(container_id, str) or len(container_id) != 64:
        raise toolchain.ProbeFailure("backend_private_builder_identity_unavailable")
    return hashlib.sha256(container_id.encode("ascii")).hexdigest()


def publish_output(store, output: dict, *, expected_source_files: dict | None = None,
                   fixture_runtime_root: Path | None = None) -> tuple[object, dict]:
    receipt = store.publish(output["archive_path"], expected_archive_digest=output["archive_digest"])
    if (receipt.manifest.digest != output["exporter_manifest_digest"]
            or receipt.config.digest != output["exporter_config_digest"]
            or store.query(receipt.storage_id) != receipt):
        raise toolchain.ProbeFailure("backend_exporter_and_artifact_identity_mismatch")
    contents = image_files(store, receipt, output["runtime_checks"][0],
        expected_source_files=expected_source_files, fixture_runtime_root=fixture_runtime_root)
    return receipt, contents


def _layer_files(archive, receipt, expected: dict) -> dict[str, bytes]:
    actual = {}
    for layer in receipt.layers:
        if layer.media_type != "application/vnd.oci.image.layer.v1.tar+gzip":
            raise toolchain.ProbeFailure("backend_output_layer_not_gzip")
        updates, removals = {}, []
        with archive.extractfile("blobs/sha256/" + layer.digest[7:]) as blob:
            with tarfile.open(fileobj=blob, mode="r|gz") as files:
                for member in files:
                    name = member.name.removeprefix("./")
                    path = PurePosixPath(name)
                    if path.name.startswith(".wh."):
                        removed = str(path.parent) if path.name == ".wh..wh..opq" else str(path.with_name(path.name[4:]))
                        removals.extend(key for key in expected if key == removed or key.startswith(removed + "/"))
                    if name not in expected:
                        continue
                    if not member.isfile() or member.size > inputs.MAX_SOURCE_FILE_BYTES:
                        raise toolchain.ProbeFailure("backend_runtime_file_unsupported")
                    with files.extractfile(member) as source:
                        updates[name] = source.read(inputs.MAX_SOURCE_FILE_BYTES + 1)
        for name in removals:
            actual.pop(name, None)
        actual.update(updates)
    return actual


def image_files(store, receipt, runtime_checks: dict, *, expected_source_files: dict | None = None,
                fixture_runtime_root: Path | None = None) -> dict:
    if expected_source_files is not None and set(expected_source_files) != set(inputs.SOURCE_DIGESTS):
        raise toolchain.ProbeFailure("backend_expected_source_members_mismatch")
    expected = {"app/" + name: (inputs.digest(expected_source_files[name]) if expected_source_files is not None
                                  else inputs.SOURCE_DIGESTS[name]) for name in inputs.RUNTIME_SOURCE}
    expected["backend-result.json"] = None
    with store.open_archive(receipt.storage_id) as stream, tarfile.open(fileobj=stream, mode="r:") as archive:
        configuration = json.load(archive.extractfile("blobs/sha256/" + receipt.config.digest[7:]))["config"]
        if (configuration.get("WorkingDir") != "/app"
                or configuration.get("Cmd") != ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
                or configuration.get("Entrypoint")
                or any(value.startswith("DATABASE_URL=") for value in configuration.get("Env", []))):
            raise toolchain.ProbeFailure("backend_runtime_configuration_mismatch")
        actual = _layer_files(archive, receipt, expected)
    if set(actual) != set(expected) or json.loads(actual["backend-result.json"]) != runtime_checks:
        raise toolchain.ProbeFailure("backend_runtime_evidence_or_members_mismatch")
    digests = {name: inputs.digest(raw) for name, raw in actual.items() if name != "backend-result.json"}
    if digests != {name: value for name, value in expected.items() if value is not None}:
        raise toolchain.ProbeFailure("backend_runtime_source_content_mismatch")
    result = {"uvicorn_entrypoint_verified": True, "verified_runtime_source": digests,
        "runtime_checks_match_archive": True, "gzip_layers": len(receipt.layers), "attestations": False}
    if fixture_runtime_root is not None:
        source_from_oci = {name: actual["app/" + name] for name in inputs.RUNTIME_SOURCE}
        result["cache_fixture_runtime_check"] = invoke_route(source_from_oci, fixture_runtime_root)
    return result


def _newline(raw: bytes) -> bytes:
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\r\n" in raw and b"\n" in without_crlf:
        raise toolchain.ProbeFailure("backend_cache_fixture_mixed_line_endings")
    return b"\r\n" if b"\r\n" in raw else b"\n"


def create_candidate(source_files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Derive the sole admitted B candidate from the exact fixed A source."""
    inputs.verify_source(source_files)
    original = source_files[CHANGED_SOURCE]
    if ROUTE_PATH.encode("ascii") in original:
        raise toolchain.ProbeFailure("backend_cache_fixture_route_already_present")
    newline = _newline(original)
    anchor = b"    return application"
    if original.count(anchor) != 1:
        raise toolchain.ProbeFailure("backend_cache_fixture_anchor_mismatch")
    lines = (
        b'    @application.get("/api/cache-fixture")',
        b"    def cache_fixture() -> dict[str, str]:",
        b'        return {"source_marker": "cloudhelm-cache-fixture-b-v1"}',
        b"",
    )
    insertion = newline.join(lines)
    candidate = dict(source_files)
    candidate[CHANGED_SOURCE] = original.replace(anchor, insertion + anchor, 1)
    return candidate


def verify_candidate(base_source: Mapping[str, bytes], candidate: Mapping[str, bytes]) -> dict:
    """Accept exactly the generated one-file B variant; all other drift fails."""
    expected = create_candidate(base_source)
    if dict(candidate) != expected:
        raise toolchain.ProbeFailure("backend_cache_fixture_candidate_mismatch")
    return inputs._source_receipt(expected)


def prepare_context(directory: Path, base_source: Mapping[str, bytes], candidate: Mapping[str, bytes], *,
                    distributions: Mapping[str, str]) -> dict:
    """Write B only after the one-file fixture verifier accepts its exact bytes."""
    source = dict(candidate)
    receipt = verify_candidate(base_source, source)
    return inputs._write_context(directory, source, receipt, source_ref=SOURCE_REF,
        distributions=distributions, context_name=CONTEXT_NAME, seal_bundle=False)


def summary(base_source: Mapping[str, bytes], source_files: Mapping[str, bytes]) -> dict:
    receipt = verify_candidate(base_source, source_files)
    return {
        "fixture_id": FIXTURE_ID,
        "source_ref": SOURCE_REF,
        "context_name": CONTEXT_NAME,
        "source_manifest_digest": receipt["manifest_digest"],
        "file_count": receipt["file_count"],
        "changed_source": {
            "path": CHANGED_SOURCE,
            "sha256": receipt["files"][CHANGED_SOURCE]["sha256"],
            "bytes": receipt["files"][CHANGED_SOURCE]["bytes"],
        },
        "expected_route_path": ROUTE_PATH,
        "expected_response": EXPECTED_RESPONSE,
    }


def invoke_route(source_files: Mapping[str, bytes], work_root: Path, *,
                 source_origin: str = "verified_bytes_extracted_from_b_oci_layers") -> dict:
    """Import a verified B source view in isolation and call its registered route."""
    if (set(source_files) != set(inputs.RUNTIME_SOURCE)
            or any(type(raw) is not bytes or len(raw) > inputs.MAX_SOURCE_FILE_BYTES
                   for raw in source_files.values())):
        raise toolchain.ProbeFailure("backend_cache_fixture_runtime_source_invalid")
    if source_origin not in {"verified_bytes_extracted_from_b_oci_layers", "fixed_fixture_candidate_prebuild"}:
        raise toolchain.ProbeFailure("backend_cache_fixture_runtime_source_origin_invalid")
    with tempfile.TemporaryDirectory(prefix="backend-cache-fixture-", dir=work_root) as temporary:
        root = Path(temporary)
        for name, raw in source_files.items():
            target = root / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
            target.chmod(0o400)
        program = (
            "import importlib,json,sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "module=importlib.import_module('app.main')\n"
            f"matches=[route for route in module.app.routes if getattr(route,'path',None)=={ROUTE_PATH!r} "
            "and 'GET' in getattr(route,'methods',set())]\n"
            "if len(matches)!=1: raise SystemExit(31)\n"
            "value=matches[0].endpoint()\n"
            f"expected={json.dumps(EXPECTED_RESPONSE, sort_keys=True, separators=(',', ':'))}\n"
            "if value!=expected: raise SystemExit(32)\n"
            "print(json.dumps({'route_path':matches[0].path,'response':value,'route_endpoint_called':True},"
            "sort_keys=True,separators=(',', ':')))\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", program, str(root)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except (OSError, subprocess.TimeoutExpired):
            raise toolchain.ProbeFailure("backend_cache_fixture_runtime_check_unavailable") from None
        if completed.returncode or len(completed.stdout) > 4096:
            raise toolchain.ProbeFailure("backend_cache_fixture_runtime_check_failed")
        try:
            observation = json.loads(completed.stdout)
        except ValueError:
            raise toolchain.ProbeFailure("backend_cache_fixture_runtime_check_output_invalid") from None
        expected = {"route_path": ROUTE_PATH, "response": EXPECTED_RESPONSE, "route_endpoint_called": True}
        if observation != expected:
            raise toolchain.ProbeFailure("backend_cache_fixture_runtime_check_mismatch")
        return {
            "route_path": ROUTE_PATH,
            "expected_response": EXPECTED_RESPONSE,
            "observed_response": observation["response"],
            "route_endpoint_called": True,
            "source_origin": source_origin,
        }
