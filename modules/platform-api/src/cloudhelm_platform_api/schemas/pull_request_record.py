"""M6 本地等价 PullRequestRecord DTO 与转换函数。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.schemas.artifact import (
    sanitize_artifact_metadata,
    sanitize_artifact_text,
)

_SHA_PATTERN = r"^[0-9a-f]{40}([0-9a-f]{24})?$"
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[\\/]")


class PullRequestProvider(str, Enum):
    """PR record 提供方。"""

    LOCAL = "local"
    GITHUB = "github"
    GITEA = "gitea"


class PullRequestRecordStatus(str, Enum):
    """PR record 生命周期状态。"""

    OPEN = "open"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


class PullRequestRecordCreate(BaseModel):
    """PullRequestRecord service 内部创建 DTO。"""

    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    created_by_agent_run_id: UUID | None = None
    branch_tool_call_id: UUID | None = None
    commit_tool_call_id: UUID | None = None
    provider: PullRequestProvider = PullRequestProvider.LOCAL
    status: PullRequestRecordStatus = PullRequestRecordStatus.OPEN
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=4000)
    base_branch: str = Field(min_length=1, max_length=240)
    head_branch: str = Field(min_length=1, max_length=240)
    base_commit_sha: str = Field(pattern=_SHA_PATTERN)
    commit_sha: str = Field(pattern=_SHA_PATTERN)
    changed_files_json: list[dict[str, Any]] = Field(min_length=1)
    diff_stat_json: dict[str, Any] = Field(default_factory=dict)
    diff_artifact_id: UUID
    test_artifact_id: UUID
    review_artifact_id: UUID
    security_artifact_id: UUID
    url: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=180)

    @field_validator("changed_files_json")
    @classmethod
    def validate_changed_files(
        cls,
        files: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """changed files 必须使用仓库相对路径。"""

        for item in files:
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("each changed file requires path")
            _validate_relative_repo_path(path)
        return files

    @model_validator(mode="after")
    def validate_provider_and_branches(self) -> PullRequestRecordCreate:
        """local record 不带 URL，base/head 必须不同。"""

        if self.base_branch == self.head_branch:
            raise ValueError("base_branch and head_branch must differ")
        if self.provider == PullRequestProvider.LOCAL and self.url is not None:
            raise ValueError("local pull request record must not contain url")
        return self


class PullRequestRecordRead(BaseModel):
    """本地等价 PR record 响应。"""

    id: UUID
    task_id: UUID
    project_id: UUID
    development_plan_id: UUID
    created_by_agent_run_id: UUID | None
    branch_tool_call_id: UUID | None
    commit_tool_call_id: UUID | None
    provider: PullRequestProvider
    status: PullRequestRecordStatus
    title: str
    summary: str
    base_branch: str
    head_branch: str
    base_commit_sha: str
    commit_sha: str
    changed_files_json: list[dict[str, Any]]
    diff_stat_json: dict[str, Any]
    diff_artifact_id: UUID
    test_artifact_id: UUID
    review_artifact_id: UUID
    security_artifact_id: UUID
    url: str | None
    created_at: datetime
    updated_at: datetime


def pull_request_record_to_read(
    record: PullRequestRecord,
) -> PullRequestRecordRead:
    """把 ORM record 转为安全响应。"""

    changed_files: list[dict[str, Any]] = []
    for raw_item in record.changed_files_json:
        if not isinstance(raw_item, dict):
            continue
        raw_path = raw_item.get("path")
        item = sanitize_artifact_metadata(raw_item)
        if isinstance(raw_path, str):
            item["path"] = _safe_relative_repo_path(raw_path)
        changed_files.append(item)

    return PullRequestRecordRead(
        id=record.id,
        task_id=record.task_id,
        project_id=record.project_id,
        development_plan_id=record.development_plan_id,
        created_by_agent_run_id=record.created_by_agent_run_id,
        branch_tool_call_id=record.branch_tool_call_id,
        commit_tool_call_id=record.commit_tool_call_id,
        provider=PullRequestProvider(record.provider),
        status=PullRequestRecordStatus(record.status),
        title=sanitize_artifact_text(record.title),
        summary=sanitize_artifact_text(record.summary),
        base_branch=record.base_branch,
        head_branch=record.head_branch,
        base_commit_sha=record.base_commit_sha,
        commit_sha=record.commit_sha,
        changed_files_json=changed_files,
        diff_stat_json=sanitize_artifact_metadata(record.diff_stat_json),
        diff_artifact_id=record.diff_artifact_id,
        test_artifact_id=record.test_artifact_id,
        review_artifact_id=record.review_artifact_id,
        security_artifact_id=record.security_artifact_id,
        url=record.url,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _validate_relative_repo_path(value: str) -> None:
    """校验仓库相对路径，不接受盘符、根路径或上级跳转。"""

    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or _WINDOWS_DRIVE_PREFIX.match(value)
        or ".." in path.parts
    ):
        raise ValueError("changed file path must be repository-relative")


def _safe_relative_repo_path(value: str) -> str:
    """历史记录路径异常时只返回末级文件名。"""

    try:
        _validate_relative_repo_path(value)
    except ValueError:
        return PurePosixPath(value.replace("\\", "/")).name or "file"
    return PurePosixPath(value.replace("\\", "/")).as_posix()
