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


REQUIREMENT_AGENTS = ("requirement", "planner", "architect")
DESIGN_AGENTS = ("architect", "planner")
REPO_READ_AGENTS = ("requirement", "planner", "architect", "coder", "reviewer", "security")
REPO_WRITE_AGENTS = ("coder", "scaffold")
SANDBOX_RUN_AGENTS = ("coder", "tester", "reviewer", "security", "scaffold")
ARTIFACT_AGENTS = ("tester", "reviewer", "security")
GIT_READ_AGENTS = ("coder", "tester", "reviewer", "security", "release")
GIT_WRITE_AGENTS = ("coder", "release")


def build_default_registry() -> ToolRegistry:
    """注册 M5 本地工具及其最小 Agent 权限白名单。"""

    registry = ToolRegistry()
    for declaration in [
        ToolDeclaration("requirement.normalize", "整理原始需求为结构化片段。", RequirementNormalizeArguments, RiskLevel.L0, False, ("raw_input",), requirement_tool.normalize, REQUIREMENT_AGENTS),
        ToolDeclaration("design.render_markdown", "将结构化设计要点渲染为 Markdown。", DesignRenderMarkdownArguments, RiskLevel.L0, False, ("title",), design_tool.render_markdown, DESIGN_AGENTS),
        ToolDeclaration("repo.read_file", "读取受控 worktree 内文本文件。", RepoReadFileArguments, RiskLevel.L0, False, ("workspace_root", "path"), repo_tool.read_file, REPO_READ_AGENTS),
        ToolDeclaration("repo.search_text", "在受控 worktree 内搜索文本。", RepoSearchTextArguments, RiskLevel.L0, False, ("workspace_root", "pattern"), repo_tool.search_text, REPO_READ_AGENTS),
        ToolDeclaration("repo.list_files", "列出受控 worktree 内文件。", RepoListFilesArguments, RiskLevel.L0, False, ("workspace_root", "path"), repo_tool.list_files, REPO_READ_AGENTS),
        ToolDeclaration("repo.write_file", "写入受控 worktree 内文本文件。", RepoWriteFileArguments, RiskLevel.L1, False, ("workspace_root", "path", "mode"), repo_tool.write_file, REPO_WRITE_AGENTS, False),
        ToolDeclaration("sandbox.run_command", "在本地受控目录执行非交互命令。", SandboxRunCommandArguments, RiskLevel.L1, False, ("workspace_root", "cwd", "command"), sandbox_tool.run_command, SANDBOX_RUN_AGENTS, False),
        ToolDeclaration("sandbox.collect_artifact", "收集本地 sandbox 产物元数据。", SandboxCollectArtifactArguments, RiskLevel.L0, False, ("workspace_root", "path"), sandbox_tool.collect_artifact, ARTIFACT_AGENTS),
        ToolDeclaration("git.status", "读取受控 Git 仓库状态。", GitStatusArguments, RiskLevel.L0, False, ("repo_root",), git_tool.status, GIT_READ_AGENTS),
        ToolDeclaration("git.diff", "读取受控 Git 仓库 diff。", GitDiffArguments, RiskLevel.L0, False, ("repo_root", "paths"), git_tool.diff, GIT_READ_AGENTS),
        ToolDeclaration("git.create_branch", "创建并切换本地开发分支。", GitCreateBranchArguments, RiskLevel.L2, False, ("repo_root", "branch_name"), git_tool.create_branch, GIT_WRITE_AGENTS, False),
        ToolDeclaration("git.commit", "提交显式文件列表到本地 Git。", GitCommitArguments, RiskLevel.L2, False, ("repo_root", "paths"), git_tool.commit, GIT_WRITE_AGENTS, False),
        ToolDeclaration("approval.request_remote_action", "为未来 L3 远端动作创建审批请求，不执行动作。", RemoteActionApprovalArguments, RiskLevel.L3, True, ("action", "target_environment"), approval_tool.reject_direct_execution, ("release", "sre"), False),
    ]:
        registry.register(declaration)
    return registry
