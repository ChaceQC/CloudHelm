"""Repo Tool 黑盒和白盒测试。"""

from pathlib import Path
from uuid import uuid4

from cloudhelm_tool_gateway import RiskLevel, ToolCallRequest, create_default_gateway


def _request(tool_name: str, risk_level: RiskLevel, arguments: dict, agent_type: str = 'architect') -> ToolCallRequest:
    """构造测试 ToolCallRequest。"""

    return ToolCallRequest(
        task_id=uuid4(),
        agent_run_id=uuid4(),
        agent_type=agent_type,
        tool_name=tool_name,
        risk_level=risk_level,
        idempotency_key=str(uuid4()),
        arguments=arguments,
        reason="pytest",
    )


def test_repo_read_and_write_file(tmp_path: Path) -> None:
    """Repo Tool 能真实写入并读取 workspace 文件。"""

    gateway = create_default_gateway(allowed_workspace_roots=[tmp_path])
    write_result = gateway.execute(
        _request(
            "repo.write_file",
            RiskLevel.L1,
            {"workspace_root": str(tmp_path), "path": "docs/demo.md", "content": "你好 CloudHelm", "create_parent": True},
            agent_type='coder',
        )
    )
    assert write_result.status == "succeeded"
    read_result = gateway.execute(
        _request("repo.read_file", RiskLevel.L0, {"workspace_root": str(tmp_path), "path": "docs/demo.md"})
    )
    assert read_result.status == "succeeded"
    assert read_result.result_json is not None
    assert read_result.result_json["content"] == "你好 CloudHelm"


def test_repo_blocks_symlink_escape(tmp_path: Path) -> None:
    """Repo Tool 通过 resolve 阻止 symlink 指向 workspace 外。"""

    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
        _request("repo.read_file", RiskLevel.L0, {"workspace_root": str(tmp_path), "path": "link.txt"})
    )
    assert result.status == "failed"
    assert result.error_code == "path_outside_workspace"


def test_repo_search_text(tmp_path: Path) -> None:
    """Repo Tool 能在受控目录内搜索文本。"""

    (tmp_path / "a.py").write_text("print('CloudHelm')\n", encoding="utf-8")
    result = create_default_gateway(allowed_workspace_roots=[tmp_path]).execute(
        _request("repo.search_text", RiskLevel.L0, {"workspace_root": str(tmp_path), "pattern": "cloudhelm"})
    )
    assert result.status == "succeeded"
    assert result.result_json is not None
    assert result.result_json["matches"][0]["line"] == 1
