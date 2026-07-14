"""M6 execution recipe schema 与仓库 fixture 白盒测试。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from cloudhelm_platform_api.schemas.local_execution_recipe import (
    LocalExecutionRecipe,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RECIPE_PATH = (
    REPOSITORY_ROOT
    / "examples"
    / "sample-repo-python"
    / "demo-issues"
    / "demo-issue-001-auth-profile-v1.plan.json"
)


def test_repository_recipe_matches_strict_m6_schema() -> None:
    """真实 sample recipe 必须可直接作为 M6 受控执行输入。"""

    recipe = LocalExecutionRecipe.model_validate(_recipe_payload())

    assert recipe.recipe_id == "demo-issue-001-auth-profile-v1"
    assert recipe.issue_path == "demo-issues/001-auth-profile.md"
    assert recipe.step_ids == ["STEP-002"]
    assert all(
        command.tool_name == "test.run_pytest"
        for command in recipe.test_commands
    )
    assert all(
        command.tool_name.startswith("security.run_")
        for command in recipe.security_commands
    )
    assert len(recipe.acceptance_evidence) == 11


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("issue_path", "../outside.md"),
        ("issue_path", r"D:\private\issue.md"),
    ),
)
def test_recipe_rejects_issue_path_escape(
    field_name: str,
    invalid_value: str,
) -> None:
    """Issue 引用只能指向 fixture 内的 demo-issues Markdown。"""

    payload = _recipe_payload()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        LocalExecutionRecipe.model_validate(payload)


def test_recipe_keeps_test_and_security_tool_domains_separate() -> None:
    """Tester 与 Security 命令列表不得互相混入其他领域工具。"""

    test_payload = _recipe_payload()
    test_payload["test_commands"][0]["tool_name"] = "security.run_bandit"
    with pytest.raises(ValidationError):
        LocalExecutionRecipe.model_validate(test_payload)

    security_payload = _recipe_payload()
    security_payload["security_commands"][0]["tool_name"] = (
        "test.run_pytest"
    )
    with pytest.raises(ValidationError):
        LocalExecutionRecipe.model_validate(security_payload)


def test_recipe_rejects_duplicate_acceptance_evidence() -> None:
    """同一 AC 只能在 recipe 中映射一次。"""

    payload = _recipe_payload()
    payload["acceptance_evidence"].append(
        deepcopy(payload["acceptance_evidence"][0])
    )

    with pytest.raises(ValidationError):
        LocalExecutionRecipe.model_validate(payload)


def _recipe_payload() -> dict:
    """以 UTF-8 读取真实版本化 recipe。"""

    with RECIPE_PATH.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    assert isinstance(payload, dict)
    return payload
