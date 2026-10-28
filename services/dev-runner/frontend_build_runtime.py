"""Run the one fixed frontend offline build and collect its bounded OCI output."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from modules.artifacts.errors import ArtifactContentError
from packages.contracts.p1.npm_cache import NPM_VERSION, NpmDownloadSpec

from .frontend_build_boundary import FrontendBuildBoundary, OUTPUT_BYTES
from .frontend_build_inputs import VerifiedFrontendSource, prepare_context
from .frontend_images import prepare_frontend_layouts, verify_frontend_image
from .npm_downloads import NpmDownloadError, NpmDownloadStore
from .buildkit_container import SOCKET
from .toolchain import ProbeFailure, ensure_toolchain, private_directory, safe_diagnostic


def _sentinel(output: str, prefix: str):
    values = []
    for line in output.splitlines():
        if prefix in line:
            try:
                values.append(json.loads(line.split(prefix, 1)[1]))
            except ValueError:
                pass  # The progress heading contains the literal command text.
    if len(values) != 1:
        raise ProbeFailure("frontend_build_fact_not_unique")
    return values[0]


class FrontendBuildRuntime(FrontendBuildBoundary):
    def build(self, bases: dict) -> dict:
        arguments = ["buildctl", "--addr", SOCKET, "build", "--frontend=dockerfile.v0",
            "--local=context=/probe/context", "--local=dockerfile=/probe/context",
            "--local=npmseed=/probe/npm-seed", "--opt=context:npmseed=local:npmseed",
            "--opt=platform=linux/amd64", "--opt=target=runtime", "--no-cache", "--progress=plain",
            "--output=type=oci,dest=/probe/output/image.oci.tar,oci-mediatypes=true,compression=gzip,force-compression=true",
            "--metadata-file=/probe/output/build-metadata.json"]
        for name in ("node", "nginx"):
            arguments += [f"--oci-layout={name}=/probe/{name}",
                f"--opt=context:{name}base=oci-layout://{name}@" + bases[name]["manifest"]["digest"]]
        with ThreadPoolExecutor(max_workers=1) as executor:
            build = executor.submit(self.execute, *arguments, ceiling=300, required=False)
            while not build.done():
                self._observe_processes()
                time.sleep(0.25)
            result = build.result()
        output = result.stdout + result.stderr
        if result.returncode:
            lines = [line for line in output.splitlines() if len(line) < 1500 and re.search(
                r"error|permission denied|read-only file system|no space left|ERR!", line, re.IGNORECASE)]
            raise ProbeFailure("frontend_offline_build_failed", detail=safe_diagnostic("\n".join(lines)))
        versions = _sentinel(output, "CLOUDHELM_FRONTEND_TOOLCHAIN=")
        if (not isinstance(versions, dict)
                or set(versions) != {"node", "npm", "seed_readonly", "no_ipv4_routes", "control_paths_absent"}
                or versions["node"] != "v22.23.2" or versions["npm"] != NPM_VERSION
                or any(versions[name] is not True for name in (
                    "seed_readonly", "no_ipv4_routes", "control_paths_absent"))):
            raise ProbeFailure("frontend_actual_toolchain_or_boundary_mismatch")
        dist = _sentinel(output, "CLOUDHELM_FRONTEND_DIST=")
        if not isinstance(dist, list) or not 3 <= len(dist) <= 64:
            raise ProbeFailure("frontend_dist_manifest_invalid")
        for entry in dist:
            if (not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}
                    or not isinstance(entry["path"], str) or not isinstance(entry["sha256"], str)
                    or not re.fullmatch(r"(?:assets/[A-Za-z0-9_.-]+|index\.html)", entry["path"])
                    or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= 2 * 1024**2
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["sha256"])):
                raise ProbeFailure("frontend_dist_file_unsupported")
        paths = [entry["path"] for entry in dist]
        if (paths != sorted(set(paths)) or "index.html" not in paths
                or sum(entry["bytes"] for entry in dist) > 8 * 1024**2):
            raise ProbeFailure("frontend_dist_manifest_not_unique_or_bounded")
        metadata = json.loads(self.execute("cat", "/probe/output/build-metadata.json").stdout)
        digest = self.execute("sha256sum", "/probe/output/image.oci.tar").stdout.split()[0]
        size = int(self.execute("stat", "-c", "%s", "/probe/output/image.oci.tar").stdout)
        if not 0 < size <= OUTPUT_BYTES:
            raise ProbeFailure("frontend_output_archive_size_invalid")
        target = self.directory / "image.oci.tar"
        self._collect_archive(target)
        if target.stat().st_size != size:
            raise ProbeFailure("frontend_collected_archive_size_mismatch")
        self._observe_processes()
        return {"archive_path": str(target), "archive_digest": "sha256:" + digest, "archive_bytes": size,
            "exporter_manifest_digest": metadata.get("containerimage.digest"),
            "exporter_config_digest": metadata.get("containerimage.config.digest"),
            "actual_toolchain": versions, "dist": dist, "build_cache_policy": "no-cache",
            "npm_cacache": "private_tmpfs_from_verified_tgz", "lifecycle_scripts": "ignored",
            "runtime_loaded": False, "http_checked": False}

    def stopped_resources(self) -> dict:
        stopped = self.stop_and_remove()
        return {"confirmation": stopped.model_dump(mode="json"),
            "process_resources_released": stopped.status == "verified",
            "memory_peak_bytes": getattr(self, "memory_peak", None),
            "private_builder_and_npm_cache_removed": stopped.status == "verified"}


def build_frontend(client, operation_id: str, directory: Path, seed_root: Path,
                   expected_seed_manifest_digest: str, *, source_inputs: dict[str, bytes] | VerifiedFrontendSource,
                   expected_source_manifest_digest: str, content_store,
                   seed_spec: NpmDownloadSpec) -> dict:
    """Run a registered fixed-reference build; the caller holds authorization and admission.

    Inputs are immutable candidate bytes, never an implicit read of the worktree.
    Returned facts include failures and physical stop evidence; they are not a BuildRun state.
    """
    result = {"all_required_verified": False, "failures": []}
    probe = None
    try:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,95}", operation_id):
            raise ProbeFailure("frontend_operation_identity_invalid")
        if any(not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
               for value in (expected_seed_manifest_digest, expected_source_manifest_digest)):
            raise ProbeFailure("frontend_expected_input_digests_required")
        private_directory(directory)
        source = (source_inputs if isinstance(source_inputs, VerifiedFrontendSource)
                  else VerifiedFrontendSource.from_inputs(source_inputs))
        if source.receipt["manifest_digest"] != expected_source_manifest_digest:
            raise ProbeFailure("frontend_source_manifest_digest_mismatch")
        candidate = source.inputs
        result["source"] = prepare_context(directory, source)
        with NpmDownloadStore(seed_root) as seeds:
            seed = seeds.verify(seed_spec, expected_manifest_digest=expected_seed_manifest_digest)
        result["seed"] = seed.model_dump(mode="json")
        result["toolchain"] = ensure_toolchain(client)
        result["bases"] = prepare_frontend_layouts(client, directory)
        probe = FrontendBuildRuntime(client, operation_id, directory,
            result["toolchain"]["reference"], time.monotonic(), seed_root / seed.manifest.cache_id)
        probe.create()
        result["limits"] = probe.observe_boundary()
        result["output"] = probe.build(result["bases"])
        receipt = content_store.publish(result["output"]["archive_path"],
            expected_archive_digest=result["output"]["archive_digest"])
        result["content_receipt"] = receipt.model_dump(mode="json")
        if (receipt.manifest.digest != result["output"]["exporter_manifest_digest"]
                or receipt.config.digest != result["output"]["exporter_config_digest"]
                or content_store.query(receipt.storage_id) != receipt):
            raise ProbeFailure("frontend_exporter_and_artifact_identity_mismatch")
        result["runtime_image_contents"] = verify_frontend_image(
            content_store, receipt, result["output"]["dist"], candidate["nginx.conf"])
        result["artifact"] = receipt.model_dump(mode="json")
        with NpmDownloadStore(seed_root) as seeds:
            if seeds.verify(seed_spec, expected_manifest_digest=seed.manifest_digest) != seed:
                raise ProbeFailure("frontend_seed_changed_after_build")
    except ProbeFailure as failure:
        result["failures"].append({"category": failure.category, "diagnostic": failure.diagnostic,
                                   "detail": failure.detail})
    except (ArtifactContentError, NpmDownloadError) as failure:
        result["failures"].append({"category": str(failure)})
    except Exception as failure:
        result["failures"].append({"category": "frontend_exception_" + type(failure).__name__})
    finally:
        if probe is not None and probe.container_id is not None:
            try:
                result["stop"] = probe.stopped_resources()
            except ProbeFailure as failure:
                result["failures"].append({"category": failure.category, "detail": failure.detail})
            except Exception as failure:
                result["failures"].append({"category": "frontend_stop_exception_" + type(failure).__name__})
        if probe is not None:
            try:
                (directory / "image.oci.tar").unlink(missing_ok=True)
                result["collected_archive_removed"] = True
            except OSError:
                result["failures"].append({"category": "frontend_archive_cleanup_failed"})
        result["all_required_verified"] = (not result["failures"] and "artifact" in result
            and result.get("stop", {}).get("process_resources_released") is True)
    return result
