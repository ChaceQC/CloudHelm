"""M6 Tester 真实 pytest/JUnit 步骤。"""

from cloudhelm_agent_runtime.agents import TesterAgent
from cloudhelm_agent_runtime.schemas.agent_io import (
    PlannedToolCommand,
    RiskLevel,
)
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion
from cloudhelm_agent_runtime.schemas.test_report import TesterAgentInput
from cloudhelm_tool_gateway import ToolGateway
from sqlalchemy.orm import Session

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.schemas.artifact import ArtifactProducerType
from cloudhelm_platform_api.services.artifact_service import ArtifactService
from cloudhelm_platform_api.services.artifact_storage import sha256
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.local_development_context import (
    LocalDevelopmentContext,
)
from cloudhelm_platform_api.services.local_development_evidence import (
    LocalDevelopmentEvidenceResolver,
)
from cloudhelm_platform_api.services.local_development_result import (
    LocalDevelopmentResult,
)
from cloudhelm_platform_api.services.local_development_step_support import (
    LocalDevelopmentStepSupport,
)
from cloudhelm_platform_api.services.local_development_tool_policy import (
    tester_tool_calls,
)


class LocalDevelopmentTestStep:
    """执行 Tester Agent、收集 JUnit 并形成同 cycle TestReport。"""

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
        self.tool_calls = ToolCallRepository(session)

    def run(
        self,
        context: LocalDevelopmentContext,
    ) -> LocalDevelopmentResult:
        """运行真实 pytest；测试失败回到 Implementing，基础设施异常暂停。"""

        implementation = self.evidence.implementation(context)
        step = self.support.begin(
            context,
            agent_type="tester",
            workflow_step="run_tester",
            approved_calls=tester_tool_calls(context),
        )
        created_artifacts = []
        try:
            self.events.record(
                "TestRunStarted",
                "agent",
                str(step.run.id),
                {
                    "agent_run_id": str(step.run.id),
                    "evidence_set_id": implementation.evidence_set_id,
                },
                context.task.id,
            )
            output = TesterAgent(step.provider).run(
                TesterAgentInput(
                    task_id=context.task.id,
                    project_id=context.task.project_id,
                    development_plan_id=context.plan.id,
                    title=context.task.title,
                    acceptance_criteria=[
                        AcceptanceCriterion.model_validate(item)
                        for item in context.requirement.acceptance_criteria_json
                    ],
                    changed_files=implementation.output.changed_files,
                    commands=[
                        PlannedToolCommand(
                            tool_name=item.tool_name,
                            arguments=item.arguments,
                            command=self._display_command(
                                item.tool_name,
                                item.arguments,
                            ),
                            purpose=item.purpose,
                        )
                        for item in context.recipe.test_commands
                    ],
                    execution_recipe_sha256=context.recipe_sha256,
                    risk_level=RiskLevel(context.task.risk_level),
                ),
                conversation=step.conversation,
                tools=step.tools,
                tool_executor=step.executor,
            )
            self.support.raise_for_infrastructure(output)
            junit_ref = next(
                (
                    item.ref
                    for item in output.artifacts
                    if item.type == "junit_xml"
                ),
                None,
            )
            junit_call = self._junit_call(
                step.executor.tool_calls,
                junit_ref,
            )
            if junit_call is None or not isinstance(
                junit_call.result_json,
                dict,
            ):
                raise ServiceError(
                    "m6_junit_artifact_missing",
                    "Tester 未返回真实 JUnit 文件内容。",
                    409,
                )
            junit_content = junit_call.result_json.get("content")
            if not isinstance(junit_content, str) or not junit_content.strip():
                raise ServiceError(
                    "m6_junit_artifact_empty",
                    "Tester JUnit 文件为空。",
                    409,
                )
            junit_bytes = junit_content.encode("utf-8")
            if (
                junit_call.result_json.get("truncated") is True
                or junit_call.result_json.get("sha256")
                != sha256(junit_bytes)
                or junit_call.result_json.get("size_bytes")
                != len(junit_bytes)
            ):
                raise ServiceError(
                    "m6_junit_integrity_mismatch",
                    "Tester JUnit 内容与工具返回的 hash/大小不一致。",
                    409,
                )
            metadata = {
                "development_plan_id": str(context.plan.id),
                "recipe_sha256": context.recipe_sha256,
                "evidence_set_id": implementation.evidence_set_id,
                "coder_agent_run_id": str(implementation.run.id),
                "tester_agent_run_id": str(step.run.id),
            }
            junit_artifact = self.artifacts.create_text(
                task_id=context.task.id,
                artifact_type="junit_xml",
                display_name="junit.xml",
                content=junit_content,
                producer_type=ArtifactProducerType.TOOL,
                summary="Tester 真实 pytest JUnit XML。",
                metadata_json=metadata,
                idempotency_key=f"m6:junit:{step.run.id}",
                tool_call_id=junit_call.id,
                media_type="application/xml",
            )
            created_artifacts.append(junit_artifact)
            report = self.artifacts.create_json(
                task_id=context.task.id,
                artifact_type="test_report",
                display_name="test-report.json",
                content=output.model_dump(mode="json"),
                producer_type=ArtifactProducerType.AGENT,
                summary=output.summary,
                metadata_json={
                    **metadata,
                    "passed": output.status == "passed",
                    "status": output.status,
                    "passed_count": output.passed_count,
                    "failed_count": output.failed_count,
                },
                idempotency_key=f"m6:test-report:{step.run.id}",
                agent_run_id=step.run.id,
            )
            created_artifacts.append(report)
            self.support.complete(
                step,
                output,
                output_type="tester_agent_output",
            )
            event_type = (
                "TestRunPassed"
                if output.status == "passed"
                else "TestRunFailed"
            )
            self.events.record(
                event_type,
                "agent",
                str(step.run.id),
                {
                    "test_artifact_id": str(report.id),
                    "junit_artifact_id": str(junit_artifact.id),
                    "passed_count": output.passed_count,
                    "failed_count": output.failed_count,
                },
                context.task.id,
            )
            return LocalDevelopmentResult(
                action="run_tester",
                message=output.summary,
                target_phase=(
                    "Reviewing"
                    if output.status == "passed"
                    else "Implementing"
                ),
                agent_run=step.run,
                tool_calls=step.executor.tool_calls,
                artifacts=created_artifacts,
                gate_evidence={
                    "evidence_set_id": implementation.evidence_set_id,
                    "test_status": output.status,
                    "passed_count": output.passed_count,
                    "failed_count": output.failed_count,
                },
            )
        except Exception as exc:
            self.artifacts.delete_uncommitted_content(created_artifacts)
            self.support.fail(context, step, exc)
            raise

    @staticmethod
    def _display_command(tool_name: str, arguments: dict) -> list[str]:
        """把领域 pytest tool 还原为控制台可读命令数组。"""

        if tool_name != "test.run_pytest":
            raise ServiceError(
                "m6_test_tool_invalid",
                f"Tester recipe 不允许工具：{tool_name}。",
                409,
            )
        pytest_args = arguments.get("pytest_args", ["-q"])
        return [
            "uv",
            "run",
            "pytest",
            *[str(item) for item in pytest_args],
        ]

    def _junit_call(self, calls, junit_ref):
        """按 Tester 输出 report ref 精确绑定对应 repo.read_file。"""

        if not isinstance(junit_ref, str) or not junit_ref:
            return None
        for item in calls:
            if item.tool_name != "repo.read_file":
                continue
            record = self.tool_calls.get(item.id)
            if (
                record is not None
                and record.arguments_json.get("path") == junit_ref
            ):
                return item
        return None
