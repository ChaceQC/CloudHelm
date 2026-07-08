"""Project ORM 模型。"""

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from cloudhelm_platform_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """CloudHelm 管理的代码项目。

    Project 是任务、环境和后续部署记录的归属根实体。M2 仅保存仓库入口
    和默认分支，不在本阶段执行真实 Git 操作。
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(Text, nullable=False, comment="项目显示名称。")
    repo_url: Mapped[str] = mapped_column(Text, nullable=False, comment="仓库地址。")
    default_branch: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="main",
        comment="默认工作分支。",
    )
    provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="git",
        comment="仓库提供方，例如 github、gitea 或 local。",
    )
