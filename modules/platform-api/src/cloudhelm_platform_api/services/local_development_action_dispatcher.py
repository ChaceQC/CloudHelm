"""M6 状态机动作到角色与分层步骤实现的映射。"""

from cloudhelm_orchestrator.local_development_state_machine import (
    LocalDevelopmentAction,
)

from cloudhelm_platform_api.services.exceptions import ServiceError


class LocalDevelopmentActionDispatcher:
    """集中维护 M6 action/Agent/step 映射，避免主 service 堆积分支。"""

    def __init__(
        self,
        write_steps,
        test_step,
        quality_steps,
        git_step,
    ) -> None:
        self.write_steps = write_steps
        self.test_step = test_step
        self.quality_steps = quality_steps
        self.git_step = git_step

    @staticmethod
    def agent_type(action: LocalDevelopmentAction) -> str:
        """返回单步 claim 使用的普通 Agent 角色。"""

        mapping = {
            LocalDevelopmentAction.RUN_SCAFFOLD: "scaffold",
            LocalDevelopmentAction.RUN_CODER: "coder",
            LocalDevelopmentAction.RUN_TESTER: "tester",
            LocalDevelopmentAction.RUN_REVIEWER: "reviewer",
            LocalDevelopmentAction.RUN_SECURITY: "security",
            LocalDevelopmentAction.FINALIZE_LOCAL_PR: "coder",
        }
        try:
            return mapping[action]
        except KeyError as exc:
            raise ServiceError(
                "local_development_action_unsupported",
                f"不支持的 M6 claim 动作：{action.value}。",
                409,
            ) from exc

    def dispatch(self, context, action: LocalDevelopmentAction):
        """把状态机动作映射到已有分层步骤执行器。"""

        if action == LocalDevelopmentAction.RUN_SCAFFOLD:
            return self.write_steps.run_scaffold(context)
        if action == LocalDevelopmentAction.RUN_CODER:
            return self.write_steps.run_coder(context)
        if action == LocalDevelopmentAction.RUN_TESTER:
            return self.test_step.run(context)
        if action == LocalDevelopmentAction.RUN_REVIEWER:
            return self.quality_steps.run_reviewer(context)
        if action == LocalDevelopmentAction.RUN_SECURITY:
            return self.quality_steps.run_security(context)
        if action == LocalDevelopmentAction.FINALIZE_LOCAL_PR:
            return self.git_step.finalize(context)
        raise ServiceError(
            "local_development_action_unsupported",
            f"不支持的 M6 动作：{action.value}。",
            409,
        )
