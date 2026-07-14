"""Artifact 受控文件存储辅助。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cloudhelm_platform_api.services.exceptions import ServiceError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_PENDING_ARTIFACTS_KEY = "cloudhelm_pending_artifacts"


class ArtifactStorage:
    """在固定 root 内原子写入并校验 Artifact 内容。"""

    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)

    def write(self, storage_key: str, content: bytes) -> Path:
        """原子写入内容；中间文件始终位于同一受控目录。"""

        path = self.resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        temp_path.write_bytes(content)
        os.replace(temp_path, path)
        return path

    def read_verified(
        self,
        storage_key: str,
        expected_sha256: str,
        expected_size: int,
    ) -> bytes:
        """读取文件并验证数据库记录中的 hash 和大小。"""

        path = self.resolve(storage_key)
        if not path.is_file():
            raise ServiceError(
                "artifact_content_missing",
                "Artifact 文件内容不存在。",
                409,
            )
        content = path.read_bytes()
        if sha256(content) != expected_sha256 or len(content) != expected_size:
            raise ServiceError(
                "artifact_integrity_mismatch",
                "Artifact 文件 hash 或大小与数据库记录不一致。",
                409,
            )
        return content

    def delete(self, storage_key: str) -> None:
        """删除尚未随数据库事务提交的 Artifact 文件，并清理空父目录。"""

        path = self.resolve(storage_key)
        if path.is_file():
            path.unlink()
        current = path.parent
        while current != self.root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def resolve(self, storage_key: str) -> Path:
        """把相对 key 解析到 root 内。"""

        candidate = (self.root / storage_key).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ServiceError(
                "artifact_storage_key_invalid",
                "Artifact 存储键越过受控根目录。",
                500,
            ) from exc
        return candidate


def sha256(content: bytes) -> str:
    """计算带算法前缀的 SHA-256。"""

    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def safe_display_name(value: str) -> str:
    """只保留展示文件名并限制长度。"""

    name = Path(value.replace("\\", "/")).name.strip()
    if not name:
        raise ServiceError(
            "artifact_display_name_invalid",
            "Artifact display_name 不能为空。",
            400,
        )
    return name[:240]


def track_pending_artifact(
    session: "Session",
    root: Path,
    storage_key: str,
) -> None:
    """登记当前数据库事务新写入、尚未提交的 Artifact 文件。"""

    pending = session.info.setdefault(_PENDING_ARTIFACTS_KEY, set())
    pending.add((str(root), storage_key))


def accept_pending_artifacts(session: "Session") -> None:
    """数据库提交成功后清除本事务 Artifact 跟踪记录。"""

    session.info.pop(_PENDING_ARTIFACTS_KEY, None)


def discard_pending_artifacts(session: "Session") -> None:
    """数据库回滚前后删除本事务新写入的 Artifact 文件。"""

    pending = session.info.pop(_PENDING_ARTIFACTS_KEY, set())
    for root, storage_key in pending:
        ArtifactStorage(root).delete(storage_key)
