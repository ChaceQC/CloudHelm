"""Broker、handler payload/result 与共享 JSON Schema 测试。"""

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from cloudhelm_platform_api.schemas.workflow_job import (
    ReleaseCandidateReconcilePayload,
    ReleaseCandidateReconcileResult,
    WorkflowJobBrokerMessage,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_SCHEMA = (
    REPO_ROOT
    / "packages"
    / "shared-contracts"
    / "schemas"
    / "workflow"
    / "workflow-job.schema.json"
)


def test_broker_message_only_accepts_workflow_job_id() -> None:
    """业务正文或 secret 字段不能进入 Redis。"""

    job_id = uuid4()
    message = WorkflowJobBrokerMessage(workflow_job_id=str(job_id))

    assert message.model_dump(mode="json") == {
        "workflow_job_id": str(job_id)
    }
    with pytest.raises(ValidationError):
        WorkflowJobBrokerMessage.model_validate(
            {
                "workflow_job_id": str(job_id),
                "payload": {"credential": "secret"},
            }
        )


def test_payload_rejects_noncanonical_uuid_and_extra_fields() -> None:
    """payload 的 UUID/hash/schema version 都使用冻结形式。"""

    candidate_id = uuid4()
    payload = {
        "schema_version": "m7.release-candidate-reconcile.payload.v1",
        "candidate_id": str(candidate_id),
        "approval_id": str(uuid4()),
        "expected_candidate_request_hash": "sha256:" + ("a" * 64),
        "expected_binding_snapshot_sha256": "sha256:" + ("b" * 64),
        "expected_pull_request_record_id": str(uuid4()),
    }

    assert ReleaseCandidateReconcilePayload.model_validate(payload)
    with pytest.raises(ValidationError):
        ReleaseCandidateReconcilePayload.model_validate(
            {**payload, "candidate_id": candidate_id.hex}
        )
    with pytest.raises(ValidationError):
        ReleaseCandidateReconcilePayload.model_validate(
            {**payload, "unexpected": True}
        )


def test_result_enforces_outcome_state_pair_and_utc() -> None:
    """result 不允许伪造相互矛盾的 outcome/status。"""

    valid = ReleaseCandidateReconcileResult(
        outcome="valid",
        candidate_status="pending_approval",
        approval_status="pending",
        pull_request_record_id=uuid4(),
        binding_snapshot_sha256="sha256:" + ("c" * 64),
        checked_at=datetime.now(UTC),
    )

    assert valid.outcome == "valid"
    with pytest.raises(ValidationError):
        ReleaseCandidateReconcileResult(
            outcome="valid",
            candidate_status="stale",
            approval_status="expired",
            pull_request_record_id=uuid4(),
            binding_snapshot_sha256="sha256:" + ("c" * 64),
            checked_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        ReleaseCandidateReconcileResult(
            outcome="stale",
            candidate_status="stale",
            approval_status="expired",
            pull_request_record_id=uuid4(),
            binding_snapshot_sha256="sha256:" + ("c" * 64),
            checked_at=datetime.now().replace(tzinfo=None),
        )


def test_shared_workflow_schema_is_meta_valid() -> None:
    """共享 workflow schema 与 wire DTO/record 约束保持一致。"""

    schema = json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )
    now = datetime.now(UTC)
    broker = WorkflowJobBrokerMessage(
        workflow_job_id=uuid4()
    ).model_dump(mode="json")
    payload = ReleaseCandidateReconcilePayload(
        schema_version="m7.release-candidate-reconcile.payload.v1",
        candidate_id=uuid4(),
        approval_id=uuid4(),
        expected_candidate_request_hash="sha256:" + ("a" * 64),
        expected_binding_snapshot_sha256="sha256:" + ("b" * 64),
        expected_pull_request_record_id=uuid4(),
    ).model_dump(mode="json")
    result = ReleaseCandidateReconcileResult(
        outcome="terminal_noop",
        candidate_status="published",
        approval_status="approved",
        pull_request_record_id=uuid4(),
        binding_snapshot_sha256="sha256:" + ("c" * 64),
        checked_at=now,
    ).model_dump(mode="json")
    record = {
        "id": str(uuid4()),
        "task_id": str(uuid4()),
        "job_type": "release_candidate_reconcile",
        "resource_type": "release_candidate",
        "resource_id": str(uuid4()),
        "side_effect_class": "none",
        "request_hash": "sha256:" + ("d" * 64),
        "idempotency_key": "release-candidate-reconcile:test",
        "status": "pending",
        "attempt": 0,
        "max_attempts": 3,
        "lease_owner": None,
        "lease_expires_at": None,
        "heartbeat_at": None,
        "next_retry_at": None,
        "cancel_requested_at": None,
        "dispatch_lease_owner": None,
        "dispatch_lease_expires_at": None,
        "next_enqueue_at": now.isoformat().replace("+00:00", "Z"),
        "last_enqueued_at": None,
        "enqueue_attempt": 0,
        "last_enqueue_error_code": None,
        "payload_json": payload,
        "result_json": None,
        "error_code": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    }

    for value in (broker, payload, result, record):
        assert validator.is_valid(value), list(
            validator.iter_errors(value)
        )

    contradictory = {
        **result,
        "candidate_status": "pending_approval",
        "approval_status": "pending",
    }
    assert not validator.is_valid(contradictory)
    missing_nullable = dict(record)
    del missing_nullable["lease_owner"]
    assert not validator.is_valid(missing_nullable)
    exhausted_pending = {**record, "attempt": 4}
    assert not validator.is_valid(exhausted_pending)
