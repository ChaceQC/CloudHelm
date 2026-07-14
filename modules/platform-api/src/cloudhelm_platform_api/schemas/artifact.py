"""M6 Artifact API DTO 与安全转换函数。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from cloudhelm_tool_gateway.audit import redact_sensitive_text

from cloudhelm_platform_api.models.artifact import Artifact

MAX_ARTIFACT_PREVIEW_BYTES = 65536
TEXT_PREVIEW_MEDIA_TYPES = {
    "application/json",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/x-diff",
    "text/x-python",
    "text/xml",
}
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[\\/]")
_EMBEDDED_WINDOWS_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)"
    r"[^\s\"'<>]+"
)
_EMBEDDED_POSIX_PATH = re.compile(
    r"(?<![:/A-Za-z0-9])/"
    r"(?:home|Users|tmp|var|opt|srv|workspace|mnt|etc|usr|root|private|app|data)"
    r"(?:/[^/\s\"'<>]+)+"
)
_SENSITIVE_METADATA_KEYS = {
    "absolute_path",
    "artifact_root",
    "repo_root",
    "storage_key",
    "workspace_root",
}


class ArtifactProducerType(str, Enum):
    """Artifact 生产者类型。"""

    AGENT = "agent"
    TOOL = "tool"
    SYSTEM = "system"


class ArtifactStatus(str, Enum):
    """Artifact 可用状态。"""

    AVAILABLE = "available"
    INVALIDATED = "invalidated"
    MISSING = "missing"


class ArtifactCreate(BaseModel):
    """Artifact service 内部创建 DTO。"""

    task_id: UUID
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None
    producer_type: ArtifactProducerType
    artifact_type: str = Field(min_length=1, max_length=80)
    status: ArtifactStatus = ArtifactStatus.AVAILABLE
    display_name: str = Field(min_length=1, max_length=240)
    media_type: str = Field(min_length=1, max_length=160)
    storage_key: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=2000)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=180)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        """展示名只接受文件名，避免响应携带目录信息。"""

        if "/" in value or "\\" in value:
            raise ValueError("display_name must not contain directory separators")
        return value

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, value: str) -> str:
        """内部存储键必须是无上级跳转的 POSIX 相对路径。"""

        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or _WINDOWS_DRIVE_PREFIX.match(value)
            or ".." in path.parts
        ):
            raise ValueError("storage_key must be a safe relative path")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_producer_reference(self) -> ArtifactCreate:
        """生产者类型必须具备对应的审计引用。"""

        references = {
            ArtifactProducerType.AGENT: (
                self.agent_run_id is not None
                and self.tool_call_id is None
            ),
            ArtifactProducerType.TOOL: (
                self.tool_call_id is not None
                and self.agent_run_id is None
            ),
            ArtifactProducerType.SYSTEM: (
                self.agent_run_id is None
                and self.tool_call_id is None
            ),
        }
        if not references[self.producer_type]:
            raise ValueError(
                "artifact producer_type requires exactly its own audit reference"
            )
        return self


class ArtifactRead(BaseModel):
    """Artifact 列表和引用响应；不包含内部 storage key。"""

    id: UUID
    task_id: UUID
    agent_run_id: UUID | None
    tool_call_id: UUID | None
    producer_type: ArtifactProducerType
    artifact_type: str
    status: ArtifactStatus
    display_name: str
    media_type: str
    uri: str
    sha256: str
    size_bytes: int
    summary: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ArtifactPreview(BaseModel):
    """受大小和媒体类型限制的 Artifact 内容预览。"""

    kind: Literal["text", "json"]
    text: str | None = None
    json_value: Any | None = None
    truncated: bool
    bytes_returned: int = Field(ge=0, le=MAX_ARTIFACT_PREVIEW_BYTES)

    @model_validator(mode="after")
    def validate_preview_payload(self) -> ArtifactPreview:
        """text/json 预览只携带与 kind 对应的内容。"""

        if self.kind == "text" and self.text is None:
            raise ValueError("text preview requires text")
        if self.kind == "json" and self.json_value is None:
            raise ValueError("json preview requires json_value")
        return self


class ArtifactDetailRead(ArtifactRead):
    """Artifact 详情，可由 service 注入安全内容预览。"""

    preview: ArtifactPreview | None = None


def artifact_to_read(artifact: Artifact) -> ArtifactRead:
    """把 ORM Artifact 转为不暴露本机路径的列表 DTO。"""

    return ArtifactRead(
        id=artifact.id,
        task_id=artifact.task_id,
        agent_run_id=artifact.agent_run_id,
        tool_call_id=artifact.tool_call_id,
        producer_type=ArtifactProducerType(artifact.producer_type),
        artifact_type=artifact.artifact_type,
        status=ArtifactStatus(artifact.status),
        display_name=_safe_display_name(artifact.display_name),
        media_type=artifact.media_type,
        uri=f"artifact://{artifact.id}",
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        summary=sanitize_artifact_text(artifact.summary),
        metadata_json=sanitize_artifact_metadata(artifact.metadata_json),
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )


def artifact_to_detail(
    artifact: Artifact,
    preview: ArtifactPreview | None = None,
) -> ArtifactDetailRead:
    """构造 Artifact 详情 DTO；文件读取由 service 完成。"""

    return ArtifactDetailRead(
        **artifact_to_read(artifact).model_dump(),
        preview=preview,
    )


def build_artifact_preview(
    media_type: str,
    content: bytes,
    *,
    max_bytes: int = MAX_ARTIFACT_PREVIEW_BYTES,
) -> ArtifactPreview | None:
    """从 service 已读取的字节构造受限 text/json 预览。"""

    if media_type not in TEXT_PREVIEW_MEDIA_TYPES:
        return None
    effective_limit = max(1, min(max_bytes, MAX_ARTIFACT_PREVIEW_BYTES))
    selected = content[:effective_limit]
    truncated = len(content) > effective_limit
    decoded = selected.decode("utf-8", errors="replace")
    if media_type == "application/json" and not truncated:
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            return ArtifactPreview(
                kind="text",
                text=sanitize_artifact_text(decoded),
                truncated=False,
                bytes_returned=len(selected),
            )
        else:
            if parsed is None:
                return ArtifactPreview(
                    kind="text",
                    text="null",
                    truncated=False,
                    bytes_returned=len(selected),
                )
            return ArtifactPreview(
                kind="json",
                json_value=sanitize_artifact_metadata(parsed),
                truncated=False,
                bytes_returned=len(selected),
            )
    return ArtifactPreview(
        kind="text",
        text=sanitize_artifact_text(decoded),
        truncated=truncated,
        bytes_returned=len(selected),
    )


def sanitize_artifact_metadata(value: Any) -> Any:
    """递归移除内部路径字段并遮蔽绝对路径值。"""

    if isinstance(value, dict):
        return {
            str(key): sanitize_artifact_metadata(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [sanitize_artifact_metadata(item) for item in value]
    if isinstance(value, str):
        return sanitize_artifact_text(value)
    return value


def sanitize_artifact_text(value: str) -> str:
    """为 API 预览遮蔽凭据及 Windows、UNC、POSIX 绝对路径。"""

    projected = redact_sensitive_text(value) or ""
    redacted = _EMBEDDED_WINDOWS_PATH.sub(
        "<redacted-local-path>",
        projected,
    )
    return _EMBEDDED_POSIX_PATH.sub(
        "<redacted-local-path>",
        redacted,
    )


def _safe_display_name(value: str) -> str:
    """从历史数据中兜底提取安全展示名。"""

    normalized = value.replace("\\", "/")
    return PurePosixPath(normalized).name or "artifact"
