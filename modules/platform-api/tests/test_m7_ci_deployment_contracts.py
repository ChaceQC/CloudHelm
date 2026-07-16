"""M7-2D Pydantic 与共享 JSON Schema 契约测试。"""

from datetime import timedelta
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from cloudhelm_platform_api.main import app
from cloudhelm_platform_api.schemas.ci_run import CIRunRecord
from cloudhelm_platform_api.schemas.deployment import DeploymentRecord
from cloudhelm_platform_api.schemas.service_instance import (
    ServiceInstanceRecord,
)

from m7_ci_deployment_fixture import (
    IMAGE_DIGEST,
    build_healthy_deployment,
    build_passed_ci_run,
    build_service_instance,
    seed_m7_ci_deployment_dependencies,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "shared-contracts"


def test_m7_ci_deployment_shared_schemas_match_pydantic_models() -> None:
    """三个共享 `$defs` 必须与内部 Record DTO 精确一致。"""

    cases = {
        "schemas/ci/ci-run.schema.json": {
            "CIRunRecord": CIRunRecord,
        },
        "schemas/deployment/deployment.schema.json": {
            "DeploymentRecord": DeploymentRecord,
        },
        "schemas/deployment/service-instance.schema.json": {
            "ServiceInstanceRecord": ServiceInstanceRecord,
        },
    }
    for relative_path, models in cases.items():
        schema = _read_json(CONTRACT_ROOT / relative_path)
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == (
            "https://json-schema.org/draft/2020-12/schema"
        )
        assert set(schema["$defs"]) == set(models)
        for name, model in models.items():
            assert schema["$defs"][name] == model.model_json_schema()
            assert set(schema["$defs"][name]["properties"]) == set(
                schema["$defs"][name]["required"]
            )


def test_m7_record_models_accept_orm_attributes_and_shared_schema() -> None:
    """完整合法 ORM 记录可直接转换，并通过相同共享 JSON Schema。"""

    for relative_path, record in _valid_record_cases():
        validator = _validator(relative_path)
        value = record.model_dump(mode="json")
        assert validator.is_valid(value), list(validator.iter_errors(value))


@pytest.mark.parametrize(
    ("case_index", "field_name", "field_value"),
    [
        (0, "token", "example-sensitive-value"),
        (1, "credential_ref", "example/credential"),
        (2, "raw_logs", "example raw output"),
    ],
)
def test_m7_record_contracts_reject_injected_extra_sensitive_fields(
    case_index: int,
    field_name: str,
    field_value: str,
) -> None:
    """从合法 Record 注入敏感额外字段，两套契约必须同时拒绝。"""

    relative_path, record = _valid_record_cases()[case_index]
    payload = record.model_dump(mode="json")
    payload[field_name] = field_value
    with pytest.raises(ValidationError):
        type(record).model_validate(payload)
    assert not _validator(relative_path).is_valid(payload)


@pytest.mark.parametrize(
    ("case_index", "field_name"),
    [
        (1, "token"),
        (1, "raw_logs"),
        (2, "credential"),
        (2, "stderr"),
    ],
)
def test_m7_health_evidence_rejects_sensitive_keys_in_both_contracts(
    case_index: int,
    field_name: str,
) -> None:
    """健康对象内部的敏感键不能借 additionalProperties 绕过。"""

    relative_path, record = _valid_record_cases()[case_index]
    payload = record.model_dump(mode="json")
    health_field = (
        "health_summary_json"
        if case_index == 1
        else "health_result_json"
    )
    payload[health_field] = {field_name: "example-sensitive-value"}
    with pytest.raises(ValidationError, match="健康证据"):
        type(record).model_validate(payload)
    assert not _validator(relative_path).is_valid(payload)


def test_m7_record_contracts_reject_invalid_lifecycle_combinations() -> None:
    """可由 JSON Schema 表达的生命周期门禁必须与 Pydantic 一致。"""

    cases = _valid_record_cases()
    invalid_payloads: list[tuple[int, dict[str, Any]]] = []

    ci_payload = cases[0][1].model_dump(mode="json")
    ci_payload["last_event_status"] = None
    invalid_payloads.append((0, ci_payload))

    ci_running = cases[0][1].model_dump(mode="json")
    ci_running.update(
        {
            "status": "running",
            "external_run_id": None,
            "external_job_id": None,
            "finished_at": None,
            "artifact_manifest_id": None,
            "image_index_digest": None,
            "platform_manifest_digest": None,
        }
    )
    invalid_payloads.append((0, ci_running))

    failed_deployment = cases[1][1].model_dump(mode="json")
    failed_deployment.update(
        {
            "status": "failed",
            "failure_code": None,
            "health_summary_json": None,
        }
    )
    invalid_payloads.append((1, failed_deployment))

    rollback = cases[1][1].model_dump(mode="json")
    rollback.update(
        {
            "status": "rollback_requested",
            "approval_id": None,
            "approved_by_actor": None,
            "remote_operation_id": None,
            "started_at": None,
            "health_summary_json": None,
            "rollback_candidate_id": str(uuid4()),
            "rollback_request_artifact_id": str(uuid4()),
        }
    )
    invalid_payloads.append((1, rollback))

    service = cases[2][1].model_dump(mode="json")
    service.update(
        {
            "health_result_json": None,
            "last_health_check_at": None,
        }
    )
    invalid_payloads.append((2, service))

    failed_service = cases[2][1].model_dump(mode="json")
    failed_service.update(
        {
            "status": "failed",
            "last_error_code": None,
        }
    )
    invalid_payloads.append((2, failed_service))

    for case_index, payload in invalid_payloads:
        relative_path, record = cases[case_index]
        with pytest.raises(ValidationError):
            type(record).model_validate(payload)
        validator = _validator(relative_path)
        assert not validator.is_valid(payload), list(
            validator.iter_errors(payload)
        )


@pytest.mark.parametrize(
    ("case_index", "field_name", "invalid_value"),
    [
        (0, "source_ref", "refs/heads/bad..ref"),
        (
            1,
            "image_ref",
            f"user@registry.example.test/sample@{IMAGE_DIGEST}",
        ),
        (
            2,
            "health_url",
            "https://user:password@staging.example.test/health",
        ),
    ],
)
def test_m7_record_contracts_reject_unsafe_refs_and_urls(
    case_index: int,
    field_name: str,
    invalid_value: str,
) -> None:
    """Git ref、OCI ref 与健康 URL 的安全格式在两套契约中一致。"""

    relative_path, record = _valid_record_cases()[case_index]
    payload = record.model_dump(mode="json")
    payload[field_name] = invalid_value
    with pytest.raises(ValidationError):
        type(record).model_validate(payload)
    validator = _validator(relative_path)
    assert not validator.is_valid(payload), list(
        validator.iter_errors(payload)
    )


def test_m7_2d_does_not_add_future_http_paths() -> None:
    """数据底座不得提前暴露 CI 或 Deployment endpoint。"""

    paths = set(app.openapi()["paths"])
    forbidden = {
        "/api/tasks/{task_id}/ci-runs",
        "/api/tasks/{task_id}/deployments",
        "/api/deployments/{deployment_id}",
        "/api/deployments/{deployment_id}/services",
    }
    assert paths.isdisjoint(forbidden)


def _read_json(path: Path) -> dict[str, Any]:
    """以 UTF-8 读取共享 JSON 文档。"""

    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    assert isinstance(value, dict)
    return value


def _validator(relative_path: str) -> Draft202012Validator:
    """读取共享 Schema 并构造启用 format 的验证器。"""

    return Draft202012Validator(
        _read_json(CONTRACT_ROOT / relative_path),
        format_checker=FormatChecker(),
    )


def _valid_record_cases() -> list[tuple[str, Any]]:
    """构造三类具有完整真实证据的合法 Record。"""

    references = seed_m7_ci_deployment_dependencies()
    ci_model = build_passed_ci_run(
        references,
        id=uuid4(),
        external_run_id="run-42",
        external_job_id="job-7",
        last_event_action="completed",
        last_event_status="success",
        last_delivery_id="delivery-42",
        provider_updated_at=references.now + timedelta(seconds=1),
    )
    ci_record = CIRunRecord.model_validate(ci_model)

    deployment_model = build_healthy_deployment(
        references,
        ci_run_id=ci_model.id,
        remote_operation_id="operation-42",
        health_summary_json={
            "status": "ok",
            "http_status": 200,
        },
    )
    deployment_record = DeploymentRecord.model_validate(deployment_model)

    service_model = build_service_instance(
        references,
        id=uuid4(),
        deployment_id=deployment_model.id,
        status="healthy",
        runtime_ref="container-42",
        health_url="https://staging.example.test/health",
        health_result_json={
            "status": "ok",
            "duration_ms": 12.5,
        },
        last_health_check_at=references.now + timedelta(seconds=1),
        created_at=references.now,
        updated_at=references.now + timedelta(seconds=1),
    )
    service_record = ServiceInstanceRecord.model_validate(service_model)

    return [
        ("schemas/ci/ci-run.schema.json", ci_record),
        ("schemas/deployment/deployment.schema.json", deployment_record),
        (
            "schemas/deployment/service-instance.schema.json",
            service_record,
        ),
    ]
