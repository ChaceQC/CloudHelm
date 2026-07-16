"""Workflow Engine 配置黑盒/白盒测试。"""

import pytest
from pydantic import ValidationError

from cloudhelm_workflow_engine.config import WorkflowSettings


def test_default_settings_satisfy_frozen_m7_values() -> None:
    """默认值与 M7-2C 设计表一致，连接串不进入 repr。"""

    settings = WorkflowSettings()

    assert settings.queue_name == "cloudhelm.workflow"
    assert settings.maintenance_queue_name == "cloudhelm.workflow.maintenance"
    assert settings.job_lease_seconds == 90
    assert settings.job_heartbeat_seconds == 20
    assert settings.dispatch_lease_seconds == 15
    assert settings.redispatch_after_seconds == 60
    assert settings.visibility_timeout_seconds == 1800
    rendered = repr(settings)
    assert "cloudhelm_dev" not in rendered
    assert "redis://" not in rendered


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"job_lease_seconds": 40, "job_heartbeat_seconds": 20},
            r"2 \* heartbeat",
        ),
        (
            {
                "dispatch_lease_seconds": 10,
                "broker_publish_timeout_seconds": 5,
            },
            r"2 \* publish timeout",
        ),
        (
            {
                "soft_time_limit_seconds": 900,
                "hard_time_limit_seconds": 900,
            },
            "soft < hard",
        ),
        (
            {
                "hard_time_limit_seconds": 1700,
                "visibility_timeout_seconds": 1750,
            },
            "visibility",
        ),
        (
            {
                "queue_name": "cloudhelm.workflow",
                "maintenance_queue_name": "cloudhelm.workflow",
            },
            "必须不同",
        ),
    ],
)
def test_invalid_time_invariants_fail_startup(
    overrides: dict[str, object],
    message: str,
) -> None:
    """所有 lease/timeout 冲突在进程启动前失败。"""

    with pytest.raises(ValidationError, match=message):
        WorkflowSettings(**overrides)
