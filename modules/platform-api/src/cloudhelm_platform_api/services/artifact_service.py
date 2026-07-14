"""M6 Artifact 文件存储与查询服务。"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_tool_gateway.audit import redact_sensitive_text

from cloudhelm_platform_api.core.config import Settings, get_settings
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.repositories.agent_run_repository import (
    AgentRunRepository,
)
from cloudhelm_platform_api.repositories.artifact_repository import (
    ArtifactRepository,
)
from cloudhelm_platform_api.repositories.task_repository import TaskRepository
from cloudhelm_platform_api.repositories.tool_call_repository import (
    ToolCallRepository,
)
from cloudhelm_platform_api.schemas.artifact import (
    ArtifactDetailRead,
    ArtifactProducerType,
    ArtifactRead,
    ArtifactStatus,
    artifact_to_detail,
    artifact_to_read,
    build_artifact_preview,
    sanitize_artifact_metadata,
)
from cloudhelm_platform_api.schemas.common import PageInfo, PageResponse
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.artifact_contract import (
    ensure_artifact_identity,
    validate_artifact_references,
)
from cloudhelm_platform_api.services.artifact_storage import (
    ArtifactStorage,
    safe_display_name,
    sha256,
    track_pending_artifact,
)

_LOSSLESS_TEXT_ARTIFACT_TYPES = frozenset({"diff_patch", "format_patch"})


class ArtifactService(BaseService):
    """把结构化证据写入受控文件，并只向 API 暴露安全引用。"""

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(session)
        self.settings = settings or get_settings()
        self.artifacts = ArtifactRepository(session)
        self.tasks = TaskRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.tool_calls = ToolCallRepository(session)
        self.events = EventService(session)
        self.storage = ArtifactStorage(self.settings.artifact_root)

    def create_text(
        self,
        *,
        task_id: UUID,
        artifact_type: str,
        display_name: str,
        content: str,
        producer_type: ArtifactProducerType,
        summary: str,
        metadata_json: dict[str, Any],
        idempotency_key: str,
        agent_run_id: UUID | None = None,
        tool_call_id: UUID | None = None,
        media_type: str = "text/plain",
    ) -> Artifact:
        """创建 UTF-8 Artifact；Git patch 保留原始字节供完整性验证。"""

        stored_text = (
            content
            if artifact_type in _LOSSLESS_TEXT_ARTIFACT_TYPES
            else (redact_sensitive_text(content) or "")
        )
        return self._create_bytes(
            task_id=task_id,
            artifact_type=artifact_type,
            display_name=display_name,
            content=stored_text.encode("utf-8"),
            producer_type=producer_type,
            summary=summary,
            metadata_json=metadata_json,
            idempotency_key=idempotency_key,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            media_type=media_type,
        )

    def create_json(
        self,
        *,
        task_id: UUID,
        artifact_type: str,
        display_name: str,
        content: Any,
        producer_type: ArtifactProducerType,
        summary: str,
        metadata_json: dict[str, Any],
        idempotency_key: str,
        agent_run_id: UUID | None = None,
        tool_call_id: UUID | None = None,
    ) -> Artifact:
        """创建确定性 JSON Artifact。"""

        sanitized = sanitize_artifact_metadata(content)
        encoded = json.dumps(
            sanitized,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        return self._create_bytes(
            task_id=task_id,
            artifact_type=artifact_type,
            display_name=display_name,
            content=encoded,
            producer_type=producer_type,
            summary=summary,
            metadata_json=metadata_json,
            idempotency_key=idempotency_key,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            media_type="application/json",
        )

    def get_detail(self, artifact_id: UUID) -> ArtifactDetailRead:
        """读取 Artifact 元数据和受限内容预览。"""

        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise ServiceError("artifact_not_found", "Artifact 不存在。", 404)
        content = self.storage.read_verified(
            artifact.storage_key,
            artifact.sha256,
            artifact.size_bytes,
        )
        preview = build_artifact_preview(
            artifact.media_type,
            content,
            max_bytes=self.settings.artifact_preview_bytes,
        )
        return artifact_to_detail(artifact, preview)

    def get_record(self, artifact_id: UUID) -> Artifact:
        """读取 Artifact ORM，供 PR 门禁服务复用。"""

        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise ServiceError("artifact_not_found", "Artifact 不存在。", 404)
        return artifact

    def delete_uncommitted_content(self, artifacts: list[Artifact]) -> None:
        """回滚晚期事务失败时删除本轮尚未提交的物理文件。"""

        for artifact in artifacts:
            self.storage.delete(artifact.storage_key)

    def list_by_task(
        self,
        task_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        artifact_type: str | None = None,
        status: str | None = None,
    ) -> PageResponse[ArtifactRead]:
        """分页读取某 Task 的 Artifact。"""

        if self.tasks.get(task_id) is None:
            raise ServiceError("task_not_found", "任务不存在。", 404)
        records, next_cursor = self.artifacts.list_by_task(
            task_id,
            limit,
            cursor,
            artifact_type=artifact_type,
            status=status,
        )
        return PageResponse(
            items=[artifact_to_read(record) for record in records],
            page=PageInfo(limit=limit, next_cursor=next_cursor),
        )

    def _create_bytes(
        self,
        *,
        task_id: UUID,
        artifact_type: str,
        display_name: str,
        content: bytes,
        producer_type: ArtifactProducerType,
        summary: str,
        metadata_json: dict[str, Any],
        idempotency_key: str,
        agent_run_id: UUID | None,
        tool_call_id: UUID | None,
        media_type: str,
    ) -> Artifact:
        """校验归属、写入文件并新增 Artifact ORM。"""

        validate_artifact_references(
            task_id=task_id,
            producer_type=producer_type,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            tasks=self.tasks,
            agent_runs=self.agent_runs,
            tool_calls=self.tool_calls,
        )
        digest = sha256(content)
        safe_name = safe_display_name(display_name)
        safe_summary = redact_sensitive_text(summary) or ""
        safe_metadata = sanitize_artifact_metadata(metadata_json)
        existing = self.artifacts.get_by_task_idempotency_key(
            task_id,
            idempotency_key,
        )
        if existing is not None:
            ensure_artifact_identity(
                existing,
                digest=digest,
                producer_type=producer_type,
                artifact_type=artifact_type,
                display_name=safe_name,
                media_type=media_type,
                summary=safe_summary,
                metadata_json=safe_metadata,
                agent_run_id=agent_run_id,
                tool_call_id=tool_call_id,
            )
            return existing

        artifact_id = uuid4()
        storage_key = PurePosixPath(
            str(task_id),
            str(artifact_id),
            safe_name,
        ).as_posix()
        self.storage.write(storage_key, content)
        track_pending_artifact(
            self.session,
            self.storage.root,
            storage_key,
        )

        artifact = self.artifacts.create(
            Artifact(
                id=artifact_id,
                task_id=task_id,
                agent_run_id=agent_run_id,
                tool_call_id=tool_call_id,
                producer_type=producer_type.value,
                artifact_type=artifact_type,
                status=ArtifactStatus.AVAILABLE.value,
                display_name=safe_name,
                media_type=media_type,
                storage_key=storage_key,
                sha256=digest,
                size_bytes=len(content),
                summary=safe_summary,
                metadata_json=safe_metadata,
                idempotency_key=idempotency_key,
            )
        )
        self.events.record(
            "ArtifactCreated",
            producer_type.value,
            str(agent_run_id or tool_call_id or "platform-api"),
            {
                "artifact_id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            },
            task_id,
        )
        return artifact
