"""审批占位工具参数模型。"""

from pydantic import BaseModel, Field


class RemoteActionApprovalArguments(BaseModel):
    """未来远端动作的审批申请参数。

    M5 只用该 schema 验证并创建 ApprovalRequest，不执行任何远端命令。
    """

    action: str = Field(min_length=1, max_length=120)
    target_environment: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1000)
