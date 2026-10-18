"""Offline backend OCI builds and explicit in-builder cache observations."""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .backend_build_boundary import BackendBuildBoundary, OUTPUT_BYTES
from .backend_build_inputs import digest
from .offline_image_runtime import SOCKET
from .python_dependencies import verify_derived_inputs
from .toolchain import ProbeFailure, safe_diagnostic


def _facts(output: str, prefix: str) -> list:
    facts = []
    for line in output.splitlines():
        if prefix in line:
            try:
                facts.append(json.loads(line.split(prefix, 1)[1]))
            except ValueError:
                pass  # Progress headings repeat the literal Dockerfile command.
    if len(facts) > 1:
        raise ProbeFailure("backend_build_fact_not_unique")
    return facts


def _cached_runtime_check(output: str) -> bool:
    identifiers = set(re.findall(r"#(\d+) \[runtime \d+/\d+\] RUN .*CLOUDHELM_BACKEND_RUNTIME=", output))
    return any(re.search(r"(?m)^#" + number + r" CACHED\s*$", output) for number in identifiers)


class BackendBuildRuntime(BackendBuildBoundary):
    def _arguments(self, manifest_digest: str, *, context_name: str | None = None) -> list[str]:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest):
            raise ProbeFailure("backend_base_manifest_invalid")
        context = "/probe/context"
        if context_name is not None:
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", context_name):
                raise ProbeFailure("backend_source_context_name_invalid")
            context += "/" + context_name
        return ["buildctl", "--addr", SOCKET, "build", "--frontend=dockerfile.v0",
            "--local=context=" + context, "--local=dockerfile=" + context,
            "--local=pythonseed=/probe/python-seed", "--opt=context:pythonseed=local:pythonseed",
            "--oci-layout=python=/probe/base", "--opt=context:pythonbase=oci-layout://python@" + manifest_digest,
            "--opt=platform=linux/amd64", "--progress=plain"]

    def _run_build(self, arguments: list[str]) -> str:
        with ThreadPoolExecutor(max_workers=1) as executor:
            build = executor.submit(self.execute, *arguments, ceiling=240, required=False)
            while not build.done():
                self._observe_processes()
                time.sleep(0.25)
            result = build.result()
        output = result.stdout + result.stderr
        if result.returncode:
            lines = [line for line in output.splitlines() if (
                len(line) < 1000 and re.match(r"#\d+\s+[0-9]+(?:\.[0-9]+)?\s", line))
                or (len(line) < 500 and re.match(r"#\d+ ERROR:", line))]
            raise ProbeFailure("backend_offline_build_failed", detail=safe_diagnostic("\n".join(lines)))
        self._observe_processes()
        return output

    def build(self, base_manifest_digest: str, *, input_key: str, collect: bool = True,
              context_name: str | None = None) -> dict:
        """Inputs/context are fixed by the admitted internal caller before create()."""
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", input_key):
            raise ProbeFailure("backend_build_input_key_invalid")
        arguments = self._arguments(base_manifest_digest, context_name=context_name) + ["--opt=target=runtime",
            "--opt=build-arg:CLOUDHELM_BUILD_INPUT_KEY=" + input_key,
            "--output=type=oci,dest=/probe/output/image.oci.tar,oci-mediatypes=true,compression=gzip,force-compression=true",
            "--metadata-file=/probe/output/build-metadata.json"]
        output = self._run_build(arguments)
        checks = _facts(output, "CLOUDHELM_BACKEND_RUNTIME=")
        cached = _cached_runtime_check(output)
        if bool(checks) == cached:
            raise ProbeFailure("backend_runtime_check_execution_or_cache_not_observed")
        if checks and (checks[0].get("build_input_key") != input_key
                       or checks[0].get("python") != "3.12.13"
                       or checks[0].get("migration_head") != "0002_add_updated_at_index"
                       or any(checks[0].get(name) is not True for name in (
                           "backend_imported", "database_unconfigured", "no_ipv4_routes", "control_paths_absent"))):
            raise ProbeFailure("backend_runtime_check_mismatch")
        metadata = json.loads(self.execute("cat", "/probe/output/build-metadata.json").stdout)
        archive_digest = "sha256:" + self.execute("sha256sum", "/probe/output/image.oci.tar").stdout.split()[0]
        size = int(self.execute("stat", "-c", "%s", "/probe/output/image.oci.tar").stdout)
        if not 0 < size <= OUTPUT_BYTES:
            raise ProbeFailure("backend_output_archive_size_invalid")
        result = {"archive_digest": archive_digest, "archive_bytes": size,
            "exporter_manifest_digest": metadata.get("containerimage.digest"),
            "exporter_config_digest": metadata.get("containerimage.config.digest"),
            "input_key": input_key, "runtime_check_cached": cached, "runtime_checks": checks,
            "build_cache_policy": "private_builder_per_operation", "runtime_loaded": False, "http_checked": False}
        if collect:
            target = self.directory / "image.oci.tar"
            self._collect_archive(target)
            if target.stat().st_size != size:
                raise ProbeFailure("backend_collected_archive_size_mismatch")
            with target.open("rb") as stream:
                actual_digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            if actual_digest != archive_digest:
                raise ProbeFailure("backend_collected_archive_digest_mismatch")
            result["archive_path"] = str(target)
        return result

    def dependency_evidence(self, base_manifest_digest: str, distributions: dict, *, source_files=None,
                            context_name: str | None = None) -> dict:
        output = self._run_build(self._arguments(base_manifest_digest, context_name=context_name)
            + ["--opt=target=verification",
            "--output=type=local,dest=/probe/output/verification"])
        raw = self.execute("cat", "/probe/output/verification/dependency-result.json").stdout
        if len(raw) > 65536:
            raise ProbeFailure("backend_dependency_evidence_bound_exceeded")
        checks = json.loads(raw)
        expected = {"python": "3.12.13", "distributions": distributions, "psycopg_impl": "binary",
            "cache_bytes": 256 * 1024**2, "temp_bytes": 64 * 1024**2,
            "wheelhouse_readonly": True, "no_ipv4_routes": True, "control_paths_absent": True}
        if checks != expected:
            raise ProbeFailure("backend_dependency_evidence_mismatch")
        project = self.execute("cat", "/probe/output/verification/derived-pyproject.toml").stdout.encode("utf-8")
        lock = self.execute("cat", "/probe/output/verification/derived-uv.lock").stdout.encode("utf-8")
        derived = verify_derived_inputs(project, lock, distributions, source_files)
        retained = self.directory / "derived-inputs"
        retained.mkdir(mode=0o700)
        for name, raw in (("pyproject.toml", project), ("uv.lock", lock)):
            descriptor = os.open(retained / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        retained.chmod(0o500)
        return {"checks": checks, "derived_inputs": derived, "derived_project_digest": digest(project),
                "derived_lock_digest": digest(lock), "private_install_cache_removed": True,
                "cache_observed": " CACHED" in output}

    def stopped_resources(self) -> dict:
        stopped = self.stop_and_remove()
        return {"confirmation": stopped.model_dump(mode="json"),
            "process_resources_released": stopped.status == "verified",
            "memory_peak_bytes": getattr(self, "memory_peak", None),
            "private_builder_and_install_cache_removed": stopped.status == "verified"}


def build_backend(client, operation_id, directory, seed_root, expected_seed_manifest_digest, *,
                  source_files, source_ref, content_store) -> dict:
    """Synchronous trusted-runner entry point; never reads implicit worktree inputs."""
    from .backend_build_service import build_backend as execute

    return execute(client, operation_id, directory, seed_root, expected_seed_manifest_digest,
                   source_files=source_files, source_ref=source_ref, content_store=content_store)
