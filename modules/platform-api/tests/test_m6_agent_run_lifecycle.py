"""M6 AgentRun 基础设施失败分类白盒测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import get_settings
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.services.agent_run_lifecycle import (
    AgentRunLifecycle,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from m6_service_fixtures import project_and_task


def test_recoverable_m6_failure_pauses_task_and_preserves_phase() -> None:
    """超时、CLI 缺失或 revision 冲突应暂停而非终结 Task。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "recoverable-lifecycle")
        task.current_phase = "Testing"
        lifecycle = AgentRunLifecycle(session, get_settings())
        run = lifecycle.start(
            task,
            "tester",
            workflow_step="run_tester",
        )
        session.commit()

        with pytest.raises(ServiceError) as exc_info:
            lifecycle.fail(
                task,
                run,
                ServiceError(
                    "command_timeout",
                    "pytest 执行超时。",
                    409,
                ),
            )

        assert exc_info.value.code == "command_timeout"
        assert run.status == "failed"
        assert task.status == "paused"
        assert task.current_phase == "Testing"


def test_unclassified_m6_failure_marks_task_failed() -> None:
    """未进入可恢复映射的实现异常保持失败终态语义。"""

    with Session(get_engine(), expire_on_commit=False) as session:
        _, task = project_and_task(session, "fatal-lifecycle")
        task.current_phase = "Implementing"
        lifecycle = AgentRunLifecycle(session, get_settings())
        run = lifecycle.start(
            task,
            "coder",
            workflow_step="run_coder",
        )
        session.commit()

        with pytest.raises(ServiceError) as exc_info:
            lifecycle.fail(
                task,
                run,
                RuntimeError("unexpected implementation failure"),
            )

        assert exc_info.value.code == "agent_output_validation_failed"
        assert run.status == "failed"
        assert task.status == "failed"
        assert task.current_phase == "Implementing"
