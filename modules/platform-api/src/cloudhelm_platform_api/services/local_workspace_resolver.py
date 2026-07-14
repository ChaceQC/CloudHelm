"""M6 Task workspace、分支和 recipe 的服务端绑定解析。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.services.exceptions import ServiceError

_RECIPE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class LocalWorkspaceResolver:
    """只从平台配置和 Task ID 推导本地路径，不接受请求方任意目录。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.workspace_parent = Path(
            settings.m6_workspace_root
        ).expanduser().resolve(strict=False)
        self.sample_repo = Path(
            settings.m6_sample_repo_root
        ).expanduser().resolve(strict=False)
        self.recipe_root = Path(
            settings.m6_recipe_root
        ).expanduser().resolve(strict=False)

    def ensure_configured_roots(self) -> None:
        """创建平台管理的输出父目录并校验 fixture/recipe 根目录。"""

        if not self.sample_repo.is_dir():
            raise ServiceError(
                "m6_sample_repo_missing",
                "M6 sample repo fixture 不存在。",
                409,
            )
        if not self.recipe_root.is_dir():
            raise ServiceError(
                "m6_recipe_root_missing",
                "M6 execution recipe 根目录不存在。",
                409,
            )
        self.workspace_parent.mkdir(parents=True, exist_ok=True)

    def workspace(self, task_id: UUID, *, require_exists: bool = True) -> Path:
        """返回 Task 独立 workspace，必要时要求已由 Scaffold 准备。"""

        candidate = (
            self.workspace_parent / str(task_id) / "repo"
        ).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace_parent)
        except ValueError as exc:
            raise ServiceError(
                "m6_workspace_invalid",
                "Task workspace 越过平台配置根目录。",
                500,
            ) from exc
        if require_exists and not candidate.is_dir():
            raise ServiceError(
                "m6_workspace_not_prepared",
                "Task workspace 尚未由 Scaffold 准备。",
                409,
            )
        return candidate

    def workspace_ref(self, task_id: UUID) -> str:
        """返回不暴露绝对路径的稳定 workspace 引用。"""

        return f"workspace://{task_id}"

    def branch_name(self, task_id: UUID) -> str:
        """按配置前缀和 Task ID 生成确定性本地开发分支。"""

        return f"{self.settings.m6_branch_prefix}/task-{str(task_id)[:8]}"

    def recipe_file(self, recipe_id: str) -> Path:
        """将已批准 recipe ID 解析为固定根目录内的 JSON 文件。"""

        if not _RECIPE_ID.fullmatch(recipe_id):
            raise ServiceError(
                "m6_recipe_id_invalid",
                "DevelopmentPlan 中的 execution recipe ID 无效。",
                409,
            )
        candidate = (self.recipe_root / f"{recipe_id}.plan.json").resolve(
            strict=False
        )
        try:
            candidate.relative_to(self.recipe_root)
        except ValueError as exc:
            raise ServiceError(
                "m6_recipe_path_invalid",
                "Execution recipe 越过配置根目录。",
                500,
            ) from exc
        if not candidate.is_file():
            raise ServiceError(
                "m6_recipe_not_found",
                f"未找到已批准 execution recipe：{recipe_id}。",
                409,
            )
        return candidate
