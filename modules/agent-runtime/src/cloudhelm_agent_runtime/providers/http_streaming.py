"""OpenAI-compatible HTTP 流辅助函数。

该模块只负责无状态协议解析：按 SSE 空行边界读取 `data:`，从完成响应中
提取文本，并解析服务端建议的 Retry-After。鉴权、重试次数和业务 schema
校验仍由 Provider 负责。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any


def iter_sse_data(response) -> Iterator[str]:  # noqa: ANN001
    """从 HTTP 响应按 SSE 空行边界提取拼接后的 `data:` 内容。"""

    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


def extract_responses_text(response_json: dict[str, Any]) -> str:
    """从 Responses API 完成对象中提取首个 `output_text`。"""

    direct = response_json.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    for item in response_json.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text:
                    return text
    raise ValueError("responses API output does not contain output_text")


def parse_retry_after_seconds(headers: Mapping[str, str] | None, detail: str) -> float | None:
    """优先解析 Retry-After header，再读取兼容端点 JSON 错误体。"""

    if headers is not None:
        header_value = headers.get("Retry-After")
        if header_value is not None:
            try:
                return max(0.0, float(header_value))
            except ValueError:
                header_value = None
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return None
    candidates = [payload.get("retry_after")]
    nested_error = payload.get("error")
    if isinstance(nested_error, dict):
        candidates.append(nested_error.get("retry_after"))
    for candidate in candidates:
        if isinstance(candidate, (int, float)):
            return max(0.0, float(candidate))
    return None
