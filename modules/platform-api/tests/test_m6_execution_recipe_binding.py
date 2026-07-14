"""M6 execution recipe 调用绑定与失败 conversation 证据测试。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cloudhelm_agent_runtime.providers import (
    ProviderToolCall,
)
from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.tool_call import ToolCall
from cloudhelm_platform_api.services.agent_tool_executor import AgentToolExecutor
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_step_support import (
    LocalDevelopmentStepSupport,
)
from cloudhelm_platform_api.services.provider_tool_turn import (
    OrchestratedToolTurn,
)
from m6_service_fixtures import project_and_task
from cloudhelm_tool_gateway.schemas.tool_call import ToolCallResult, utc_now


def test_agent_executor_persists_and_blocks_unapproved_command(
    client: TestClient,
) -> None:
    """模型即使请求可执行程序，也只能命中当前步骤批准的规范化参数。"""

    settings = get_settings()
    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "recipe-command-block")
        run = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="running",
            workflow_step="run_coder",
            attempt=1,
            idempotency_key=f"m6:run_coder:{task.id}",
        )
        session.add(run)
        session.commit()
        workspace = (
            Path(settings.m6_workspace_root) / str(task.id) / "repo"
        )
        workspace.mkdir(parents=True)
        executor = AgentToolExecutor(
            session,
            client.app.state.tool_gateway,
            settings,
            task_id=task.id,
            agent_run_id=run.id,
            workflow_step="run_coder",
            attempt=1,
            approved_calls=[
                (
                    "sandbox.run_command",
                    {
                        "cwd": ".",
                        "command": ["uv", "--version"],
                        "timeout_seconds": 30,
                    },
                )
            ],
        )

        blocked = executor(
            ProviderToolCall(
                call_id="call-unapproved-python",
                name="sandbox.run_command",
                arguments={
                    "cwd": ".",
                    "command": [
                        "python",
                        "-c",
                        "from pathlib import Path; Path('blocked.txt').write_text('x')",
                    ],
                    "timeout_seconds": 30,
                },
            )
        )

        assert blocked.status == "failed"
        assert (
            blocked.error_code
            == "m6_execution_recipe_call_not_approved"
        )
        assert not (workspace / "blocked.txt").exists()
        assert len(executor.tool_calls) == 1
        record = executor.tool_calls[0]
        assert record.status.value == "failed"
        assert record.audit_json["execution_policy_fingerprint"]
        assert record.audit_json["execution_source"] == "agent_executor"


def test_public_tool_gateway_cannot_bypass_m6_executor(
    client: TestClient,
) -> None:
    """公开 Tool Gateway API 不接受带 M6 workflow identity 的 AgentRun。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "public-m6-bypass")
        run = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="running",
            workflow_step="run_coder",
            attempt=1,
            idempotency_key=f"m6:public-bypass:{task.id}",
        )
        session.add(run)
        session.commit()

    response = client.post(
        f"/api/tasks/{task.id}/tool-gateway/call",
        json={
            "agent_run_id": str(run.id),
            "provider_call_id": "call-public-bypass",
            "provider_item_type": "function_call",
            "tool_name": "sandbox.run_command",
            "risk_level": "L1",
            "idempotency_key": "public-m6-bypass",
            "arguments": {
                "workspace_root": get_settings().m6_workspace_root,
                "cwd": ".",
                "command": ["uv", "--version"],
                "timeout_seconds": 30,
            },
            "reason": "尝试绕过 M6 execution recipe。",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "m6_agent_tool_executor_required"


def test_failed_agent_step_saves_call_output_and_retry_context(
    client: TestClient,
) -> None:
    """失败 AgentRun、ToolCall 与 root conversation 保持同一 call_id 证据。"""

    settings = get_settings()
    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "failed-turn")
        workspace = (
            Path(settings.m6_workspace_root) / str(task.id) / "repo"
        )
        workspace.mkdir(parents=True)
        support = LocalDevelopmentStepSupport(
            session,
            settings,
            client.app.state.tool_gateway,
        )
        context = SimpleNamespace(task=task)
        step = support.begin(
            context,
            agent_type="tester",
            workflow_step="run_tester",
            approved_calls=[],
        )
        call = ProviderToolCall(
            call_id="call-failed-turn",
            name="sandbox.run_command",
            arguments={
                "cwd": ".",
                "command": ["python", "-c", "print('not executed')"],
                "timeout_seconds": 30,
            },
        )
        result = step.executor(call)
        turn = OrchestratedToolTurn(
            agent_type="tester",
            step_name="run_tester",
            step_purpose="验证失败工具证据保存。",
        )
        turn.add(call, result, purpose="执行未批准命令并记录拒绝。")
        turn.commit(step.conversation, summary="Tester 工具步骤失败。")

        with pytest.raises(ServiceError) as exc_info:
            support.fail(
                context,
                step,
                ServiceError(
                    "command_timeout",
                    "模拟后续测试工具超时。",
                    409,
                ),
            )

        assert exc_info.value.code == "command_timeout"
        task_id = task.id
        run_id = step.run.id
        tool_call_id = step.executor.tool_calls[0].id

    with Session(get_engine()) as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.conversation_id is not None
        conversation = session.get(
            AgentConversation,
            run.conversation_id,
        )
        assert conversation is not None
        call_items = [
            item
            for item in conversation.items_json
            if item["type"] in {"function_call", "function_call_output"}
        ]
        assert [item["call_id"] for item in call_items] == [
            "call-failed-turn",
            "call-failed-turn",
        ]
        feedback = next(
            item
            for item in conversation.items_json
            if item["type"] == "message"
            and item["role"] == "developer"
            and "<failed_step_context>" in item["content"][0]["text"]
        )
        payload_text = feedback["content"][0]["text"].splitlines()[1]
        payload = json.loads(payload_text)
        assert payload["agent_run_id"] == str(run_id)
        assert payload["tool_call_ids"] == [str(tool_call_id)]


@pytest.mark.parametrize(
    (
        "agent_type",
        "workflow_step",
        "tool_name",
        "arguments",
        "error_code",
    ),
    (
        (
            "tester",
            "run_tester",
            "test.run_pytest",
            {
                "cwd": ".",
                "pytest_args": ["-q"],
                "junit_path": ".cloudhelm/artifacts/junit.xml",
                "timeout_seconds": 30,
                "max_output_chars": 12000,
            },
            "pytest_timeout",
        ),
        (
            "security",
            "run_security",
            "security.run_bandit",
            {
                "cwd": ".",
                "path": "src",
                "timeout_seconds": 30,
                "max_output_chars": 12000,
            },
            "security_scan_timeout",
        ),
    ),
)
def test_timeout_failure_rebuilds_partial_tool_turn_in_root_conversation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    agent_type: str,
    workflow_step: str,
    tool_name: str,
    arguments: dict,
    error_code: str,
) -> None:
    """pytest/security 超时也要保存配对 call/output 和可重试上下文。"""

    settings = get_settings()
    now = utc_now()

    def failed_tool_result(_request) -> ToolCallResult:
        return ToolCallResult(
            status="failed",
            summary=f"模拟 {error_code}。",
            result_json={"timed_out": True},
            stderr_summary="timeout",
            duration_ms=30000,
            started_at=now,
            finished_at=now,
            error_code=error_code,
            requires_approval=False,
            arguments_summary="timeout fixture",
            audit_json={"status": "failed", "error_code": error_code},
        )

    monkeypatch.setattr(
        client.app.state.tool_gateway,
        "execute",
        failed_tool_result,
    )
    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, f"partial-turn-{agent_type}")
        (
            Path(settings.m6_workspace_root) / str(task.id) / "repo"
        ).mkdir(parents=True)
        support = LocalDevelopmentStepSupport(
            session,
            settings,
            client.app.state.tool_gateway,
        )
        context = SimpleNamespace(task=task)
        step = support.begin(
            context,
            agent_type=agent_type,
            workflow_step=workflow_step,
            approved_calls=[(tool_name, arguments)],
        )
        provider_call_id = f"call-{error_code}"
        result = step.executor(
            ProviderToolCall(
                call_id=provider_call_id,
                name=tool_name,
                arguments=arguments,
            )
        )
        assert result.status == "failed"
        assert result.error_code == error_code

        with pytest.raises(ServiceError) as exc_info:
            support.fail(
                context,
                step,
                ServiceError(
                    error_code,
                    f"模拟 {tool_name} 超时。",
                    409,
                ),
            )

        assert exc_info.value.code == error_code
        run_id = step.run.id
        tool_call_id = step.executor.tool_calls[0].id

    with Session(get_engine()) as session:
        run = session.get(AgentRun, run_id)
        call = session.get(ToolCall, tool_call_id)
        assert run is not None
        assert call is not None
        assert run.status == "failed"
        assert run.error_code == error_code
        assert run.conversation_id is not None
        assert run.conversation_turn is not None
        assert call.status == "failed"
        assert call.error_code == error_code
        conversation = session.get(
            AgentConversation,
            run.conversation_id,
        )
        assert conversation is not None
        assert conversation.source_type == "root"
        call_items = [
            item
            for item in conversation.items_json
            if item["type"] in {"function_call", "function_call_output"}
        ]
        assert [item["call_id"] for item in call_items] == [
            provider_call_id,
            provider_call_id,
        ]
        feedback = next(
            item
            for item in conversation.items_json
            if item["type"] == "message"
            and item["role"] == "developer"
            and "<failed_step_context>" in item["content"][0]["text"]
        )
        payload_text = feedback["content"][0]["text"].splitlines()[1]
        payload = json.loads(payload_text)
        assert payload["agent_run_id"] == str(run_id)
        assert payload["tool_call_ids"] == [str(tool_call_id)]
        assert payload["error_code"] == error_code


def test_cancelled_task_keeps_inflight_tool_call_cancelled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """晚到工具成功结果不得覆盖 Task 取消事务写入的 ToolCall 终态。"""

    settings = get_settings()
    started = Event()
    release = Event()
    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "cancel-inflight-tool")
        run = AgentRun(
            task_id=task.id,
            agent_type="coder",
            status="running",
            workflow_step="run_coder",
            attempt=1,
            idempotency_key=f"m6:cancel-inflight:{task.id}",
        )
        session.add(run)
        session.commit()
        (
            Path(settings.m6_workspace_root) / str(task.id) / "repo"
        ).mkdir(parents=True)
        task_id = task.id
        run_id = run.id

    def delayed_success(request) -> ToolCallResult:
        started.set()
        assert release.wait(timeout=10)
        now = utc_now()
        return ToolCallResult(
            status="succeeded",
            summary="模拟晚到成功结果。",
            result_json={"exit_code": 0},
            duration_ms=1,
            started_at=now,
            finished_at=now,
            requires_approval=False,
            arguments_summary="keys=[command, cwd]",
            audit_json={"status": "succeeded"},
        )

    monkeypatch.setattr(
        client.app.state.tool_gateway,
        "execute",
        delayed_success,
    )

    def execute_call():
        with Session(get_engine(), expire_on_commit=False) as session:
            executor = AgentToolExecutor(
                session,
                client.app.state.tool_gateway,
                settings,
                task_id=task_id,
                agent_run_id=run_id,
                workflow_step="run_coder",
                attempt=1,
                approved_calls=[
                    (
                        "sandbox.run_command",
                        {
                            "cwd": ".",
                            "command": ["uv", "--version"],
                            "timeout_seconds": 30,
                        },
                    )
                ],
            )
            return executor(
                ProviderToolCall(
                    call_id="call-cancel-inflight",
                    name="sandbox.run_command",
                    arguments={
                        "cwd": ".",
                        "command": ["uv", "--version"],
                        "timeout_seconds": 30,
                    },
                )
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute_call)
        assert started.wait(timeout=10)
        cancelled = client.post(f"/api/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        release.set()
        result = future.result(timeout=10)

    assert result.status == "failed"
    assert result.error_code == "task_cancelled"
    with Session(get_engine()) as session:
        run = session.get(AgentRun, run_id)
        call = session.query(ToolCall).filter_by(
            provider_call_id="call-cancel-inflight"
        ).one()
        assert run is not None
        assert run.status == "cancelled"
        assert call.status == "cancelled"
        assert call.error_code == "task_cancelled"
