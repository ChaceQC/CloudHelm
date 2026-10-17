"""Trusted candidate-to-OCI backend build, without development cache probes."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tarfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from modules.artifacts.errors import ArtifactContentError

from . import backend_build_inputs as inputs
from .offline_images import prepare_python_layout
from .python_dependencies import PythonDependencyInput, verify_admitted_seed
from .toolchain import ProbeFailure, ensure_toolchain, private_directory


def _layer_files(archive, receipt, expected: dict) -> dict[str, bytes]:
    """Read the final fixed source view without extracting the image to disk."""
    actual = {}
    for layer in receipt.layers:
        if layer.media_type != "application/vnd.oci.image.layer.v1.tar+gzip":
            raise ProbeFailure("backend_output_layer_not_gzip")
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
                        raise ProbeFailure("backend_runtime_file_unsupported")
                    with files.extractfile(member) as source:
                        updates[name] = source.read(inputs.MAX_SOURCE_FILE_BYTES + 1)
        for name in removals:
            actual.pop(name, None)
        actual.update(updates)
    return actual


def _verify_image(store, receipt, runtime_checks: dict) -> dict:
    expected = {"app/" + name: inputs.SOURCE_DIGESTS[name] for name in inputs.RUNTIME_SOURCE}
    expected["backend-result.json"] = None
    with store.open_archive(receipt.storage_id) as stream, tarfile.open(fileobj=stream, mode="r:") as archive:
        configuration = json.load(archive.extractfile("blobs/sha256/" + receipt.config.digest[7:]))["config"]
        if (configuration.get("WorkingDir") != "/app"
                or configuration.get("Cmd") != ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
                or configuration.get("Entrypoint")
                or any(value.startswith("DATABASE_URL=") for value in configuration.get("Env", []))):
            raise ProbeFailure("backend_runtime_configuration_mismatch")
        actual = _layer_files(archive, receipt, expected)
    if set(actual) != set(expected) or json.loads(actual["backend-result.json"]) != runtime_checks:
        raise ProbeFailure("backend_runtime_evidence_or_members_mismatch")
    digests = {name: inputs.digest(raw) for name, raw in actual.items() if name != "backend-result.json"}
    if digests != {name: value for name, value in expected.items() if value is not None}:
        raise ProbeFailure("backend_runtime_source_content_mismatch")
    return {"uvicorn_entrypoint_verified": True, "verified_runtime_source": digests,
        "runtime_checks_match_archive": True, "gzip_layers": len(receipt.layers), "attestations": False}


def _cleanup(directory: Path, *, remove_layout: bool) -> dict:
    """Remove only this invocation's temporary public base and collected exports."""
    removed_bytes = 0
    device = directory.stat().st_dev
    layout = directory / "base-layout"
    if remove_layout and (layout.exists() or layout.is_symlink()):
        entries = [layout, *layout.rglob("*")]
        for entry in entries:
            state = entry.lstat()
            if (state.st_uid != os.getuid() or state.st_dev != device
                    or not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode))):
                raise ProbeFailure("backend_cleanup_member_rejected")
            if stat.S_ISREG(state.st_mode):
                removed_bytes += state.st_size
        for entry in entries:
            if entry.is_dir():
                entry.chmod(0o700)
        shutil.rmtree(layout)
    for name in ("image.oci.tar", "source-export.tar"):
        target = directory / name
        try:
            state = target.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid() or state.st_dev != device:
            raise ProbeFailure("backend_cleanup_export_rejected")
        target.unlink()
    return {"source_layout_removed": not layout.exists(),
        "source_layout_removed_logical_bytes": removed_bytes,
        "collected_archive_removed": not (directory / "image.oci.tar").exists(),
        "source_export_removed": not (directory / "source-export.tar").exists()}


def build_backend(client, operation_id: str, directory: Path, seed_root: Path,
                  expected_seed_manifest_digest: str, *, source_files: Mapping[str, bytes],
                  source_ref: str, content_store) -> dict:
    """The composition root supplies immutable candidate bytes and holds admission.

    Physical observations and stop evidence are returned to the owner of BuildRun;
    this function does not manufacture business completion or HTTP acceptance.
    """
    from .backend_build_runtime import BackendBuildRuntime

    result = {"all_required_verified": False, "failures": []}
    probe = None
    try:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,95}", operation_id):
            raise ProbeFailure("backend_operation_identity_invalid")
        if (not isinstance(expected_seed_manifest_digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_seed_manifest_digest)):
            raise ProbeFailure("backend_expected_seed_digest_required")
        private_directory(directory)
        candidate = dict(source_files)
        dependency_input = PythonDependencyInput()
        seed = verify_admitted_seed(seed_root, dependency_input, source_files=candidate)
        if seed["manifest_digest"] != expected_seed_manifest_digest:
            raise ProbeFailure("backend_seed_manifest_mismatch")
        result["seed"] = seed
        result["source"] = inputs.prepare_context(directory, candidate, source_ref=source_ref,
                                                   distributions=seed["distributions"])
        result["toolchain"] = ensure_toolchain(client)
        result["base"] = prepare_python_layout(client, directory)
        manifest = result["base"]["manifest"]["digest"]
        input_key = inputs.build_input_key(result["source"], seed, manifest)
        result["inputs"] = {"source_ref": source_ref,
            "source_manifest_digest": result["source"]["manifest_digest"],
            "seed_manifest_digest": seed["manifest_digest"], "base_manifest_digest": manifest,
            "recipe_digest": result["source"]["recipe_digest"], "build_input_key": input_key}
        probe = BackendBuildRuntime(client, operation_id, directory,
            result["toolchain"]["reference"], time.monotonic(), seed_root)
        probe.create()
        result["limits"] = probe.observe_boundary()
        result["output"] = probe.build(manifest, input_key=input_key)
        output = result["output"]
        if output["runtime_check_cached"] or len(output["runtime_checks"]) != 1:
            raise ProbeFailure("backend_first_build_execution_not_observed")
        receipt = content_store.publish(output["archive_path"], expected_archive_digest=output["archive_digest"])
        if (receipt.manifest.digest != output["exporter_manifest_digest"]
                or receipt.config.digest != output["exporter_config_digest"]
                or content_store.query(receipt.storage_id) != receipt):
            raise ProbeFailure("backend_exporter_and_artifact_identity_mismatch")
        result["runtime_image_contents"] = _verify_image(content_store, receipt, output["runtime_checks"][0])
        result["artifact"] = receipt.model_dump(mode="json")
        result["dependencies"] = probe.dependency_evidence(manifest, seed["distributions"], source_files=candidate)
        if verify_admitted_seed(seed_root, dependency_input, source_files=candidate) != seed:
            raise ProbeFailure("backend_seed_changed_after_build")
        inputs.verify_source(candidate)
    except ProbeFailure as failure:
        result["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic,
                                   "detail": failure.detail})
    except ArtifactContentError as failure:
        result["failures"].append({"category": str(failure)})
    except Exception as failure:
        result["failures"].append({"category": "backend_exception_" + type(failure).__name__})
    finally:
        if probe is not None and probe.container_id is not None:
            try:
                result["stop"] = probe.stopped_resources()
            except ProbeFailure as failure:
                result["failures"].append({"category": failure.category, "detail": failure.detail})
            except Exception as failure:
                result["failures"].append({"category": "backend_stop_exception_" + type(failure).__name__})
        try:
            stopped = result.get("stop", {}).get("process_resources_released") is True
            result["cleanup"] = _cleanup(directory, remove_layout=probe is None or probe.container_id is None or stopped)
        except ProbeFailure as failure:
            result["failures"].append({"category": failure.category, "detail": failure.detail})
        except Exception as failure:
            result["failures"].append({"category": "backend_cleanup_exception_" + type(failure).__name__})
        result["all_required_verified"] = (not result["failures"] and "artifact" in result
            and "dependencies" in result and result.get("stop", {}).get("process_resources_released") is True
            and all(result.get("cleanup", {}).get(name) is True for name in (
                "source_layout_removed", "collected_archive_removed", "source_export_removed")))
    return result
