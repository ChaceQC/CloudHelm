"""Subagent 工具权限交集的稳定审计值对象。"""

from dataclasses import dataclass
from uuid import UUID

from cloudhelm_tool_gateway.audit import stable_json_hash


@dataclass(frozen=True, slots=True)
class SubagentToolScope:
    """记录 child 角色与全部父级角色交集后的有效工具范围。"""

    conversation_id: UUID
    child_role: str
    ancestor_roles: tuple[str, ...]
    effective_allowed_tools: tuple[str, ...]

    def audit_payload(self) -> dict[str, object]:
        """返回可持久化、可哈希的权限判定摘要。"""

        return {
            "policy_version": "subagent_parent_intersection_v1",
            "conversation_id": str(self.conversation_id),
            "child_role": self.child_role,
            "ancestor_roles": list(self.ancestor_roles),
            "effective_allowed_tools": list(self.effective_allowed_tools),
        }

    def fingerprint(self) -> str:
        """返回用于 ToolCall 审计的稳定权限指纹。"""

        return stable_json_hash(self.audit_payload())
