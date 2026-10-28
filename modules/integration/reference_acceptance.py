"""Collect the fixed independent reference HTTP method from the trusted checkout."""

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from modules.projects.reference_assets import (
    ACCEPTANCE_ROOT, ReferenceAssetError, ReferenceAssets, _digest, _read_public_file,
    load_reference_assets,
)
from modules.workspaces.reference_seed import _seed_root


_ENTRY = ACCEPTANCE_ROOT + "verify_http.py"
_OUTPUT_LIMIT = 65536
_TIMEOUT_SECONDS = 300
_PHASE_CHECKS = {
    "seed": frozenset({
        "REF-04.seed_ready_200",
        "REF-04.seed_clear_exact_reserved_marker",
        "REF-04.seed_create_fixed_persistence_marker",
    }),
    "verify-persisted": frozenset({
        "REF-04.persisted_marker_present_after_api_restart",
        "REF-04.persisted_marker_cleanup_exact",
    }),
    "not-ready": frozenset({
        "REF-06.health_200_while_dependency_unavailable",
        "REF-06.ready_503_while_dependency_unavailable",
    }),
}


@dataclass(frozen=True, slots=True)
class CollectedPhase:
    phase: str
    assets: ReferenceAssets
    passed_check_ids: tuple[str, ...]
    failed_check_ids: tuple[str, ...]
    integrity_errors: tuple[str, ...]
    exit_code: int | None
    output_digest: str
    observed_at: datetime


def collect_reference_phase(repository, *, base_url: str, phase: str) -> CollectedPhase:
    """Run one phase against a disposable local instance; caller binds setup evidence.

    An empty output digest means no complete, bounded output was captured. The caller
    must provide a trusted checkout and must not treat a single phase as full acceptance.
    """
    if not isinstance(phase, str) or phase not in {"baseline", *_PHASE_CHECKS}:
        raise ValueError("reference_phase_invalid")
    try:
        if not isinstance(base_url, str):
            raise ValueError
        parsed = urlsplit(base_url)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None or "@" in parsed.netloc
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or not port):
            raise ValueError
        origin = f"http://{'[::1]' if host == '::1' else host}:{port}"
    except ValueError:
        raise ValueError("reference_base_url_invalid") from None

    try:
        assets = load_reference_assets(repository)
    except (ValueError, TypeError, OSError):
        raise ReferenceAssetError("reference_assets_unavailable") from None
    extra_checks = set().union(*_PHASE_CHECKS.values())
    required = set(assets.required_check_ids)
    if not extra_checks <= required:
        raise ReferenceAssetError("reference_check_identity_invalid")
    expected = required - extra_checks if phase == "baseline" else _PHASE_CHECKS[phase]

    errors: list[str] = []
    passed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    exit_code = None
    output_digest = ""
    output = None
    try:
        with _seed_root(repository) as root:
            entry = _read_public_file(root, _ENTRY)
        if _digest(entry) != dict(assets.file_digests)[_ENTRY]:
            raise ReferenceAssetError("reference_entry_digest_mismatch")
    except (ValueError, TypeError, OSError, KeyError):
        errors.append("reference_assets_before_execution_invalid")
    else:
        try:
            # The child receives only fixed script bytes, a local origin, and a private cwd.
            with tempfile.TemporaryDirectory(prefix="cloudhelm-reference-", dir="/tmp") as directory:
                with tempfile.TemporaryFile(dir=directory) as stdout:
                    try:
                        result = subprocess.run(
                            [sys.executable, "-I", "-S", "-X", "utf8", "-", "--base-url", origin,
                             "--phase", phase],
                            input=entry, stdout=stdout, stderr=subprocess.DEVNULL, cwd=directory,
                            env={"LANG": "C.UTF-8"}, timeout=_TIMEOUT_SECONDS, check=False,
                        )
                        exit_code = result.returncode
                    except subprocess.TimeoutExpired:
                        errors.append("reference_execution_timeout")
                    if exit_code is not None:
                        stdout.seek(0)
                        output = stdout.read(_OUTPUT_LIMIT + 1)
                        if len(output) > _OUTPUT_LIMIT:
                            errors.append("reference_output_too_large")
                            output = None
                        else:
                            output_digest = _digest(output)
        except (OSError, subprocess.SubprocessError):
            errors.append("reference_execution_unavailable")

    try:
        if load_reference_assets(repository) != assets:
            errors.append("reference_assets_after_execution_changed")
    except (ValueError, TypeError, OSError):
        errors.append("reference_assets_after_execution_invalid")

    if output is not None:
        try:
            data = json.loads(output.decode("utf-8"))
            keys = {"method_revision", "requirement_revision", "phase", "case_counts", "passed",
                    "passed_cases", "failed_cases"}
            if not isinstance(data, dict) or set(data) != keys:
                raise ValueError
            passed_cases, failed_cases = data["passed_cases"], data["failed_cases"]
            if (not isinstance(passed_cases, list) or not isinstance(failed_cases, list)
                    or any(not isinstance(name, str) or len(name) > 160 for name in passed_cases + failed_cases)):
                raise ValueError
            names = passed_cases + failed_cases
            passed = tuple(sorted(set(passed_cases) & expected))
            failed = tuple(sorted(set(failed_cases) & expected))
            if (data["method_revision"] != assets.method_revision
                    or data["requirement_revision"] != assets.requirement_revision or data["phase"] != phase):
                errors.append("reference_output_binding_mismatch")
            counts = data["case_counts"]
            if (not isinstance(counts, dict) or set(counts) != {"total", "passed", "failed"}
                    or any(type(value) is not int for value in counts.values())
                    or counts != {"total": len(names), "passed": len(passed_cases), "failed": len(failed_cases)}):
                errors.append("reference_case_counts_mismatch")
            if len(names) != len(set(names)):
                errors.append("reference_duplicate_check_id")
            if set(names) != expected:
                errors.append("reference_check_set_incomplete")
            if type(data["passed"]) is not bool or data["passed"] != (not failed_cases):
                errors.append("reference_passed_flag_mismatch")
            if exit_code != (1 if failed_cases else 0):
                errors.append("reference_exit_code_mismatch")
        except (ValueError, UnicodeError):
            errors.append("reference_output_invalid")

    return CollectedPhase(
        phase=phase, assets=assets, passed_check_ids=passed, failed_check_ids=failed,
        integrity_errors=tuple(errors), exit_code=exit_code, output_digest=output_digest,
        observed_at=datetime.now(UTC),
    )
