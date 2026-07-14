"""M6 Git finalize 共用的路径、SHA 与 Artifact 校验。"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.services.exceptions import ServiceError

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def normalize_git_paths(
    values: Any,
    label: str,
    require_nonempty: bool = True,
) -> list[str]:
    """规范化仓库相对路径并拒绝重复和越界。"""

    if not isinstance(values, list):
        raise gate_error("m6_git_paths_invalid", f"{label} 必须是路径数组。")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise gate_error(
                "m6_git_paths_invalid",
                f"{label} 包含无效路径。",
            )
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise gate_error(
                "m6_git_paths_invalid",
                f"{label} 包含越界路径。",
            )
        normalized.append(path.as_posix())
    if require_nonempty and not normalized:
        raise gate_error("m6_git_paths_empty", f"{label} 为空。")
    if len(normalized) != len(set(normalized)):
        raise gate_error("m6_git_paths_duplicate", f"{label} 包含重复路径。")
    return normalized


def read_artifact_text(storage, artifact: Artifact, label: str) -> str:
    """读取并验证 UTF-8 Artifact，拒绝空内容。"""

    content = storage.read_verified(
        artifact.storage_key,
        artifact.sha256,
        artifact.size_bytes,
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise gate_error(
            "m6_artifact_not_utf8",
            f"{label} 不是有效 UTF-8 文本。",
        ) from exc
    if not text.strip():
        raise gate_error("m6_artifact_empty", f"{label} 内容为空。")
    return text


def is_git_sha(value: Any) -> bool:
    """校验 Git SHA-1/SHA-256 十六进制格式。"""

    return isinstance(value, str) and _SHA_PATTERN.fullmatch(value) is not None


def gate_error(code: str, message: str) -> ServiceError:
    """构造稳定的 ReadyForPR 409 门禁错误。"""

    return ServiceError(code, message, 409)
