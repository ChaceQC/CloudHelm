"""Agent Runtime 结构化输出白盒测试。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from cloudhelm_agent_runtime.agents import ArchitectAgent, PlannerAgent, RequirementAgent
from cloudhelm_agent_runtime.providers import LocalStructuredProvider, MissingProviderConfigurationError, OpenAICompatibleProvider
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.design import ArchitectAgentInput
from cloudhelm_agent_runtime.schemas.development_plan import DevelopmentPlanStep, PlannerAgentInput
from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion, RequirementAgentInput


def test_requirement_agent_generates_valid_structured_output() -> None:
    """Requirement Agent 应从真实输入生成可校验需求规格。"""

    provider = LocalStructuredProvider()
    output = RequirementAgent(provider).run(
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="实现 Agent 编排",
            description="用户需要在控制台启动 M4 编排。必须展示事件和验收标准。",
            source_type="manual",
            source_ref=None,
            risk_level=RiskLevel.L1,
        )
    )

    assert output.user_story.startswith("作为 CloudHelm 使用者")
    assert output.acceptance_criteria[0].id == "AC-001"
    assert output.constraints[0].type == "source"


def test_architect_agent_marks_database_related_design_as_l2() -> None:
    """涉及数据库/迁移风险的设计应建议审批。"""

    provider = LocalStructuredProvider()
    requirement_output = RequirementAgent(provider).run(
        RequirementAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            title="新增开发计划表",
            description="需要新增数据库表并写入迁移，控制台可查询。",
            source_type="manual",
            risk_level=RiskLevel.L1,
        )
    )
    output = ArchitectAgent(provider).run(
        ArchitectAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            requirement_spec_id=uuid4(),
            title="新增开发计划表",
            user_story=requirement_output.user_story,
            acceptance_criteria=requirement_output.acceptance_criteria,
            constraints=requirement_output.constraints,
            task_risk_level=RiskLevel.L1,
        )
    )

    assert output.risk_level == RiskLevel.L2
    assert output.approval_recommended is True
    assert "development_plans" in str(output.db_schema_json)


def test_planner_agent_rejects_missing_step_dependency() -> None:
    """DevelopmentPlan schema 必须拒绝断裂依赖。"""

    with pytest.raises(ValidationError):
        from cloudhelm_agent_runtime.schemas.development_plan import PlannerAgentOutput

        PlannerAgentOutput(
            summary="坏计划",
            steps=[
                DevelopmentPlanStep(
                    id="STEP-001",
                    title="坏依赖",
                    description="依赖不存在的步骤。",
                    agent="tester",
                    expected_artifact="test",
                    depends_on=["STEP-999"],
                )
            ],
            risks=[],
            risk_level=RiskLevel.L1,
        )


def test_planner_agent_generates_task_graph() -> None:
    """Planner Agent 应输出可追溯任务图。"""

    output = PlannerAgent(LocalStructuredProvider()).run(
        PlannerAgentInput(
            task_id=uuid4(),
            project_id=uuid4(),
            technical_design_id=uuid4(),
            title="实现 M4",
            design_summary="需要 Platform API、控制台和测试。",
            risk_level=RiskLevel.L1,
        )
    )

    assert [step.id for step in output.steps] == ["STEP-001", "STEP-002", "STEP-003", "STEP-004"]
    assert output.status == "ready_for_review"


def test_openai_compatible_provider_reports_missing_config() -> None:
    """缺少外部模型配置时不能静默写固定输出。"""

    provider = OpenAICompatibleProvider(api_base=None, api_key=None, model_name=None)
    with pytest.raises(MissingProviderConfigurationError):
        provider.generate(
            "requirement",
            RequirementAgentInput(
                task_id=uuid4(),
                project_id=uuid4(),
                title="配置缺失",
                description="验证缺配置错误。",
                source_type="manual",
                risk_level=RiskLevel.L1,
            ),
            AcceptanceCriterion,
        )
