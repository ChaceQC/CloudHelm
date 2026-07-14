"""CloudHelm 核心 ORM 模型集合。

Alembic env 会导入该模块以注册所有表 metadata。新增模型时必须在这里
导入，避免迁移漏表。
"""

from cloudhelm_platform_api.db.base import Base
from cloudhelm_platform_api.models.agent_conversation import AgentConversation
from cloudhelm_platform_api.models.agent_run import AgentRun
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.design import TechnicalDesign
from cloudhelm_platform_api.models.development_plan import DevelopmentPlan
from cloudhelm_platform_api.models.event_log import EventLog
from cloudhelm_platform_api.models.project import Project
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.models.requirement import RequirementSpec
from cloudhelm_platform_api.models.task import Task
from cloudhelm_platform_api.models.tool_call import ToolCall

__all__ = [
    "AgentRun",
    "AgentConversation",
    "ApprovalRequest",
    "Artifact",
    "Base",
    "DevelopmentPlan",
    "EventLog",
    "Project",
    "PullRequestRecord",
    "RequirementSpec",
    "Task",
    "TechnicalDesign",
    "ToolCall",
]
