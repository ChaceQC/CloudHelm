"""M7-2D Record DTO 的 Draft 2020-12 生命周期条件。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

JsonSchema = dict[str, Any]


def _field_rules(
    fields: Iterable[str],
    rule: JsonSchema,
) -> JsonSchema:
    """构造一组属性的统一约束；Record 本体已要求全字段存在。"""

    names = list(fields)
    return {
        "properties": {
            name: dict(rule)
            for name in names
        },
    }


def _null_fields(*fields: str) -> JsonSchema:
    """要求字段全部为 JSON null。"""

    return _field_rules(fields, {"type": "null"})


def _non_null_fields(*fields: str) -> JsonSchema:
    """要求字段全部不为 JSON null。"""

    return _field_rules(fields, {"not": {"type": "null"}})


def _status_condition(statuses: str | Iterable[str]) -> JsonSchema:
    """构造状态匹配条件。"""

    values = [statuses] if isinstance(statuses, str) else list(statuses)
    status_rule: JsonSchema
    if len(values) == 1:
        status_rule = {"const": values[0]}
    else:
        status_rule = {"enum": values}
    return {
        "properties": {
            "status": status_rule,
        },
    }


def _when_status(
    statuses: str | Iterable[str],
    then_schema: JsonSchema,
) -> JsonSchema:
    """为一个或多个状态增加 if/then 证据门禁。"""

    return {
        "if": _status_condition(statuses),
        "then": then_schema,
    }


def _all_of(*rules: JsonSchema) -> JsonSchema:
    """组合必须同时成立的属性规则。"""

    return {"allOf": list(rules)}


CI_RUN_JSON_SCHEMA_EXTRA: JsonSchema = {
    "allOf": [
        {
            "oneOf": [
                _null_fields(
                    "last_event_action",
                    "last_event_status",
                    "last_delivery_id",
                    "provider_updated_at",
                ),
                _non_null_fields(
                    "last_event_action",
                    "last_event_status",
                    "last_delivery_id",
                    "provider_updated_at",
                ),
            ]
        },
        {
            "if": _non_null_fields("external_job_id"),
            "then": _non_null_fields("external_run_id"),
        },
        _when_status(
            "triggered",
            _null_fields(
                "started_at",
                "finished_at",
                "artifact_manifest_id",
                "image_index_digest",
                "platform_manifest_digest",
            ),
        ),
        _when_status(
            "running",
            _all_of(
                _non_null_fields("external_run_id", "started_at"),
                _null_fields(
                    "finished_at",
                    "artifact_manifest_id",
                    "image_index_digest",
                    "platform_manifest_digest",
                ),
            ),
        ),
        _when_status(
            "passed",
            _non_null_fields(
                "external_run_id",
                "started_at",
                "finished_at",
                "provider_head_sha",
                "artifact_manifest_id",
                "image_index_digest",
                "platform_manifest_digest",
            ),
        ),
        _when_status(
            ["failed", "cancelled"],
            _all_of(
                _non_null_fields("finished_at"),
                _null_fields(
                    "artifact_manifest_id",
                    "image_index_digest",
                    "platform_manifest_digest",
                ),
            ),
        ),
    ]
}


DEPLOYMENT_JSON_SCHEMA_EXTRA: JsonSchema = {
    "allOf": [
        _when_status(
            "planned",
            _null_fields("approval_id", "approved_by_actor"),
        ),
        _when_status(
            "pending_approval",
            _all_of(
                _non_null_fields("approval_id"),
                _null_fields("approved_by_actor"),
            ),
        ),
        _when_status(
            [
                "queued",
                "deploying",
                "verifying",
                "healthy",
                "unhealthy",
                "rollback_requested",
            ],
            _non_null_fields("approval_id", "approved_by_actor"),
        ),
        _when_status(
            ["failed", "cancelled"],
            {
                "anyOf": [
                    _null_fields("approved_by_actor"),
                    _non_null_fields("approval_id"),
                ]
            },
        ),
        _when_status(
            ["planned", "pending_approval", "queued"],
            _null_fields(
                "remote_operation_id",
                "started_at",
                "finished_at",
            ),
        ),
        _when_status(
            ["deploying", "verifying"],
            _all_of(
                _non_null_fields("remote_operation_id", "started_at"),
                _null_fields("finished_at"),
            ),
        ),
        _when_status(
            ["healthy", "unhealthy", "rollback_requested"],
            _non_null_fields(
                "remote_operation_id",
                "started_at",
                "finished_at",
                "health_summary_json",
            ),
        ),
        _when_status(
            ["failed", "cancelled"],
            _all_of(
                _non_null_fields("finished_at"),
                {
                    "oneOf": [
                        _null_fields(
                            "remote_operation_id",
                            "started_at",
                        ),
                        _non_null_fields(
                            "remote_operation_id",
                            "started_at",
                        ),
                    ]
                },
            ),
        ),
        _when_status(
            "failed",
            _non_null_fields("failure_code"),
        ),
        _when_status(
            [
                "planned",
                "pending_approval",
                "queued",
                "deploying",
                "verifying",
                "healthy",
                "unhealthy",
                "rollback_requested",
                "cancelled",
            ],
            _null_fields("failure_code", "failure_summary"),
        ),
        _when_status(
            "rollback_requested",
            _non_null_fields(
                "rollback_candidate_id",
                "rollback_request_artifact_id",
            ),
        ),
        _when_status(
            [
                "planned",
                "pending_approval",
                "queued",
                "deploying",
                "verifying",
                "healthy",
                "unhealthy",
                "failed",
                "cancelled",
            ],
            _null_fields(
                "rollback_candidate_id",
                "rollback_request_artifact_id",
            ),
        ),
    ]
}


SERVICE_INSTANCE_JSON_SCHEMA_EXTRA: JsonSchema = {
    "allOf": [
        {
            "oneOf": [
                _null_fields(
                    "health_result_json",
                    "last_health_check_at",
                ),
                _non_null_fields(
                    "health_result_json",
                    "last_health_check_at",
                ),
            ]
        },
        _when_status(
            ["healthy", "unhealthy"],
            _non_null_fields(
                "health_result_json",
                "last_health_check_at",
            ),
        ),
        _when_status(
            "failed",
            _non_null_fields("last_error_code"),
        ),
    ]
}
