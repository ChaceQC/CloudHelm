"""M6 Git finalize 的 Tester、Reviewer、Security 同轮门禁。"""

from __future__ import annotations

from typing import Any

from cloudhelm_agent_runtime.schemas.review_report import ReviewerAgentOutput
from cloudhelm_agent_runtime.schemas.security_report import SecurityAgentOutput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput

from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_evidence import (
    ImplementationEvidence,
)
from cloudhelm_platform_api.services.local_development_git_utils import (
    gate_error,
)


class LocalDevelopmentGitQualityGate:
    """验证 passed、approved、non-blocking 来自当前 evidence set。"""

    def __init__(self, session) -> None:
        self.agent_runs = AgentRunRepository(session)

    def validate(
        self,
        context: LocalDevelopmentContext,
        implementation: ImplementationEvidence,
        test: Artifact,
        review: Artifact,
        security: Artifact,
    ) -> None:
        """交叉校验质量 AgentRun、结构化输出和 Artifact metadata。"""

        specs = (
            (
                "run_tester",
                "tester_agent_output",
                TesterAgentOutput,
                test,
                "tester_agent_run_id",
            ),
            (
                "run_reviewer",
                "reviewer_agent_output",
                ReviewerAgentOutput,
                review,
                "reviewer_agent_run_id",
            ),
            (
                "run_security",
                "security_agent_output",
                SecurityAgentOutput,
                security,
                "security_agent_run_id",
            ),
        )
        outputs: list[Any] = []
        for step, output_type, model, artifact, run_key in specs:
            run = self.agent_runs.latest_by_workflow_step(
                context.task.id,
                step,
                status="succeeded",
            )
            metadata = artifact.metadata_json
            if (
                run is None
                or run.structured_output_type != output_type
                or run.structured_output_json is None
                or metadata.get(run_key) != str(run.id)
                or metadata.get("coder_agent_run_id")
                != str(implementation.run.id)
            ):
                raise gate_error(
                    "m6_quality_run_mismatch",
                    f"{step} 与当前 evidence set 不一致。",
                )
            output = model.model_validate(run.structured_output_json)
            if (
                output.task_id != context.task.id
                or output.development_plan_id != context.plan.id
            ):
                raise gate_error(
                    "m6_quality_output_mismatch",
                    f"{step} 输出归属无效。",
                )
            outputs.append(output)

        test_output, review_output, security_output = outputs
        if test_output.status != "passed" or test.metadata_json.get(
            "passed"
        ) is not True:
            raise gate_error(
                "m6_test_gate_not_passed",
                "当前测试门禁未通过。",
            )
        if (
            review_output.verdict != "approved"
            or not review_output.proceed_to_security
            or review.metadata_json.get("verdict") != "approved"
        ):
            raise gate_error(
                "m6_review_gate_not_approved",
                "当前 Review 门禁未批准。",
            )
        if (
            security_output.blocking
            or security_output.verdict in {"failed", "blocked"}
            or security.metadata_json.get("blocking") is not False
        ):
            raise gate_error(
                "m6_security_gate_blocked",
                "当前 Security 门禁仍有阻断项。",
            )
