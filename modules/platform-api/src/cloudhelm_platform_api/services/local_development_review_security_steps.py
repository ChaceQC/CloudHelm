"""M6 Reviewer 与 Security 同 cycle 门禁步骤。"""

from cloudhelm_agent_runtime.agents import ReviewerAgent, SecurityAgent
from cloudhelm_tool_gateway import ToolGateway
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_evidence import (
    LocalDevelopmentEvidenceResolver,
)
from cloudhelm_platform_api.services.local_development_quality_inputs import (
    build_reviewer_input,
    build_security_input,
)
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)
from cloudhelm_platform_api.services.local_development_step_support import (
    LocalDevelopmentStepSupport,
)
from cloudhelm_platform_api.services.local_development_tool_policy import (
    reviewer_tool_calls,
    security_tool_calls,
)


class LocalDevelopmentReviewSecuritySteps:
    """基于真实 diff/test 运行 Reviewer 和本地安全扫描。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        gateway: ToolGateway,
    ) -> None:
        self.session = session
        self.support = LocalDevelopmentStepSupport(
            session,
            settings,
            gateway,
        )
        self.artifacts = ArtifactService(session, settings)
        self.evidence = LocalDevelopmentEvidenceResolver(session)
        self.events = EventService(session)

    def run_reviewer(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """映射全部 AC；未批准时回到 Implementing。"""

        implementation = self.evidence.implementation(context)
        test_output, test_artifact = self.evidence.test_output(
            context,
            implementation.evidence_set_id,
        )
        junit_artifact = self.evidence.required_artifact(
            context,
            "junit_xml",
            implementation.evidence_set_id,
        )
        step = self.support.begin(
            context,
            agent_type="reviewer",
            workflow_step="run_reviewer",
            approved_calls=reviewer_tool_calls(
                implementation.output.diff_paths
            ),
        )
        created_artifacts = []
        try:
            evidence_refs = [
                f"artifact://{implementation.diff_artifact.id}",
                f"artifact://{test_artifact.id}",
                f"artifact://{junit_artifact.id}",
            ]
            output = ReviewerAgent(step.provider).run(
                build_reviewer_input(
                    context,
                    implementation,
                    test_output,
                    evidence_refs,
                ),
                conversation=step.conversation,
                tools=step.tools,
                tool_executor=step.executor,
            )
            self.support.raise_for_infrastructure(output)
            report = self.artifacts.create_json(
                task_id=context.task.id,
                artifact_type="review_report",
                display_name="review-report.json",
                content=output.model_dump(mode="json"),
                producer_type=ArtifactProducerType.AGENT,
                summary=output.summary,
                metadata_json={
                    "development_plan_id": str(context.plan.id),
                    "recipe_sha256": context.recipe_sha256,
                    "evidence_set_id": implementation.evidence_set_id,
                    "coder_agent_run_id": str(implementation.run.id),
                    "reviewer_agent_run_id": str(step.run.id),
                    "verdict": output.verdict,
                },
                idempotency_key=f"m6:review-report:{step.run.id}",
                agent_run_id=step.run.id,
            )
            created_artifacts.append(report)
            self.support.complete(
                step,
                output,
                output_type="reviewer_agent_output",
            )
            self.events.record(
                "ReviewCompleted",
                "agent",
                str(step.run.id),
                {
                    "review_artifact_id": str(report.id),
                    "verdict": output.verdict,
                    "issue_count": len(output.issues),
                },
                context.task.id,
            )
            return LocalDevelopmentResult(
                action="run_reviewer",
                message=output.summary,
                target_phase=(
                    "SecurityScanning"
                    if output.verdict == "approved"
                    else "Implementing"
                ),
                agent_run=step.run,
                tool_calls=step.executor.tool_calls,
                artifacts=[report],
                gate_evidence={
                    "evidence_set_id": implementation.evidence_set_id,
                    "verdict": output.verdict,
                    "acceptance_results": [
                        item.model_dump(mode="json")
                        for item in output.acceptance_results
                    ],
                },
            )
        except Exception as exc:
            self.artifacts.delete_uncommitted_content(created_artifacts)
            self.support.fail(context, step, exc)
            raise

    def run_security(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """运行 Bandit/pip-audit；阻断发现回到 Implementing。"""

        implementation = self.evidence.implementation(context)
        review_artifact = self.evidence.required_artifact(
            context,
            "review_report",
            implementation.evidence_set_id,
        )
        if review_artifact.metadata_json.get("verdict") != "approved":
            raise ServiceError(
                "m6_review_gate_not_approved",
                "Review 未通过，不能进入 Security。",
                409,
            )
        step = self.support.begin(
            context,
            agent_type="security",
            workflow_step="run_security",
            approved_calls=security_tool_calls(context),
        )
        created_artifacts = []
        try:
            output = SecurityAgent(step.provider).run(
                build_security_input(context, implementation),
                conversation=step.conversation,
                tools=step.tools,
                tool_executor=step.executor,
            )
            self.support.raise_for_infrastructure(output)
            report = self.artifacts.create_json(
                task_id=context.task.id,
                artifact_type="security_report",
                display_name="security-report.json",
                content=output.model_dump(mode="json"),
                producer_type=ArtifactProducerType.AGENT,
                summary=output.summary,
                metadata_json={
                    "development_plan_id": str(context.plan.id),
                    "recipe_sha256": context.recipe_sha256,
                    "evidence_set_id": implementation.evidence_set_id,
                    "coder_agent_run_id": str(implementation.run.id),
                    "security_agent_run_id": str(step.run.id),
                    "verdict": output.verdict,
                    "blocking": output.blocking,
                    "finding_count": len(output.findings),
                },
                idempotency_key=f"m6:security-report:{step.run.id}",
                agent_run_id=step.run.id,
            )
            created_artifacts.append(report)
            self.support.complete(
                step,
                output,
                output_type="security_agent_output",
            )
            self.events.record(
                (
                    "SecurityScanBlocked"
                    if output.blocking
                    else "SecurityScanCompleted"
                ),
                "agent",
                str(step.run.id),
                {
                    "security_artifact_id": str(report.id),
                    "verdict": output.verdict,
                    "blocking": output.blocking,
                    "finding_count": len(output.findings),
                },
                context.task.id,
            )
            return LocalDevelopmentResult(
                action="run_security",
                message=output.summary,
                target_phase=(
                    "Implementing"
                    if output.blocking
                    else "ReadyForPR"
                ),
                agent_run=step.run,
                tool_calls=step.executor.tool_calls,
                artifacts=[report],
                gate_evidence={
                    "evidence_set_id": implementation.evidence_set_id,
                    "verdict": output.verdict,
                    "blocking": output.blocking,
                    "findings": len(output.findings),
                },
            )
        except Exception as exc:
            self.artifacts.delete_uncommitted_content(created_artifacts)
            self.support.fail(context, step, exc)
            raise
