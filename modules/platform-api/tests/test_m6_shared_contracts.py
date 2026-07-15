"""M6 OpenAPI、Artifact/PR JSON Schema 与事件契约回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from cloudhelm_tool_gateway import ToolCallRequest, create_default_gateway
from jsonschema.validators import validator_for

from cloudhelm_platform_api.main import app
from cloudhelm_platform_api.schemas.artifact import ArtifactDetailRead
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordRead,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "packages" / "shared-contracts"
M6_EVENT_TYPES = {
    "LocalDevelopmentStarted",
    "ScaffoldCompleted",
    "CodePatchGenerated",
    "TestRunStarted",
    "TestRunPassed",
    "TestRunFailed",
    "ReviewCompleted",
    "SecurityScanCompleted",
    "SecurityScanBlocked",
    "ArtifactCreated",
    "BranchCreated",
    "CommitCreated",
    "PullRequestRecordCreated",
}
M6_TOOL_SCHEMA_GROUPS = {
    "schemas/tools/repo-tool.schema.json": {
        "repo.read_file",
        "repo.search_text",
        "repo.write_file",
        "repo.list_files",
    },
    "schemas/tools/scaffold-tool.schema.json": {
        "scaffold.prepare_workspace",
    },
    "schemas/tools/sandbox-tool.schema.json": {
        "sandbox.run_command",
        "sandbox.collect_artifact",
    },
    "schemas/tools/test-tool.schema.json": {
        "test.run_pytest",
    },
    "schemas/tools/security-tool.schema.json": {
        "security.run_bandit",
        "security.run_pip_audit",
    },
    "schemas/tools/git-tool.schema.json": {
        "git.status",
        "git.diff",
        "git.create_branch",
        "git.commit",
        "git.format_patch",
    },
}


def test_artifact_and_pull_request_contracts_match_pydantic() -> None:
    """独立 JSON Schema 必须与 Platform API Pydantic DTO 精确一致。"""

    cases = (
        (
            "schemas/artifacts/artifact.schema.json",
            ArtifactDetailRead.model_json_schema(),
        ),
        (
            "schemas/artifacts/pull-request-record.schema.json",
            PullRequestRecordRead.model_json_schema(),
        ),
    )
    for relative_path, expected in cases:
        actual = _read_json(CONTRACT_ROOT / relative_path)
        assert actual.pop("$schema") == (
            "https://json-schema.org/draft/2020-12/schema"
        )
        assert actual.pop("$id").startswith(
            "https://cloudhelm.local/schemas/artifacts/"
        )
        assert actual == expected


def test_task_event_contract_contains_each_m6_event_once() -> None:
    """EventSource 和后端写入的 M6 事件必须全部进入共享枚举。"""

    schema = _read_json(
        CONTRACT_ROOT / "schemas/events/task-event.schema.json"
    )
    event_types = schema["properties"]["event_type"]["enum"]

    assert len(event_types) == len(set(event_types))
    assert M6_EVENT_TYPES.issubset(event_types)
    assert "M2-M7-1" in schema["description"]


def test_shared_openapi_matches_fastapi_application() -> None:
    """共享 OpenAPI 必须是当前 FastAPI 应用契约的无漂移镜像。"""

    contract_path = CONTRACT_ROOT / "openapi/cloudhelm.openapi.yaml"
    with contract_path.open("r", encoding="utf-8") as stream:
        shared_openapi = yaml.safe_load(stream)

    assert shared_openapi == app.openapi()


def test_tool_call_request_contract_tracks_provider_identity_fields() -> None:
    """共享请求字段必须与 Tool Gateway Pydantic 请求模型同步。"""

    shared = _read_json(
        CONTRACT_ROOT / "schemas/tools/tool-call-request.schema.json"
    )
    runtime = ToolCallRequest.model_json_schema()

    assert set(shared["required"]) == set(runtime["required"])
    assert set(shared["properties"]) == set(runtime["properties"])
    assert shared["properties"]["provider_item_type"]["enum"] == [
        "function_call",
        "custom_tool_call",
        None,
    ]

    validator = validator_for(shared)(shared)
    base_request = {
        "task_id": "00000000-0000-0000-0000-000000000001",
        "tool_name": "repo.read_file",
        "risk_level": "L0",
        "idempotency_key": "m6:test:1",
        "arguments": {},
        "reason": "契约验证",
    }
    assert validator.is_valid(base_request)
    assert validator.is_valid(
        {
            **base_request,
            "provider_call_id": "call_001",
            "provider_item_type": "function_call",
        }
    )
    assert not validator.is_valid(
        {
            **base_request,
            "provider_call_id": "call_001",
        }
    )


def test_m6_tool_group_schemas_track_registry_fields() -> None:
    """M6 工具分组 schema 必须覆盖 registry 的名称、风险和参数字段。"""

    declarations = {
        item["name"]: item
        for item in create_default_gateway().list_tools()
    }
    for relative_path, expected_names in M6_TOOL_SCHEMA_GROUPS.items():
        schema = _read_json(CONTRACT_ROOT / relative_path)
        item_properties = schema["properties"]["tools"]["items"]["properties"]
        assert set(item_properties["name"]["enum"]) == expected_names
        assert set(item_properties["risk_level"]["enum"]) == {
            declarations[name]["risk_level"]
            for name in expected_names
        }

        shared_argument_names = set(item_properties["arguments"]["properties"])
        runtime_argument_names: set[str] = set()
        for name in expected_names:
            runtime_argument_names.update(
                declarations[name]["arguments_schema"]["properties"]
            )
        assert shared_argument_names == runtime_argument_names

    repo_arguments = _read_json(
        CONTRACT_ROOT / "schemas/tools/repo-tool.schema.json"
    )["properties"]["tools"]["items"]["properties"]["arguments"]["properties"]
    assert repo_arguments["mode"]["const"] == "replace"
    assert "expected_sha256" in repo_arguments

    sandbox_arguments = _read_json(
        CONTRACT_ROOT / "schemas/tools/sandbox-tool.schema.json"
    )["properties"]["tools"]["items"]["properties"]["arguments"]["properties"]
    assert sandbox_arguments["timeout_seconds"]["maximum"] == 300

    git_names = _read_json(
        CONTRACT_ROOT / "schemas/tools/git-tool.schema.json"
    )["properties"]["tools"]["items"]["properties"]["name"]["enum"]
    assert "git.format_patch" in git_names


def test_every_shared_json_schema_is_valid_draft_2020_12() -> None:
    """递归校验全部共享 JSON Schema 的元结构。"""

    schema_paths = sorted(
        (CONTRACT_ROOT / "schemas").rglob("*.schema.json")
    )
    assert len(schema_paths) >= 26
    for path in schema_paths:
        schema = _read_json(path)
        assert schema.get("$schema") == (
            "https://json-schema.org/draft/2020-12/schema"
        )
        validator_for(schema).check_schema(schema)


def _read_json(path: Path) -> dict[str, Any]:
    """以 UTF-8 读取共享 JSON Schema。"""

    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    assert isinstance(value, dict)
    return value
