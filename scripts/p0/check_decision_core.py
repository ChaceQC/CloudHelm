"""Fixed negative contract examples, not product or security acceptance."""

from pydantic import ValidationError

from packages.contracts.p0.core_contracts import AcceptedReceipt, RunContinuity, TurnResult
from packages.contracts.p0.delivery_contracts import EnvironmentConfigRevision, ReleaseManifest
from packages.contracts.p0.emergency_contracts import EmergencyAccessProfile, MaintenanceGate
from packages.contracts.p0.engineering_contracts import (
    EngineeringRef, EvidenceRecord, InputSet, input_set_digest,
)

DIGEST = "sha256:" + "a" * 64


def reference(kind, object_id=None):
    payload = {"kind": kind, "object_id": object_id or kind, "revision": "r1"}
    if kind not in {"task", "session", "run", "operation", "wait_condition", "secret_version"}:
        payload.update(digest=DIGEST, digest_algorithm="sha256")
    return EngineeringRef(**payload)


def rejects(call):
    try:
        call()
    except (ValueError, ValidationError):
        return True
    return False


def release_payload():
    fields = {
        "source_ref": "source", "build_input_ref": "input_set", "build_run_ref": "build",
        "runtime_contract_ref": "runtime", "configuration_schema_ref": "config_schema",
        "acceptance_assets_ref": "acceptance_assets", "descriptor_ref": "descriptor",
        "compose_ref": "compose", "variant_ref": "variant",
    }
    return {
        "release_id": "release-1", "parser_revision": "p0-decisions-r1",
        **{field: reference(kind) for field, kind in fields.items()},
        "services": ({"service_key": "backend", "platform": "linux/amd64", "artifact_ref": reference("artifact")},),
        "verification_refs": (reference("evidence"),),
    }


def emergency_payload():
    return {
        "profile_id": "profile-example", "revision": 1,
        "installation_id": "installation-example", "executor_instance": "executor-example",
        "owner_user_id": "owner-example", "local_admin_identity": "admin-example", "local_admin_uid": 1001,
        "authentication": "so-peercred-and-ed25519-challenge-r1",
        "authentication_material_ref": reference("secret_version"),
        "resource_scope": ("environment-example",), "allowed_actions": ("controlled_restart",),
        "policy_ref": reference("policy"), "valid_from": "2026-10-14T00:00:00Z",
        "valid_until": "2026-10-14T01:00:00Z", "max_execution_seconds": 300,
    }


def run_checks() -> dict[str, bool]:
    refs = (reference("source"), reference("contract"))
    frozen = InputSet(input_set_id="set-1", references=refs, set_digest=input_set_digest(refs))
    continuity = {
        "session_id": "session-1", "run_id": "run-1", "workflow_id": "workflow-1",
        "trigger": "crash_recovery", "prior_session_id": "session-1",
        "prior_run_id": "run-1", "prior_workflow_id": "workflow-1",
    }
    recovered = RunContinuity(**continuity)
    continued = RunContinuity(**{**continuity, "trigger": "wait_continuation", "run_id": "run-2", "workflow_id": "workflow-2"})
    receipt = {"operation_id": "operation-1", "request_digest": DIGEST,
               "query_ref": reference("operation", "operation-1"), "wait_ref": reference("operation", "operation-1")}
    release = ReleaseManifest(**release_payload())
    environment = EnvironmentConfigRevision(
        environment_id="test-env", revision=1, parameter_set_ref=reference("parameter_set"),
        resource_binding_refs=(reference("resource_binding"),), secret_refs=(reference("secret_version"),),
    )
    evidence = {"evidence_id": "evidence-1", "subject_ref": reference("artifact"),
                "input_set_ref": reference("input_set"), "method_ref": reference("method"),
                "environment_ref": reference("environment"), "result": "unknown", "support_scope": ("synthetic-contract",)}
    checks = {
        "reference_order_stable": frozen.set_digest == input_set_digest(tuple(reversed(refs))),
        "changed_input_invalidates_digest": rejects(lambda: InputSet(input_set_id="set-1", references=(refs[0], reference("contract", "other")), set_digest=frozen.set_digest)),
        "duplicate_input_rejected": rejects(lambda: InputSet(input_set_id="set-1", references=(refs[0], refs[0]), set_digest=DIGEST)),
        "secret_is_reference_only": rejects(lambda: EngineeringRef(kind="secret_version", object_id="credential-ref", revision="r1", value="synthetic-content")),
        "secret_plaintext_hash_rejected": rejects(lambda: EngineeringRef(kind="secret_version", object_id="credential-ref", revision="r1", digest=DIGEST, digest_algorithm="sha256")),
        "crash_identity_preserved": recovered.run_id == "run-1",
        "wait_identity_changes": continued.run_id != recovered.run_id,
        "wait_cannot_reuse_run": rejects(lambda: RunContinuity(**{**continuity, "trigger": "wait_continuation"})),
        "accepted_is_not_success": AcceptedReceipt(**receipt).status == "accepted" and rejects(lambda: AcceptedReceipt(**receipt, status="succeeded")),
        "wait_requires_condition": rejects(lambda: TurnResult(run_id="run-1", outcome="waiting_condition", history_delta=reference("history"), reason_code="WAIT")),
        "release_rejects_environment_values": rejects(lambda: ReleaseManifest(**release_payload(), environment_id=environment.environment_id)),
        "environment_rejects_raw_secrets": release.release_id == "release-1" and rejects(lambda: EnvironmentConfigRevision(**environment.model_dump(), secret_values={"credential": "synthetic-content"})),
        "audit_requires_utc": rejects(lambda: EvidenceRecord(**evidence, observed_at="2026-10-14T08:00:00+08:00")),
        "unknown_evidence_preserved": EvidenceRecord(**evidence, observed_at="2026-10-14T00:00:00Z").result == "unknown",
        "emergency_disabled": not EmergencyAccessProfile(**emergency_payload()).enabled and rejects(lambda: EmergencyAccessProfile(**emergency_payload(), enabled=True)),
        "recovery_operation_is_distinct": rejects(lambda: MaintenanceGate(maintenance_id="m1", installation_id="i1", executor_instance="e1", profile_id="p1", profile_revision=1, local_admin_identity="a1", resource_scope=("r1",), original_operation_id="op1", recovery_operation_id="op1")),
    }
    if not all(checks.values()):
        raise AssertionError({name: result for name, result in checks.items() if not result})
    return checks


if __name__ == "__main__":
    import json
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
