"""共享 Agent JSON Schema 与 Runtime 输出集合一致性测试。"""

import json
from pathlib import Path

from cloudhelm_agent_runtime.schemas import (
    ArchitectAgentOutput,
    CoderAgentOutput,
    PlannerAgentOutput,
    RequirementAgentOutput,
    ReviewerAgentOutput,
    ScaffoldAgentOutput,
    SecurityAgentOutput,
    TesterAgentOutput,
)


SCHEMA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared-contracts"
    / "schemas"
    / "agents"
)

OUTPUT_MODELS = {
    "requirement-agent-output.schema.json": RequirementAgentOutput,
    "architect-agent-output.schema.json": ArchitectAgentOutput,
    "planner-agent-output.schema.json": PlannerAgentOutput,
    "scaffold-agent-output.schema.json": ScaffoldAgentOutput,
    "coder-agent-output.schema.json": CoderAgentOutput,
    "tester-agent-output.schema.json": TesterAgentOutput,
    "reviewer-agent-output.schema.json": ReviewerAgentOutput,
    "security-agent-output.schema.json": SecurityAgentOutput,
}


def _load(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def test_agent_run_union_contains_all_eight_normal_roles() -> None:
    """AgentRun union 必须引用八类普通 Agent 输出。"""

    schema = _load("agent-run-output.schema.json")
    refs = {item["$ref"] for item in schema["oneOf"]}
    assert refs == {
        "./requirement-agent-output.schema.json",
        "./architect-agent-output.schema.json",
        "./planner-agent-output.schema.json",
        "./scaffold-agent-output.schema.json",
        "./coder-agent-output.schema.json",
        "./tester-agent-output.schema.json",
        "./reviewer-agent-output.schema.json",
        "./security-agent-output.schema.json",
    }


def test_all_agent_output_objects_forbid_extra_fields() -> None:
    """共享输出 schema 的根对象和公共嵌套对象均拒绝额外字段。"""

    for name in (
        "requirement-agent-output.schema.json",
        "architect-agent-output.schema.json",
        "planner-agent-output.schema.json",
        "scaffold-agent-output.schema.json",
        "coder-agent-output.schema.json",
        "tester-agent-output.schema.json",
        "reviewer-agent-output.schema.json",
        "security-agent-output.schema.json",
    ):
        assert _load(name)["additionalProperties"] is False, name

    common = _load("agent-common.schema.json")
    for name, definition in common["$defs"].items():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False, name


def test_shared_agent_output_fields_match_runtime_models() -> None:
    """共享输出字段和必填集合必须与 Pydantic 模型精确一致。"""

    for name, model in OUTPUT_MODELS.items():
        shared = _load(name)
        runtime = model.model_json_schema()

        assert set(shared["properties"]) == set(runtime["properties"]), name
        assert set(shared["required"]) == set(runtime["required"]), name
