"""工具调用审计摘要工具。

审计摘要用于写入 Platform API 的 `tool_calls` 和 `event_logs`，只保存
参数键、低敏短值、hash 和输出摘要，不把文件内容、密钥或完整命令输出
原样暴露给控制台。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SENSITIVE_KEYWORDS = ("password", "token", "secret", "key", "credential", "cookie", "content")
INTERNAL_PATH_KEYS = {
    "artifact_root",
    "repo_root",
    "source_root",
    "storage_key",
    "workspace_root",
}
STORAGE_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "auth_header",
    "api_key",
    "apikey",
    "private_key",
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"(?i)\b(password|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=]\s*([^\r\n]+)"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)"
        r"[^\s\"'<>]+"
    ),
    re.compile(
        r"(?<![:/A-Za-z0-9])/"
        r"(?:home|Users|tmp|var|opt|srv|workspace|mnt|etc|usr|root|private|app|data)"
        r"(?:/[^/\s\"'<>]+)+"
    ),
)


def stable_json_hash(value: Any) -> str:
    """生成稳定 JSON hash，供审计去重和事后比对使用。"""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def redact_value(key: str, value: Any, max_length: int = 80) -> Any:
    """按字段名对参数值脱敏并截断。

    参数:
        key: 参数字段名。
        value: 参数值。
        max_length: 普通字符串允许保留的最大长度。
    """

    lowered = key.lower()
    normalized_key = lowered.replace("-", "_")
    if normalized_key in INTERNAL_PATH_KEYS:
        return "<server-bound-path>"
    if any(keyword in lowered for keyword in SENSITIVE_KEYWORDS):
        if isinstance(value, str):
            return f"<redacted:{len(value)} chars>"
        return "<redacted>"
    if isinstance(value, str):
        return value if len(value) <= max_length else f"{value[: max_length - 3]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return f"<list:{len(value)}>"
    if isinstance(value, dict):
        return f"<object:{len(value)}>"
    return str(type(value).__name__)


def summarize_mapping(arguments: dict[str, Any], max_length: int = 360) -> str:
    """生成短参数摘要，避免 API 响应泄露完整参数。"""

    if not arguments:
        return "empty"
    redacted = {key: redact_value(key, value) for key, value in sorted(arguments.items())}
    summary = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    return summary if len(summary) <= max_length else f"{summary[: max_length - 3]}..."


def truncate_text(value: str | bytes | None, max_length: int = 4000) -> str | None:
    """按 UTF-8 展示需求截断 stdout、stderr 或文件片段。"""

    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text if len(text) <= max_length else f"{text[: max_length - 24]}\n...<truncated:{len(text)}>"


def redact_sensitive_text(value: str | bytes | None) -> str | None:
    """移除输出文本中的常见 Token、Bearer 凭据和私钥块。"""

    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: f"{match.group(1)}=<redacted>", text)
        else:
            text = pattern.sub("<redacted>", text)
    for pattern in LOCAL_PATH_PATTERNS:
        text = pattern.sub("<redacted-local-path>", text)
    return text


def sanitize_arguments_for_storage(arguments: dict[str, Any]) -> dict[str, Any]:
    """生成可落库参数，敏感字段脱敏且文件正文只保留长度与 hash。"""

    return {
        key: _sanitize_value(value, key=key, redact_content=True)
        for key, value in arguments.items()
    }


def sanitize_result_for_storage(value: Any) -> Any:
    """递归清理结果 JSON 中的敏感字段和凭据文本。"""

    return _sanitize_value(value, key=None, redact_content=False)


def _sanitize_value(value: Any, *, key: str | None, redact_content: bool) -> Any:
    """递归实现参数和结果脱敏，返回 JSON 可序列化对象。"""

    lowered = (key or "").lower()
    normalized_key = lowered.replace("-", "_")
    if normalized_key in INTERNAL_PATH_KEYS:
        return "<server-bound-path>"
    if any(keyword in normalized_key for keyword in STORAGE_SENSITIVE_KEYS):
        return "<redacted>"
    if redact_content and lowered == "content" and isinstance(value, str):
        return {
            "redacted": True,
            "length": len(value),
            "sha256": stable_json_hash(value),
        }
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            child_key: _sanitize_value(child_value, key=child_key, redact_content=redact_content)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, key=None, redact_content=redact_content) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)
