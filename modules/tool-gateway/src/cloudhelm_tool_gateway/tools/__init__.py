"""M5 默认工具注册。"""

from cloudhelm_tool_gateway.registry import ToolDeclaration, ToolRegistry
from cloudhelm_tool_gateway.schemas.approval import RemoteActionApprovalArguments
from cloudhelm_tool_gateway.schemas.design import DesignRenderMarkdownArguments
from cloudhelm_tool_gateway.schemas.git import GitCommitArguments, GitCreateBranchArguments, GitDiffArguments, GitStatusArguments
from cloudhelm_tool_gateway.schemas.repo import (
    RepoListFilesArguments,
    RepoReadFileArguments,
    RepoSearchTextArguments,
    RepoWriteFileArguments,
)
from cloudhelm_tool_gateway.schemas.requirement import RequirementNormalizeArguments
from cloudhelm_tool_gateway.schemas.sandbox import SandboxCollectArtifactArguments, SandboxRunCommandArguments
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel
from cloudhelm_tool_gateway.tools import approval_tool, design_tool, git_tool, repo_tool, requirement_tool, sandbox_tool


def build_default_registry() -> ToolRegistry:
    """注册 M5 本地工具。"""

    registry = ToolRegistry()
    for declaration in [
        ToolDeclaration("requirement.normalize", "整理原始需求为结构化片段。", RequirementNormalizeArguments, RiskLevel.L0, False, ("raw_input",), requirement_tool.normalize),
        ToolDeclaration("design.render_markdown", "将结构化设计要点渲染为 Markdown。", DesignRenderMarkdownArguments, RiskLevel.L0, False, ("title",), design_tool.render_markdown),
        ToolDeclaration("repo.read_file", "读取受控 worktree 内文本文件。", RepoReadFileArguments, RiskLevel.L0, False, ("workspace_root", "path"), repo_tool.read_file),
        ToolDeclaration("repo.search_text", "在受控 worktree 内搜索文本。", RepoSearchTextArguments, RiskLevel.L0, False, ("workspace_root", "pattern"), repo_tool.search_text),
        ToolDeclaration("repo.list_files", "列出受控 worktree 内文件。", RepoListFilesArguments, RiskLevel.L0, False, ("workspace_root", "path"), repo_tool.list_files),
        ToolDeclaration("repo.write_file", "写入受控 worktree 内文本文件。", RepoWriteFileArguments, RiskLevel.L1, False, ("workspace_root", "path", "mode"), repo_tool.write_file),
        ToolDeclaration("sandbox.run_command", "在本地受控目录执行非交互命令。", SandboxRunCommandArguments, RiskLevel.L1, False, ("workspace_root", "cwd", "command"), sandbox_tool.run_command),
        ToolDeclaration("sandbox.collect_artifact", "收集本地 sandbox 产物元数据。", SandboxCollectArtifactArguments, RiskLevel.L0, False, ("workspace_root", "path"), sandbox_tool.collect_artifact),
        ToolDeclaration("git.status", "读取受控 Git 仓库状态。", GitStatusArguments, RiskLevel.L0, False, ("repo_root",), git_tool.status),
        ToolDeclaration("git.diff", "读取受控 Git 仓库 diff。", GitDiffArguments, RiskLevel.L0, False, ("repo_root", "paths"), git_tool.diff),
        ToolDeclaration("git.create_branch", "创建并切换本地开发分支。", GitCreateBranchArguments, RiskLevel.L2, False, ("repo_root", "branch_name"), git_tool.create_branch),
        ToolDeclaration("git.commit", "提交显式文件列表到本地 Git。", GitCommitArguments, RiskLevel.L2, False, ("repo_root", "paths"), git_tool.commit),
        ToolDeclaration("approval.request_remote_action", "为未来 L3 远端动作创建审批请求，不执行动作。", RemoteActionApprovalArguments, RiskLevel.L3, True, ("action", "target_environment"), approval_tool.not_executed),
    ]:
        registry.register(declaration)
    return registry
