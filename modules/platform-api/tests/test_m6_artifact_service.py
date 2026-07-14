"""M6 Artifact 生产者引用白盒测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.artifact_storage import sha256
from cloudhelm_platform_api.services.exceptions import ServiceError
from m6_service_fixtures import project_and_task


def test_artifact_service_enforces_exact_producer_reference() -> None:
    """Agent、Tool、System Artifact 只能携带各自允许的审计引用。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        project, task = project_and_task(session, "producer-primary")
        _, other_task = project_and_task(session, "producer-secondary")
        agent_run = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="succeeded",
        )
        other_agent_run = AgentRun(
            task_id=other_task.id,
            agent_type="coder",
            status="succeeded",
        )
        tool_call = ToolCall(
            task_id=task.id,
            tool_name="repo.write_file",
            risk_level="L1",
            arguments_json={},
            audit_json={},
            status="succeeded",
        )
        session.add_all([agent_run, other_agent_run, tool_call])
        session.flush()
        artifacts = ArtifactService(session)

        invalid_cases = (
            (
                ArtifactProducerType.SYSTEM,
                agent_run.id,
                None,
                "system_artifact_reference_invalid",
            ),
            (
                ArtifactProducerType.AGENT,
                agent_run.id,
                tool_call.id,
                "agent_artifact_reference_invalid",
            ),
            (
                ArtifactProducerType.TOOL,
                agent_run.id,
                tool_call.id,
                "tool_artifact_reference_invalid",
            ),
            (
                ArtifactProducerType.AGENT,
                other_agent_run.id,
                None,
                "agent_run_task_mismatch",
            ),
        )
        for index, (
            producer_type,
            agent_run_id,
            tool_call_id,
            error_code,
        ) in enumerate(invalid_cases, start=1):
            with pytest.raises(ServiceError) as exc_info:
                artifacts.create_text(
                    task_id=task.id,
                    artifact_type="test_evidence",
                    display_name=f"invalid-{index}.txt",
                    content="invalid",
                    producer_type=producer_type,
                    summary="非法生产者引用。",
                    metadata_json={},
                    idempotency_key=f"invalid:{index}",
                    agent_run_id=agent_run_id,
                    tool_call_id=tool_call_id,
                )
            assert exc_info.value.code == error_code

        agent_artifact = artifacts.create_text(
            task_id=task.id,
            artifact_type="review_report",
            display_name="agent.txt",
            content="agent evidence",
            producer_type=ArtifactProducerType.AGENT,
            summary="Agent 证据。",
            metadata_json={},
            idempotency_key="valid:agent",
            agent_run_id=agent_run.id,
        )
        tool_artifact = artifacts.create_text(
            task_id=task.id,
            artifact_type="diff_patch",
            display_name="tool.patch",
            content="tool evidence",
            producer_type=ArtifactProducerType.TOOL,
            summary="Tool 证据。",
            metadata_json={},
            idempotency_key="valid:tool",
            tool_call_id=tool_call.id,
            media_type="text/x-diff",
        )

        assert agent_artifact.agent_run_id == agent_run.id
        assert agent_artifact.tool_call_id is None
        assert tool_artifact.tool_call_id == tool_call.id
        assert tool_artifact.agent_run_id is None
        assert project.id == task.project_id


def test_artifact_idempotency_compares_the_complete_contract() -> None:
    """相同内容也不能用同一幂等键静默替换 Artifact 契约。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "artifact-identity")
        agent_run = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="succeeded",
        )
        session.add(agent_run)
        session.flush()
        artifacts = ArtifactService(session)
        base = {
            "task_id": task.id,
            "artifact_type": "diff_patch",
            "display_name": "changes.patch",
            "content": "same bytes",
            "producer_type": ArtifactProducerType.SYSTEM,
            "summary": "同一摘要。",
            "metadata_json": {
                "cycle": "1",
                "workspace_root": r"D:\private\one",
            },
            "media_type": "text/x-diff",
        }
        conflict_cases = (
            {
                "producer_type": ArtifactProducerType.AGENT,
                "agent_run_id": agent_run.id,
            },
            {"display_name": "other.patch"},
            {"media_type": "text/plain"},
            {"summary": "不同摘要。"},
            {"metadata_json": {"cycle": "2"}},
        )
        for index, overrides in enumerate(conflict_cases, start=1):
            idempotency_key = f"identity:{index}"
            artifacts.create_text(
                **base,
                idempotency_key=idempotency_key,
            )
            with pytest.raises(ServiceError) as exc_info:
                artifacts.create_text(
                    **{**base, **overrides},
                    idempotency_key=idempotency_key,
                )
            assert exc_info.value.code == "artifact_idempotency_conflict"

        original = artifacts.create_text(
            **base,
            idempotency_key="identity:sanitized-metadata",
        )
        reused = artifacts.create_text(
            **{
                **base,
                "metadata_json": {
                    "cycle": "1",
                    "workspace_root": r"C:\private\two",
                },
            },
            idempotency_key="identity:sanitized-metadata",
        )
        assert reused.id == original.id


def test_git_patch_artifacts_preserve_raw_bytes_and_safe_preview(
    tmp_path: Path,
) -> None:
    """diff/format-patch 原文可应用，API 预览单独遮蔽凭据与绝对路径。"""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "CloudHelm Test")
    _git(repo, "config", "user.email", "cloudhelm@example.test")
    source = repo / "config.py"
    source.write_text(
        "def build_config("
        "password: str, token: str, secret: str"
        ") -> dict[str, str]:\n"
        '    data_root = "/var/lib/cloudhelm"\n'
        '    return {"version": "1"}\n',
        encoding="utf-8",
    )
    _git(repo, "add", "config.py")
    _git(repo, "commit", "-m", "chore: baseline")
    base_commit = _git(repo, "rev-parse", "HEAD").strip()

    source.write_text(
        "def build_config("
        "password: str, token: str, secret: str"
        ") -> dict[str, str]:\n"
        '    data_root = "/var/lib/cloudhelm"\n'
        '    return {"version": "2"}\n',
        encoding="utf-8",
    )
    diff_patch = _git(repo, "diff", "--no-ext-diff", "--binary")
    _git(repo, "add", "config.py")
    _git(repo, "commit", "-m", "feat: update config")
    format_patch = _git(
        repo,
        "format-patch",
        "--stdout",
        f"{base_commit}..HEAD",
    )
    _git(repo, "reset", "--hard", base_commit)

    settings = Settings(artifact_root=str(tmp_path / "artifacts"))
    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "artifact-lossless-patch")
        artifacts = ArtifactService(session, settings)
        cases = (
            ("diff_patch", "implementation.diff", diff_patch),
            ("format_patch", "implementation.patch", format_patch),
        )
        for artifact_type, display_name, patch_text in cases:
            artifact = artifacts.create_text(
                task_id=task.id,
                artifact_type=artifact_type,
                display_name=display_name,
                content=patch_text,
                producer_type=ArtifactProducerType.SYSTEM,
                summary=f"{artifact_type} 完整性回归。",
                metadata_json={},
                idempotency_key=f"lossless:{artifact_type}",
                media_type="text/x-diff",
            )
            stored = artifacts.storage.read_verified(
                artifact.storage_key,
                artifact.sha256,
                artifact.size_bytes,
            )
            assert stored == patch_text.encode("utf-8")
            assert artifact.sha256 == sha256(patch_text.encode("utf-8"))

            detail = artifacts.get_detail(artifact.id)
            assert detail.preview is not None
            assert detail.preview.text is not None
            assert "password: str" not in detail.preview.text
            assert "token: str" not in detail.preview.text
            assert "secret: str" not in detail.preview.text
            assert "<redacted>" in detail.preview.text
            assert "<redacted-local-path>" in detail.preview.text

            checked = subprocess.run(
                [
                    "git",
                    "apply",
                    "--check",
                    str(artifacts.storage.resolve(artifact.storage_key)),
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            assert checked.returncode == 0, checked.stderr


def _git(repo: Path, *arguments: str) -> str:
    """在 UTF-8 测试仓库执行 Git 并返回 stdout。"""

    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout
