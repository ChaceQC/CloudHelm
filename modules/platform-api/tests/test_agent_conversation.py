"""Task root 与显式 subagent conversation 集成测试。"""

import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.services.agent_conversation_service import (
    AgentConversationService,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from conftest import create_project, create_running_agent_run, create_task


def test_normal_agent_roles_share_one_task_root_conversation(
    client: TestClient,
) -> None:
    """Requirement/Architect/Planner 必须是同一 root thread 的连续 turn。"""

    project = create_project(client, "会话连续性项目")
    task = create_task(client, project["id"], title="验证主会话连续性")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200

    requirement_step = client.post(f"/api/tasks/{task['id']}/run-next")
    assert requirement_step.status_code == 200, requirement_step.text
    assert _root_revision(task["id"]) == 1
    design_step = client.post(f"/api/tasks/{task['id']}/run-next")
    assert design_step.status_code == 200, design_step.text
    assert _root_revision(task["id"]) == 2
    assert client.post(
        f"/api/technical-designs/{design_step.json()['technical_design']['id']}/approve",
        json={"actor_id": "architect", "reason": "设计已人工确认"},
    ).status_code == 200
    assert _root_revision(task["id"]) == 3
    plan_step = client.post(f"/api/tasks/{task['id']}/run-next")
    assert plan_step.status_code == 200, plan_step.text
    assert _root_revision(task["id"]) == 4
    assert client.post(
        f"/api/approvals/{plan_step.json()['approval']['id']}/approve",
        json={"actor_id": "reviewer", "reason": "计划已人工确认"},
    ).status_code == 200
    assert _root_revision(task["id"]) == 5

    runs = client.get(f"/api/tasks/{task['id']}/agent-runs").json()["items"]
    ordered_runs = sorted(runs, key=lambda item: item["conversation_turn"])
    assert [run["agent_type"] for run in ordered_runs] == [
        "requirement",
        "architect",
        "planner",
    ]
    assert [run["conversation_turn"] for run in ordered_runs] == [1, 2, 3]
    assert len({run["conversation_id"] for run in runs}) == 1
    assert all(run["cached_input_tokens"] == 0 for run in runs)
    assert all(run["provider_request_count"] == 0 for run in runs)
    assert all(run["provider_requests"] == [] for run in runs)

    with Session(get_engine()) as session:
        conversations = list(
            session.scalars(
                select(AgentConversation).where(
                    AgentConversation.task_id == UUID(task["id"])
                )
            )
        )
        assert len(conversations) == 1
        root = conversations[0]
        assert root.source_type == "root"
        assert root.parent_conversation_id is None
        assert root.agent_role is None
        assert root.turn_count == 3
        assert root.revision == 5
        assert root.prompt_cache_key.startswith("cloudhelm:")
        serialized = json.dumps(root.items_json, ensure_ascii=False)
        assert "Requirement Agent Role Instructions v3" in serialized
        assert "Architect Agent Role Instructions v3" in serialized
        assert "Planner Agent Role Instructions v3" in serialized
        assert serialized.count("<approval_context>") == 2

    event_types = [
        event["event_type"]
        for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    ]
    assert event_types.count("AgentConversationCreated") == 1


def test_only_explicit_spawn_creates_child_and_completion_notifies_parent(
    client: TestClient,
) -> None:
    """显式 spawn 才能创建 child；完成后只回传通知而不增加父 turn。"""

    project = create_project(client, "子 Agent 管理项目")
    task = create_task(client, project["id"], title="验证子 Agent 生命周期")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next").status_code == 200
    root_id = _root_id(task["id"])
    spawning_run = create_running_agent_run(
        task["id"],
        "planner",
        conversation_id=root_id,
    )

    with Session(get_engine()) as session:
        settings = get_settings()
        assert settings.agent_max_subagent_depth == 1
        assert settings.agent_max_subagent_threads == 6
        service = AgentConversationService(session, settings)
        root = session.scalar(
            select(AgentConversation).where(
                AgentConversation.task_id == UUID(task["id"]),
                AgentConversation.source_type == "root",
            )
        )
        assert root is not None
        parent_turn_count = root.turn_count
        parent_revision = root.revision

        with pytest.raises(ServiceError) as role_error:
            service.spawn_subagent(
                parent_conversation_id=root.id,
                agent_role="coder",
                nickname=None,
                objective="修改共享 workspace 中的生产代码。",
                expected_result="完成代码修改并返回摘要。",
                spawned_by_agent_run_id=UUID(spawning_run["id"]),
                fork_context=False,
            )
        assert role_error.value.code == "subagent_role_not_allowed"
        assert role_error.value.detail == {"agent_role": "coder"}

        child, provider_conversation = service.spawn_subagent(
            parent_conversation_id=root.id,
            agent_role="reviewer",
            nickname="Atlas",
            objective="只审查当前 Requirement 输出是否满足结构化契约和风险边界。",
            expected_result="结构化 review 结论和阻断问题列表。",
            spawned_by_agent_run_id=UUID(spawning_run["id"]),
            fork_context=False,
        )
        session.commit()

        assert child.source_type == "subagent"
        assert child.parent_conversation_id == root.id
        assert child.depth == 1
        assert child.fork_mode == "fresh"
        assert child.status == "active"
        assert child.revision == 0
        assert root.revision == parent_revision
        assert child.objective == "只审查当前 Requirement 输出是否满足结构化契约和风险边界。"
        assert provider_conversation.source_type == "subagent"
        assert provider_conversation.parent_conversation_id == str(root.id)
        assert len(child.items_json) == 2
        child_context = json.dumps(
            child.items_json,
            ensure_ascii=False,
        )
        child_instruction_text = child.items_json[0]["content"][0]["text"]
        assert "CloudHelm Subagent Role Instructions" in child_context
        assert "<subagent_task>" in child_context
        assert "只审查当前 Requirement 输出" in child_context
        assert '"parent_agent_type": "planner"' in child_instruction_text
        assert (
            '"effective_allowed_tools": ["repo.list_files", "repo.read_file", '
            '"repo.search_text"]'
            in child_instruction_text
        )
        assert '"git.diff"' not in child_instruction_text

        mismatched_run = create_running_agent_run(
            task["id"],
            "reviewer",
            conversation_id=str(child.id),
        )

        with pytest.raises(ServiceError) as nested_error:
            service.spawn_subagent(
                parent_conversation_id=child.id,
                agent_role="reviewer",
                nickname=None,
                objective="继续递归探索。",
                expected_result="探索摘要。",
                spawned_by_agent_run_id=UUID(spawning_run["id"]),
                fork_context=False,
            )
        assert nested_error.value.code == "subagent_depth_limit_exceeded"

        with pytest.raises(ServiceError) as conversation_error:
            service.spawn_subagent(
                parent_conversation_id=root.id,
                agent_role="tester",
                nickname=None,
                objective="核验测试证据是否覆盖当前验收标准。",
                expected_result="测试覆盖缺口和证据引用。",
                spawned_by_agent_run_id=UUID(mismatched_run["id"]),
                fork_context=False,
            )
        assert (
            conversation_error.value.code
            == "spawning_agent_run_conversation_mismatch"
        )

        with pytest.raises(ServiceError) as empty_summary:
            service.complete_subagent(
                child.id,
                status="completed",
                summary=" ",
            )
        assert empty_summary.value.code == "invalid_subagent_summary"

        with pytest.raises(ServiceError) as long_summary:
            service.complete_subagent(
                child.id,
                status="completed",
                summary="x" * 4001,
            )
        assert long_summary.value.code == "subagent_summary_too_long"

        with pytest.raises(ServiceError) as active_run_error:
            service.complete_subagent(
                child.id,
                status="completed",
                summary="仍有 active AgentRun 时不得结束 child。",
            )
        assert active_run_error.value.code == "subagent_agent_run_active"
        active_child_run = session.get(AgentRun, UUID(mismatched_run["id"]))
        assert active_child_run is not None
        active_child_run.status = "succeeded"
        session.flush()

        service.complete_subagent(
            child.id,
            status="completed",
            summary=(
                "审查完成，未发现阻断问题；"
                "token=secret-subagent-summary-value"
            ),
        )
        session.commit()
        session.refresh(root)
        session.refresh(child)

        assert child.status == "completed"
        assert child.completed_at is not None
        assert child.revision == 1
        assert root.turn_count == parent_turn_count
        assert root.revision == parent_revision + 1
        parent_text = json.dumps(root.items_json, ensure_ascii=False)
        assert "<subagent_notification>" in parent_text
        assert str(child.id) in parent_text
        assert "审查完成，未发现阻断问题" in parent_text
        assert "secret-subagent-summary-value" not in parent_text
        assert "token=<redacted>" in parent_text

    event_types = [
        event["event_type"]
        for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    ]
    assert "SubagentSpawned" in event_types
    assert "SubagentCompleted" in event_types


def test_late_step_failure_rolls_back_artifact_and_conversation_turn(
    client: TestClient,
    monkeypatch,
) -> None:
    """步骤末尾失败时只保留失败 AgentRun，不得提交半成品或会话 turn。"""

    project = create_project(client, "会话事务回滚项目")
    task = create_task(client, project["id"], title="验证 Agent 步骤原子性")
    assert client.post(f"/api/tasks/{task['id']}/start").status_code == 200

    original_record = EventService.record

    def fail_requirement_created(self, event_type, *args, **kwargs):  # noqa: ANN001
        if event_type == "RequirementSpecCreated":
            raise RuntimeError("late event persistence failure")
        return original_record(self, event_type, *args, **kwargs)

    monkeypatch.setattr(EventService, "record", fail_requirement_created)
    response = client.post(f"/api/tasks/{task['id']}/run-next")

    assert response.status_code == 500
    assert response.json()["code"] == "agent_output_validation_failed"

    with Session(get_engine()) as session:
        task_id = UUID(task["id"])
        conversations = list(
            session.scalars(
                select(AgentConversation).where(
                    AgentConversation.task_id == task_id
                )
            )
        )
        requirements = list(
            session.scalars(
                select(RequirementSpec).where(
                    RequirementSpec.task_id == task_id
                )
            )
        )
        runs = list(
            session.scalars(
                select(AgentRun).where(AgentRun.task_id == task_id)
            )
        )

    assert conversations == []
    assert requirements == []
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].conversation_id is None
    assert runs[0].conversation_turn is None

    event_types = [
        event["event_type"]
        for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]
    ]
    assert event_types == ["TaskCreated", "TaskPhaseChanged", "AgentRunStarted", "AgentRunFailed"]


def _root_id(task_id: str) -> str:
    """读取 Task root conversation ID。"""

    with Session(get_engine()) as session:
        conversation_id = session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.task_id == UUID(task_id),
                AgentConversation.source_type == "root",
            )
        )
    assert conversation_id is not None
    return str(conversation_id)


def _root_revision(task_id: str) -> int:
    """读取 Task root conversation 当前乐观并发版本。"""

    with Session(get_engine()) as session:
        revision = session.scalar(
            select(AgentConversation.revision).where(
                AgentConversation.task_id == UUID(task_id),
                AgentConversation.source_type == "root",
            )
        )
    assert revision is not None
    return revision
