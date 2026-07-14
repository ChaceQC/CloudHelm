"""LocalStructuredProvider 的 M4 规则化输出生成。"""

from __future__ import annotations

from pydantic import BaseModel

from cloudhelm_agent_runtime.providers.local_requirement_rules import (
    contains_any,
    extract_acceptance_criteria,
    split_sentences,
)
from cloudhelm_agent_runtime.schemas.agent_io import RiskLevel
from cloudhelm_agent_runtime.schemas.design import (
    ArchitectAgentInput,
    ArchitectAgentOutput,
)
from cloudhelm_agent_runtime.schemas.development_plan import (
    DevelopmentPlanRisk,
    DevelopmentPlanStep,
    PlannerAgentInput,
    PlannerAgentOutput,
)
from cloudhelm_agent_runtime.schemas.requirement import (
    AcceptanceCriterion,
    RequirementAgentInput,
    RequirementAgentOutput,
    RequirementConstraint,
)


def generate_requirement(payload: BaseModel) -> RequirementAgentOutput:
    """从真实任务输入生成需求规格。"""

    data = RequirementAgentInput.model_validate(payload)
    sentences = split_sentences(data.description)
    first_sentence = sentences[0] if sentences else data.title
    constraints = [
        RequirementConstraint(
            type="source",
            value=f"来源类型：{data.source_type}",
            required=True,
        ),
        RequirementConstraint(
            type="mvp_scope",
            value="M4 只生成需求、设计和计划，不执行代码或工具调用。",
            required=True,
        ),
    ]
    if data.source_ref:
        constraints.append(
            RequirementConstraint(
                type="source_ref",
                value=data.source_ref,
                required=False,
            )
        )
    if contains_any(data.description, ["测试", "pytest", "test", "验证"]):
        constraints.append(
            RequirementConstraint(
                type="testing",
                value="完成后必须记录黑盒和白盒验证结果。",
                required=True,
            )
        )

    criteria = extract_acceptance_criteria(data.description)
    if not criteria:
        descriptions = [
            f"系统能基于任务“{data.title}”生成结构化需求规格。",
            "需求规格包含可追溯的验收标准和约束条件。",
            "状态迁移、AgentRun 和事件日志可在控制台查询。",
        ]
        if len(sentences) > 1:
            descriptions.append(
                f"实现结果覆盖用户描述中的关键要求：{sentences[1]}"
            )
        criteria = [
            AcceptanceCriterion(
                id=f"AC-{index:03d}",
                description=description,
                verification="api",
            )
            for index, description in enumerate(descriptions, start=1)
        ]
    return RequirementAgentOutput(
        summary=f"围绕“{data.title}”整理需求、约束和验收标准。",
        raw_input=data.description,
        user_story=(
            f"作为 CloudHelm 使用者，我希望 {first_sentence}，"
            "以便在控制台中推进可审查的工程闭环。"
        ),
        constraints=constraints,
        acceptance_criteria=criteria,
        risk_level=data.risk_level,
    )


def generate_architect(payload: BaseModel) -> ArchitectAgentOutput:
    """从需求规格生成 M4 技术设计草案。"""

    data = ArchitectAgentInput.model_validate(payload)
    elevated = contains_any(
        data.user_story,
        ["数据库", "迁移", "部署", "权限", "审批"],
    )
    risk_level = _max_risk(
        data.task_risk_level,
        RiskLevel.L2 if elevated else RiskLevel.L1,
    )
    risks = [
        "M4 不执行 Repo/Git/Docker/SSH 工具，所有后续动作只进入计划或审批建议。"
    ]
    if risk_level in {RiskLevel.L2, RiskLevel.L3, RiskLevel.L4}:
        risks.append(
            "需求包含数据库、部署、权限或审批相关风险，建议人工设计审批。"
        )
    openapi_json = {
        "openapi": "3.1.0",
        "info": {"title": f"{data.title} M4 draft", "version": "0.3.0"},
        "paths": {
            "/api/tasks/{task_id}/run-next": {
                "post": {
                    "summary": "推进一个 M4 Agent 步骤",
                    "description": (
                        "由 Orchestrator 根据当前阶段执行 "
                        "Requirement、Architect 或 Planner。"
                    ),
                }
            }
        },
    }
    db_schema_json = {
        "tables": [
            {
                "name": "development_plans",
                "purpose": "保存 Planner Agent 输出的开发任务图和风险说明。",
            }
        ],
        "jsonb_fields": ["steps_json", "risks_json"],
    }
    content = "\n".join(
        [
            f"# {data.title} 技术设计草案",
            "",
            "## 用户故事",
            data.user_story,
            "",
            "## 模块边界",
            "- Platform API 负责事务、持久化和事件副作用。",
            "- Agent Runtime 负责结构化输出校验，不直接写数据库。",
            "- Orchestrator 负责 M4 状态迁移和失败恢复。",
            "",
            "## 验收映射",
            *[
                f"- {criterion.id}: {criterion.description}"
                for criterion in data.acceptance_criteria
            ],
            "",
            "## 风险",
            *[f"- {risk}" for risk in risks],
        ]
    )
    mermaid = "\n".join(
        [
            "stateDiagram-v2",
            "    Created --> RequirementClarifying",
            "    RequirementClarifying --> Designing",
            "    Designing --> WaitingDesignApproval",
            "    WaitingDesignApproval --> Planning",
            "    Designing --> Planning",
        ]
    )
    return ArchitectAgentOutput(
        summary=f"为“{data.title}”生成 M4 API、数据和状态机设计草案。",
        content_markdown=content,
        openapi_json=openapi_json,
        db_schema_json=db_schema_json,
        mermaid_diagram=mermaid,
        risk_level=risk_level,
        risks=risks,
        approval_recommended=risk_level
        in {RiskLevel.L2, RiskLevel.L3, RiskLevel.L4},
    )


def generate_planner(payload: BaseModel) -> PlannerAgentOutput:
    """从技术设计生成开发计划任务图。"""

    data = PlannerAgentInput.model_validate(payload)
    recipe = (
        "demo-issue-001-auth-profile-v1"
        if contains_any(
            f"{data.title}\n{data.design_summary}",
            ["注册", "个人资料", "/auth/register", "/profile"],
        )
        else None
    )
    steps = [
        DevelopmentPlanStep(
            id="STEP-001",
            title="补齐契约和迁移",
            description=(
                "同步 Pydantic schema、OpenAPI、JSON Schema 与 Alembic migration。"
            ),
            agent="architect",
            expected_artifact="schema_and_migration",
        ),
        DevelopmentPlanStep(
            id="STEP-002",
            title="实现 API 与状态机",
            description=(
                "在 service 层实现 M4 run-next 事务、副作用事件和失败恢复。"
            ),
            agent="coder",
            expected_artifact="platform_api_patch",
            depends_on=["STEP-001"],
            execution_recipe=recipe,
        ),
        DevelopmentPlanStep(
            id="STEP-003",
            title="接入控制台展示",
            description=(
                "展示 Requirement、Technical Design、Development Plan 和 Timeline。"
            ),
            agent="coder",
            expected_artifact="control_console_patch",
            depends_on=["STEP-002"],
        ),
        DevelopmentPlanStep(
            id="STEP-004",
            title="执行黑盒和白盒验证",
            description="覆盖 start/run-next、审批分支、schema 校验和异常路径。",
            agent="tester",
            expected_artifact="test_report",
            depends_on=["STEP-002", "STEP-003"],
        ),
    ]
    risks = [
        DevelopmentPlanRisk(
            id="RISK-001",
            description=(
                "外部 LLM 配置缺失时，openai_compatible provider 无法生成输出。"
            ),
            mitigation=(
                "默认使用 local_structured provider；"
                "如切换外部模型，缺配置时写入失败事件。"
            ),
            risk_level=RiskLevel.L1,
        )
    ]
    if data.risk_level in {RiskLevel.L2, RiskLevel.L3, RiskLevel.L4}:
        risks.append(
            DevelopmentPlanRisk(
                id="RISK-002",
                description="设计风险达到 L2 及以上，后续执行前必须人工审批。",
                mitigation="保持任务在审批或计划审查状态，禁止自动进入工具执行。",
                risk_level=data.risk_level,
            )
        )
    return PlannerAgentOutput(
        summary=f"围绕“{data.title}”拆分 M4 后续实现任务图，当前不执行代码工具。",
        steps=steps,
        risks=risks,
        status="ready_for_review",
        risk_level=data.risk_level,
    )
def _max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    """返回两个风险等级中更高的一个。"""

    order = {level: index for index, level in enumerate(RiskLevel)}
    return left if order[left] >= order[right] else right
