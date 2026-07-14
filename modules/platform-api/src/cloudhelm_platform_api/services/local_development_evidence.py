"""M6 同一 rework cycle 的真实证据解析与一致性校验。"""

from dataclasses import dataclass

from cloudhelm_agent_runtime.schemas.implementation import CoderAgentOutput
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentOutput

from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)


@dataclass(frozen=True, slots=True)
class ImplementationEvidence:
    """Coder 成功输出及其非空 diff Artifact。"""

    run: AgentRun
    output: CoderAgentOutput
    diff_artifact: Artifact
    evidence_set_id: str


class LocalDevelopmentEvidenceResolver:
    """禁止把不同 Coder attempt/recipe/plan 的 latest Artifact 拼接。"""

    def __init__(self, session) -> None:
        self.agent_runs = AgentRunRepository(session)
        self.artifacts = ArtifactRepository(session)

    def implementation(
        self,
        context: LocalDevelopmentContext,
    ) -> ImplementationEvidence:
        """读取当前成功 Coder run 和与其绑定的 diff。"""

        run = self.agent_runs.latest_by_workflow_step(
            context.task.id,
            "run_coder",
            status="succeeded",
        )
        if (
            run is None
            or run.structured_output_json is None
            or run.structured_output_type != "coder_agent_output"
        ):
            raise ServiceError(
                "m6_coder_evidence_missing",
                "缺少当前 M6 Coder 成功输出。",
                409,
            )
        output = CoderAgentOutput.model_validate(
            run.structured_output_json
        )
        if (
            output.task_id != context.task.id
            or output.development_plan_id != context.plan.id
        ):
            raise ServiceError(
                "m6_coder_output_mismatch",
                "Coder 输出不属于当前 Task/DevelopmentPlan。",
                409,
            )
        if output.status != "completed":
            raise ServiceError(
                "m6_coder_not_completed",
                "当前 Coder 输出尚未完成。",
                409,
            )
        diff = self.artifacts.get_by_task_idempotency_key(
            context.task.id,
            f"m6:diff:{run.id}",
        )
        if diff is None or diff.status != "available":
            raise ServiceError(
                "m6_diff_artifact_missing",
                "缺少当前 Coder 的真实 diff Artifact。",
                409,
            )
        metadata = diff.metadata_json
        evidence_set_id = metadata.get("evidence_set_id")
        expected = f"m6:{context.plan.id}:{run.id}"
        if (
            evidence_set_id != expected
            or metadata.get("development_plan_id") != str(context.plan.id)
            or metadata.get("recipe_sha256") != context.recipe_sha256
            or metadata.get("coder_agent_run_id") != str(run.id)
        ):
            raise ServiceError(
                "m6_diff_evidence_mismatch",
                "diff Artifact 不属于当前 plan/recipe/Coder cycle。",
                409,
            )
        return ImplementationEvidence(
            run=run,
            output=output,
            diff_artifact=diff,
            evidence_set_id=expected,
        )

    def test_output(
        self,
        context: LocalDevelopmentContext,
        evidence_set_id: str,
    ) -> tuple[TesterAgentOutput, Artifact]:
        """读取同一 evidence set 的 Tester 输出与报告。"""

        run = self.agent_runs.latest_by_workflow_step(
            context.task.id,
            "run_tester",
            status="succeeded",
        )
        if (
            run is None
            or run.structured_output_json is None
            or run.structured_output_type != "tester_agent_output"
        ):
            raise ServiceError(
                "m6_test_evidence_missing",
                "缺少当前 Tester 输出。",
                409,
            )
        output = TesterAgentOutput.model_validate(
            run.structured_output_json
        )
        if (
            output.task_id != context.task.id
            or output.development_plan_id != context.plan.id
        ):
            raise ServiceError(
                "m6_test_output_mismatch",
                "Tester 输出不属于当前 Task/DevelopmentPlan。",
                409,
            )
        artifact = self.artifacts.get_by_task_idempotency_key(
            context.task.id,
            f"m6:test-report:{run.id}",
        )
        if artifact is None or artifact.status != "available":
            raise ServiceError(
                "m6_test_report_missing",
                "缺少当前 Tester run 的 TestReport Artifact。",
                409,
            )
        metadata = artifact.metadata_json
        if (
            metadata.get("evidence_set_id") != evidence_set_id
            or metadata.get("development_plan_id") != str(context.plan.id)
            or metadata.get("recipe_sha256") != context.recipe_sha256
            or metadata.get("tester_agent_run_id") != str(run.id)
        ):
            raise ServiceError(
                "m6_test_evidence_mismatch",
                "TestReport 不属于当前 Tester/rework cycle。",
                409,
            )
        return output, artifact

    def required_artifact(
        self,
        context: LocalDevelopmentContext,
        artifact_type: str,
        evidence_set_id: str,
    ) -> Artifact:
        """读取并校验同一 plan/recipe/evidence set 的门禁 Artifact。"""

        artifact = self.artifacts.latest_by_task_and_type(
            context.task.id,
            artifact_type,
            status="available",
        )
        if artifact is None:
            raise ServiceError(
                "m6_gate_artifact_missing",
                f"缺少 M6 门禁 Artifact：{artifact_type}。",
                409,
            )
        metadata = artifact.metadata_json
        if (
            metadata.get("evidence_set_id") != evidence_set_id
            or metadata.get("development_plan_id") != str(context.plan.id)
            or metadata.get("recipe_sha256") != context.recipe_sha256
        ):
            raise ServiceError(
                "m6_gate_evidence_mismatch",
                f"{artifact_type} 不属于当前 rework cycle。",
                409,
            )
        return artifact
