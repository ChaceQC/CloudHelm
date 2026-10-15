"""Run the fixed P1.2 rootless capability probe and retain bounded JSON evidence."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, input_set_digest
from packages.contracts.p1.runner_contracts import (
    CAPABILITY_NAMES, CapabilityEvidence, RunnerCapabilityReport, RunnerOperationSpec, operation_digest,
)

policy = import_module("services.dev-runner.policy")
toolchain = import_module("services.dev-runner.toolchain")
capabilities = import_module("services.dev-runner.capabilities")
ROOT = Path(__file__).resolve().parents[2]
METHOD_FILES = (
    "packages/contracts/p1/runner_contracts.py", "services/dev-runner/policy.py",
    "services/dev-runner/toolchain.py", "services/dev-runner/capabilities.py", "scripts/p1/probe_runner.py",
)


def reference(kind: str, identity: str, digest: str) -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=identity, revision="r1",
                          authority="controlled-wsl-maintenance", digest=digest, digest_algorithm="sha256")


def registered_spec(operation_id: str, started: datetime) -> tuple[RunnerOperationSpec, InputSet]:
    method_refs = tuple(reference("method", name.replace("/", ":"), toolchain.file_digest(ROOT / name))
                        for name in METHOD_FILES)
    tool = reference("artifact", toolchain.TOOLCHAIN_TAG, toolchain.TOOLCHAIN_DIGEST)
    policy_ref = reference("policy", "runner-probe-policy", toolchain.file_digest(ROOT / METHOD_FILES[1]))
    envelope = reference("policy", "runner-probe-static-envelope", policy_ref.digest)
    refs = method_refs + (tool, policy_ref, envelope)
    inputs = InputSet(input_set_id=operation_id + "-input", references=refs, set_digest=input_set_digest(refs))
    input_ref = reference("input_set", inputs.input_set_id, inputs.set_digest)
    partial = RunnerOperationSpec.model_construct(
        operation_id=operation_id, request_digest="sha256:" + "0" * 64,
        executor_instance_id="ubuntu-24-04-wsl-maintenance", input_set_ref=input_ref,
        toolchain_ref=tool, policy_ref=policy_ref, development_envelope_ref=envelope,
        deadline=started + timedelta(seconds=policy.WALL_SECONDS),
    )
    spec = RunnerOperationSpec.model_validate(partial.model_dump() | {"request_digest": operation_digest(partial)})
    return spec, inputs


def save_json(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    policy.acquire_probe_lock()
    operation_id = "runner-probe-" + uuid4().hex
    directory = toolchain.RUNTIME_ROOT / operation_id
    toolchain.private_directory(directory)
    client = toolchain.DockerClient.create(directory)
    print(json.dumps({"stage": "fixed_public_toolchain", "operation_id": operation_id}), flush=True)
    try:
        image = toolchain.ensure_toolchain(client)
    except toolchain.ProbeFailure as failure:
        value = {"operation_id": operation_id, "all_required_verified": False,
                 "failure": failure.category, "diagnostic": failure.diagnostic,
                 "detail": failure.detail,
                 "stage": "toolchain", "observed_at": datetime.now(timezone.utc).isoformat()}
        save_json(directory / "toolchain-failure.json", value)
        print(json.dumps(value), flush=True)
        return 1
    started = datetime.now(timezone.utc)
    spec, inputs = registered_spec(operation_id, started)
    save_json(directory / "registered-operation.json", spec.model_dump(mode="json"))
    save_json(directory / "input-set.json", inputs.model_dump(mode="json"))
    probe = capabilities.CapabilityProbe(client, operation_id, directory, image["reference"], time.monotonic())
    failures: list[str] = []
    diagnostics: list[str] = []
    try:
        print(json.dumps({"stage": "restricted_rootless_start", "operation_id": operation_id}), flush=True)
        probe.create()
        probe.observe_boundary()
        print(json.dumps({"stage": "fixed_offline_exec_probe", "operation_id": operation_id}), flush=True)
        probe.run_fixed_build()
    except toolchain.ProbeFailure as failure:
        failures.append(failure.category)
        if failure.diagnostic:
            failures.append(failure.diagnostic)
        if failure.detail:
            diagnostics.append(failure.detail)
    except Exception as failure:
        # Exception text is not public: it can include Docker output or runtime paths.
        failures.append("probe_observation_exception_" + type(failure).__name__)
    finally:
        try:
            probe.records["stop_confirmation"] = probe.stop_and_remove()
        except toolchain.ProbeFailure as failure:
            failures.append(failure.category)
            if failure.detail:
                diagnostics.append(failure.detail)
    records = tuple(probe.records.get(name, CapabilityEvidence(
        capability=name, status="unverified", reason="preceding_probe_not_completed")) for name in CAPABILITY_NAMES)
    report = RunnerCapabilityReport(spec=spec, started_at=started, finished_at=datetime.now(timezone.utc),
        toolchain_image_id=image["image_id"], container_id=probe.container_id,
        probe_input_digest=probe.probe_input_digest,
        security_exceptions=policy.SECURITY_EXCEPTIONS, capabilities=records,
        failures=tuple(failures), diagnostics=tuple(diagnostics))
    # Keep the stored contract round-trippable; the derived summary is printed below.
    save_json(directory / "report.json", report.model_dump(mode="json", exclude_computed_fields=True))
    print(json.dumps({"report_path": str(directory / "report.json"), **report.model_dump(mode="json")},
                     ensure_ascii=False), flush=True)
    return 0 if report.all_required_verified else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except toolchain.ProbeFailure as failure:
        print(json.dumps({"all_required_verified": False, "failure": failure.category,
                          "diagnostic": failure.diagnostic, "detail": failure.detail}), flush=True)
        raise SystemExit(1) from None
