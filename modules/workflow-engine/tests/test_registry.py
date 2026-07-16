"""Workflow handler registry 与副作用分类白盒测试。"""

from uuid import uuid4

import pytest

from cloudhelm_workflow_engine.registry import (
    HandlerRegistration,
    HandlerRegistry,
)


class NoopHandler:
    """仅用于验证 registry 结构，不进入生产 worker。"""

    def execute(self, *, workflow_job_id, worker_owner):
        """返回输入用于测试注册对象可被读取。"""

        return workflow_job_id, worker_owner


@pytest.mark.parametrize(
    "side_effect_class",
    ("none", "external_idempotent", "external_uncertain"),
)
def test_registry_accepts_frozen_side_effect_classes(
    side_effect_class: str,
) -> None:
    """三类冻结副作用均可表达，但是否注册由 worker factory 决定。"""

    registration = HandlerRegistration(
        job_type=f"test_{side_effect_class}",
        resource_type="test_resource",
        side_effect_class=side_effect_class,
        handler=NoopHandler(),
    )
    registry = HandlerRegistry([registration])

    assert registry.get(registration.job_type) is registration
    assert registration.handler.execute(
        workflow_job_id=uuid4(),
        worker_owner="worker:test",
    )


def test_registry_rejects_unknown_side_effect_class() -> None:
    """未知分类不得绕过 stale fail-closed 策略。"""

    with pytest.raises(
        ValueError,
        match="side_effect_class",
    ):
        HandlerRegistration(
            job_type="invalid",
            resource_type="test_resource",
            side_effect_class="external_best_effort",
            handler=NoopHandler(),
        )
