"""审批专用工具声明。

该工具用于验证 L3/L4 审批拦截链路。Gateway 会在执行前返回
`waiting_approval`，因此此 handler 不应在 M5 被调用。
"""

from cloudhelm_tool_gateway.policies import ToolPolicy
from cloudhelm_tool_gateway.schemas.approval import RemoteActionApprovalArguments


def reject_direct_execution(args: RemoteActionApprovalArguments, policy: ToolPolicy) -> dict:  # noqa: ARG001
    """防御性拒绝直接执行；被调用说明审批拦截链路失效。"""

    raise RuntimeError("approval-only tool cannot execute directly")
