"""受控 auth/profile demo issue 的本地 M4 领域设计与计划。"""

from __future__ import annotations

from cloudhelm_agent_runtime.providers.local_m4_intent import (
    AUTH_PROFILE_RECIPE_ID,
    AUTH_PROFILE_RECIPE_MARKER,
)
from cloudhelm_agent_runtime.providers.local_m4_sample_auth_contract import (
    auth_profile_db_schema,
    auth_profile_openapi,
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


def generate_sample_auth_architect(
    data: ArchitectAgentInput,
) -> ArchitectAgentOutput:
    """为受控 auth/profile issue 生成与 sample repo 一致的领域设计。"""

    risks = [
        "密码摘要、token 签名与鉴权失败响应属于安全敏感逻辑，必须人工审查。",
        "SQLite 只用于单实例 demo；并发写入和多实例共享不属于当前 M6 范围。",
        "指标标签不得包含 email、用户 ID、token 或任意请求路径。",
    ]
    criteria = [
        f"- {item.id}: {item.description}"
        for item in data.acceptance_criteria
    ]
    content = "\n".join(
        [
            AUTH_PROFILE_RECIPE_MARKER,
            f"# ADR：{data.title}",
            "",
            "## 决策",
            "- 在 `sample_service` 内新增认证路由、安全原语和 SQLite repository。",
            "- 密码使用 `hashlib.scrypt` 加随机盐摘要，不保存明文或可逆密钥。",
            "- access token 使用版本化 HMAC-SHA256 不透明短期凭据，固定 1800 秒。",
            "- `/auth/register`、`/auth/login`、`/profile` 继续经过现有指标中间件。",
            "",
            "## 模块边界",
            "- `auth.py`：HTTP 路由、严格请求/响应模型、统一认证错误和依赖装配。",
            "- `auth_security.py`：密码摘要、常量时间校验、token 签发与校验。",
            "- `user_repository.py`：SQLite 初始化、唯一 email 和资料持久化。",
            "- `main.py`：应用装配、认证路由接入和低基数 HTTP 指标。",
            "- `tests/`：黑盒 API、白盒安全原语、持久化重建和指标回归。",
            "",
            "## 验收映射",
            *criteria,
            "",
            "## 风险",
            *[f"- {risk}" for risk in risks],
        ]
    )
    mermaid = "\n".join(
        [
            "flowchart LR",
            '    Client["API Client"] --> Auth["auth router"]',
            '    Auth --> Security["password/token security"]',
            '    Auth --> Repo["SQLite user repository"]',
            '    Auth --> Metrics["HTTP metrics middleware"]',
        ]
    )
    return ArchitectAgentOutput(
        summary="已生成 sample auth/profile API、数据、安全与测试设计。",
        content_markdown=content,
        openapi_json=auth_profile_openapi(),
        db_schema_json=auth_profile_db_schema(),
        mermaid_diagram=mermaid,
        risk_level=_max_risk(data.task_risk_level, RiskLevel.L2),
        risks=risks,
        approval_recommended=True,
    )


def generate_sample_auth_planner(
    data: PlannerAgentInput,
) -> PlannerAgentOutput:
    """生成与 M6 Scaffold/Coder/Tester/Reviewer/Security 一致的任务图。"""

    steps = [
        DevelopmentPlanStep(
            id="STEP-001",
            title="准备受控 sample Git workspace",
            description="复制只读 fixture、排除缓存/凭据并建立 baseline commit。",
            agent="scaffold",
            expected_artifact="workspace_manifest",
        ),
        DevelopmentPlanStep(
            id="STEP-002",
            title="实现 auth/profile 领域闭环",
            description=(
                "实现 SQLite 用户持久化、scrypt 密码摘要、HMAC token、"
                "注册/登录/资料 API、文档和测试。"
            ),
            agent="coder",
            expected_artifact="diff_patch",
            depends_on=["STEP-001"],
            execution_recipe=AUTH_PROFILE_RECIPE_ID,
        ),
        DevelopmentPlanStep(
            id="STEP-003",
            title="执行黑盒与白盒 pytest",
            description="运行完整 pytest/JUnit，逐项映射全部稳定 AC。",
            agent="tester",
            expected_artifact="test_report",
            depends_on=["STEP-002"],
        ),
        DevelopmentPlanStep(
            id="STEP-004",
            title="审查 diff 与验收证据",
            description="核对 changed files、测试报告和每条 AC 的满足状态。",
            agent="reviewer",
            expected_artifact="review_report",
            depends_on=["STEP-003"],
        ),
        DevelopmentPlanStep(
            id="STEP-005",
            title="执行代码与依赖安全扫描",
            description="运行 Bandit 与 pip-audit，保存 findings 和剩余风险。",
            agent="security",
            expected_artifact="security_report",
            depends_on=["STEP-004"],
        ),
    ]
    risks = [
        DevelopmentPlanRisk(
            id="RISK-001",
            description="认证与 token 实现错误会造成凭据泄露或越权。",
            mitigation="人工批准设计，并以安全原语白盒测试和 Bandit 门禁验证。",
            risk_level=RiskLevel.L2,
        ),
        DevelopmentPlanRisk(
            id="RISK-002",
            description="本地 provider 只覆盖当前受控 demo recipe。",
            mitigation="其他需求切换已配置的 openai_compatible provider。",
            risk_level=RiskLevel.L1,
        ),
    ]
    return PlannerAgentOutput(
        summary="已按 sample auth/profile 领域目标拆分本地开发与质量门禁。",
        steps=steps,
        risks=risks,
        status="ready_for_review",
        risk_level=_max_risk(data.risk_level, RiskLevel.L2),
    )


def _max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    """返回两个风险等级中更高的一个。"""

    order = {level: index for index, level in enumerate(RiskLevel)}
    return left if order[left] >= order[right] else right
