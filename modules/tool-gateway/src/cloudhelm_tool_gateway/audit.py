"""工具调用审计摘要工具。

审计摘要用于写入 Platform API 的 `tool_calls` 和 `event_logs`，只保存
参数键、低敏短值、hash 和输出摘要，不把文件内容、密钥或完整命令输出
原样暴露给控制台。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SENSITIVE_KEYWORDS = ("password", "token", "secret", "key", "credential", "cookie", "content")


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
