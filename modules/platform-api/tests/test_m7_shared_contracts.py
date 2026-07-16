"""M7-1 Environment、RemoteTarget、heartbeat 与 OpenAPI 契约测试。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

from cloudhelm_platform_api.main import app
from cloudhelm_platform_api.schemas.environment import (
    EnvironmentCreate,
    EnvironmentRead,
)
from cloudhelm_platform_api.schemas.remote_target import (
    RemoteAgentHeartbeat,
    RemoteAgentHeartbeatRead,
    RemoteTargetCreate,
    RemoteTargetRead,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "shared-contracts"
REMOTE_AGENT_SRC = REPOSITORY_ROOT / "modules" / "remote-agent" / "src"
if str(REMOTE_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(REMOTE_AGENT_SRC))

from cloudhelm_remote_agent.schemas import HeartbeatAck, HeartbeatPayload

M7_1_EVENT_TYPES = {
    "EnvironmentCreated",
    "RemoteTargetRegistered",
    "RemoteAgentHeartbeat",
    "RemoteAgentOnline",
    "RemoteAgentOffline",
    "RemoteAgentRecovered",
}
M7_2B_EVENT_TYPES = {
    "RepositoryBindingConfigured",
    "ApprovalExpired",
}
MACHINE_HEADER_NAMES = {
    "X-CloudHelm-Target-Id",
    "X-CloudHelm-Agent-Id",
    "X-CloudHelm-Key-Id",
    "X-CloudHelm-Timestamp",
    "X-CloudHelm-Nonce",
    "X-CloudHelm-Signature",
}


def test_m7_remote_json_schemas_match_platform_pydantic_models() -> None:
    """三个共享文件的 defs 必须与 Platform API DTO 精确一致。"""

    cases = {
        "schemas/remote/environment.schema.json": {
            "EnvironmentCreate": EnvironmentCreate,
            "EnvironmentRead": EnvironmentRead,
        },
        "schemas/remote/remote-target.schema.json": {
            "RemoteTargetCreate": RemoteTargetCreate,
            "RemoteTargetRead": RemoteTargetRead,
        },
        "schemas/remote/remote-agent-heartbeat.schema.json": {
            "RemoteAgentHeartbeat": RemoteAgentHeartbeat,
            "RemoteAgentHeartbeatRead": RemoteAgentHeartbeatRead,
        },
    }
    for relative_path, models in cases.items():
        schema = _read_json(CONTRACT_ROOT / relative_path)
        assert schema["$schema"] == (
            "https://json-schema.org/draft/2020-12/schema"
        )
        assert schema["$id"].startswith(
            "https://cloudhelm.local/schemas/remote/"
        )
        assert set(schema["$defs"]) == set(models)
        for name, model in models.items():
            assert schema["$defs"][name] == model.model_json_schema()


def test_remote_agent_heartbeat_models_match_platform_contract() -> None:
    """Remote Agent 发送/接收 DTO 与 Platform API 只允许文案和类名不同。"""

    pairs = (
        (RemoteAgentHeartbeat, HeartbeatPayload),
        (RemoteAgentHeartbeatRead, HeartbeatAck),
    )
    for platform_model, remote_model in pairs:
        platform_schema = copy.deepcopy(platform_model.model_json_schema())
        remote_schema = copy.deepcopy(remote_model.model_json_schema())
        for schema in (platform_schema, remote_schema):
            schema.pop("title", None)
            schema.pop("description", None)
        assert remote_schema == platform_schema


def test_m7_event_types_are_unique_and_present_in_shared_contract() -> None:
    """生产代码写入的 M7-1 事件必须全部进入共享枚举。"""

    schema = _read_json(
        CONTRACT_ROOT / "schemas/events/task-event.schema.json"
    )
    event_types = schema["properties"]["event_type"]["enum"]

    assert len(event_types) == len(set(event_types))
    assert M7_1_EVENT_TYPES.issubset(event_types)
    assert M7_2B_EVENT_TYPES.issubset(event_types)
    assert "M2-M7-2B1" in schema["description"]


def test_repository_binding_event_schema_rejects_internal_fields() -> None:
    """Binding 事件 payload 使用精确 allowlist，契约层拒绝内部配置。"""

    schema = _read_json(
        CONTRACT_ROOT / "schemas/events/task-event.schema.json"
    )
    validator = Draft202012Validator(schema)
    event = {
        "id": "00000000-0000-0000-0000-000000000701",
        "task_id": None,
        "event_type": "RepositoryBindingConfigured",
        "actor_type": "system",
        "actor_id": "repository-profile",
        "created_at": "2026-07-16T00:00:00Z",
        "payload": {
            "project_id": "00000000-0000-0000-0000-000000000001",
            "repository_binding_id": (
                "00000000-0000-0000-0000-000000000301"
            ),
            "profile_key": "demo-gitea-repository",
            "provider": "gitea",
            "repository_external_id": "42",
            "repository_owner": "cloudhelm",
            "repository_name": "sample-api",
            "default_branch": "dev",
            "workflow_id": ".gitea/workflows/ci.yml",
            "release_ref_prefix": "refs/heads/cloudhelm/candidates",
            "status": "active",
            "created": True,
            "configuration_changed": False,
            "stale_candidate_ids": [],
            "expired_approval_ids": [],
        },
    }

    assert validator.is_valid(event)
    event["payload"]["clone_url"] = "https://internal.example.test/repo.git"
    assert not validator.is_valid(event)
    event["payload"].pop("clone_url")
    event.pop("actor_id")
    assert not validator.is_valid(event)


def test_heartbeat_openapi_requires_headers_and_documents_errors() -> None:
    """machine-auth 六个请求头和实际错误状态必须出现在 OpenAPI。"""

    operation = app.openapi()["paths"][
        "/api/remote-agents/heartbeat"
    ]["post"]
    parameters = {
        parameter["name"]: parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header"
    }

    assert set(parameters) == MACHINE_HEADER_NAMES
    assert all(parameter["required"] is True for parameter in parameters.values())
    assert {"200", "401", "403", "413", "422", "503"}.issubset(
        operation["responses"]
    )


def _read_json(path: Path) -> dict[str, Any]:
    """以 UTF-8 读取共享 JSON 文档。"""

    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    assert isinstance(value, dict)
    return value
