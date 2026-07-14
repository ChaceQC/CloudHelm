"""M6 Artifact、PR record DTO 与 ORM metadata 白盒测试。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_platform_api.models import Base
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.schemas.artifact import (
    ArtifactCreate,
    ArtifactProducerType,
    artifact_to_read,
    build_artifact_preview,
)
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
    pull_request_record_to_read,
)


def test_artifact_response_hides_storage_and_absolute_paths() -> None:
    """Artifact 响应仅提供 artifact URI，并清理内部路径。"""

    now = datetime.now(UTC)
    artifact_id = uuid4()
    artifact = Artifact(
        id=artifact_id,
        task_id=uuid4(),
        producer_type="system",
        artifact_type="test_report",
        status="available",
        display_name=r"D:\private\report.json",
        media_type="application/json",
        storage_key=f"tasks/{uuid4()}/reports/report.json",
        sha256=f"sha256:{'a' * 64}",
        size_bytes=128,
        summary=r"报告来自 D:\private\report.json",
        metadata_json={
            "workspace_root": r"D:\private",
            "command": ["uv", "run", "pytest"],
            "report_path": r"D:\private\report.json",
        },
        idempotency_key="artifact:test-report:1",
        created_at=now,
        updated_at=now,
    )

    response = artifact_to_read(artifact)

    assert response.uri == f"artifact://{artifact_id}"
    assert "storage_key" not in response.model_dump()
    assert response.display_name == "report.json"
    assert "workspace_root" not in response.metadata_json
    assert response.metadata_json["report_path"] == "<redacted-local-path>"
    assert "<redacted-local-path>" in response.summary


def test_artifact_preview_limits_bytes_and_sanitizes_json() -> None:
    """预览只处理受支持媒体类型，并限制返回字节数。"""

    preview = build_artifact_preview(
        "application/json",
        b'{"workspace_root":"D:\\\\private","result":"ok"}',
    )
    assert preview is not None
    assert preview.kind == "json"
    assert preview.json_value == {"result": "ok"}

    truncated = build_artifact_preview(
        "text/plain",
        b"0123456789",
        max_bytes=5,
    )
    assert truncated is not None
    assert truncated.kind == "text"
    assert truncated.text == "01234"
    assert truncated.truncated is True
    assert truncated.bytes_returned == 5

    assert build_artifact_preview("application/octet-stream", b"binary") is None


def test_artifact_sanitizer_redacts_embedded_paths_without_hiding_uris() -> None:
    """键值文本中的绝对路径必须脱敏，但 artifact/HTTPS URI 保持可用。"""

    preview = build_artifact_preview(
        "text/plain",
        (
            "workspace=D:\\private\\sample "
            "report=/home/cloudhelm/report.json "
            "artifact=artifact://123 "
            "source=https://example.test/docs "
            "route=/api/tasks/123/artifacts "
            "document=/docs/15-detailed-design/08-m6.md"
        ).encode(),
    )

    assert preview is not None
    assert preview.text is not None
    assert "D:\\private" not in preview.text
    assert "/home/cloudhelm" not in preview.text
    assert preview.text.count("<redacted-local-path>") == 2
    assert "artifact://123" in preview.text
    assert "https://example.test/docs" in preview.text
    assert "/api/tasks/123/artifacts" in preview.text
    assert "/docs/15-detailed-design/08-m6.md" in preview.text


def test_artifact_create_rejects_unsafe_storage_and_missing_producer_ref() -> None:
    """内部 Artifact DTO 校验相对 storage key 和生产者引用。"""

    base = {
        "task_id": uuid4(),
        "producer_type": ArtifactProducerType.SYSTEM,
        "artifact_type": "diff_patch",
        "display_name": "diff.patch",
        "media_type": "text/x-diff",
        "storage_key": "tasks/task-id/diff.patch",
        "sha256": f"sha256:{'b' * 64}",
        "size_bytes": 1,
        "summary": "真实 diff",
        "idempotency_key": "artifact:diff:1",
    }
    assert ArtifactCreate.model_validate(base).storage_key == (
        "tasks/task-id/diff.patch"
    )

    with pytest.raises(ValidationError):
        ArtifactCreate.model_validate(
            {**base, "storage_key": r"D:\private\diff.patch"}
        )
    with pytest.raises(ValidationError):
        ArtifactCreate.model_validate(
            {
                **base,
                "producer_type": ArtifactProducerType.TOOL,
                "tool_call_id": None,
            }
        )
    with pytest.raises(ValidationError):
        ArtifactCreate.model_validate(
            {
                **base,
                "producer_type": ArtifactProducerType.SYSTEM,
                "agent_run_id": uuid4(),
            }
        )
    with pytest.raises(ValidationError):
        ArtifactCreate.model_validate(
            {
                **base,
                "producer_type": ArtifactProducerType.AGENT,
                "agent_run_id": uuid4(),
                "tool_call_id": uuid4(),
            }
        )


def test_pull_request_create_rejects_local_url_and_absolute_changed_path() -> None:
    """本地等价 PR 只接受相对 changed files 且不生成远端 URL。"""

    valid = {
        "task_id": uuid4(),
        "project_id": uuid4(),
        "development_plan_id": uuid4(),
        "title": "feat: 本地开发闭环",
        "summary": "真实 diff、测试、评审与安全门禁均通过。",
        "base_branch": "main",
        "head_branch": "feature/m6-demo",
        "base_commit_sha": "a" * 40,
        "commit_sha": "b" * 40,
        "changed_files_json": [{"path": "src/sample_service/main.py"}],
        "diff_artifact_id": uuid4(),
        "test_artifact_id": uuid4(),
        "review_artifact_id": uuid4(),
        "security_artifact_id": uuid4(),
        "idempotency_key": "pr-record:commit-b",
    }
    assert PullRequestRecordCreate.model_validate(valid).url is None

    with pytest.raises(ValidationError):
        PullRequestRecordCreate.model_validate(
            {**valid, "url": "https://example.test/pr/1"}
        )
    with pytest.raises(ValidationError):
        PullRequestRecordCreate.model_validate(
            {
                **valid,
                "changed_files_json": [{"path": r"D:\private\main.py"}],
            }
        )


def test_pull_request_response_sanitizes_historical_changed_paths() -> None:
    """历史异常路径在 PR record 响应中只保留末级文件名。"""

    now = datetime.now(UTC)
    record = PullRequestRecord(
        id=uuid4(),
        task_id=uuid4(),
        project_id=uuid4(),
        development_plan_id=uuid4(),
        provider="local",
        status="open",
        title="本地 PR",
        summary=r"工作区 D:\private\sample 已完成。",
        base_branch="main",
        head_branch="feature/m6-demo",
        base_commit_sha="a" * 40,
        commit_sha="b" * 40,
        changed_files_json=[{"path": r"D:\private\main.py", "change_type": "modified"}],
        diff_stat_json={"workspace_root": r"D:\private", "files": 1},
        diff_artifact_id=uuid4(),
        test_artifact_id=uuid4(),
        review_artifact_id=uuid4(),
        security_artifact_id=uuid4(),
        idempotency_key="pr-record:1",
        created_at=now,
        updated_at=now,
    )

    response = pull_request_record_to_read(record)

    assert response.changed_files_json[0]["path"] == "main.py"
    assert "workspace_root" not in response.diff_stat_json
    assert "<redacted-local-path>" in response.summary
    assert response.url is None


def test_m6_models_register_expected_constraints_and_indexes() -> None:
    """Alembic autogenerate 使用的 ORM metadata 必须包含 M6 约束。"""

    artifacts = Base.metadata.tables["artifacts"]
    records = Base.metadata.tables["pull_request_records"]
    agent_runs = Base.metadata.tables["agent_runs"]
    tool_calls = Base.metadata.tables["tool_calls"]
    conversations = Base.metadata.tables["agent_conversations"]

    artifact_constraint_names = {
        constraint.name for constraint in artifacts.constraints
    }
    record_constraint_names = {
        constraint.name for constraint in records.constraints
    }
    assert "uq_artifacts_task_idempotency" in artifact_constraint_names
    assert "ck_artifacts_sha256" in artifact_constraint_names
    assert "uq_pull_request_records_task_commit" in record_constraint_names
    assert "ck_pull_request_records_local_url" in record_constraint_names
    assert "workflow_step" in agent_runs.c
    assert "attempt" in agent_runs.c
    assert "idempotency_key" in agent_runs.c
    assert "provider_call_id" in tool_calls.c
    assert "provider_item_type" in tool_calls.c
    assert "revision" in conversations.c
