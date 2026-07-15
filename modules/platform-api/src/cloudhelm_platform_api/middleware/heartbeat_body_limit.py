"""Remote Agent heartbeat 请求体积门禁。"""

import json
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEARTBEAT_PATH = "/api/remote-agents/heartbeat"


class HeartbeatBodyLimitMiddleware:
    """在 JSON 解析和 machine-auth 前限制 heartbeat 原始 body bytes。

    该端点正文很小，middleware 最多缓存配置上限内的 ASGI request messages，
    再原样回放给 FastAPI。Content-Length 缺失时仍按实际 chunk 累计，避免用
    chunked body 绕过门禁。
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != _HEARTBEAT_PATH
        ):
            await self.app(scope, receive, send)
            return

        headers = {
            name.lower(): value
            for name, value in scope.get("headers", [])
        }
        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > self.max_body_bytes:
                    await self._reject(scope, headers, send)
                    return
            except ValueError:
                pass

        messages: list[Message] = []
        body_parts: list[bytes] = []
        received = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                body = message.get("body", b"")
                body_parts.append(body)
                received += len(body)
                if received > self.max_body_bytes:
                    await self._reject(scope, headers, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        scope.setdefault("state", {})["heartbeat_body"] = b"".join(
            body_parts
        )
        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        await self.app(scope, replay, send)

    async def _reject(
        self,
        scope: Scope,
        headers: dict[bytes, bytes],
        send: Send,
    ) -> None:
        """返回与 Platform API 统一错误结构一致的 413。"""

        incoming_trace = headers.get(b"x-trace-id")
        trace_id = (
            incoming_trace.decode("utf-8", errors="replace")
            if incoming_trace
            else str(uuid4())
        )
        scope.setdefault("state", {})["trace_id"] = trace_id
        content = json.dumps(
            {
                "code": "request_body_too_large",
                "message": "Remote Agent heartbeat 请求体超过大小限制。",
                "detail": {
                    "max_body_bytes": self.max_body_bytes,
                },
                "trace_id": trace_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(content)).encode("ascii")),
                    (b"x-trace-id", trace_id.encode("utf-8")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": content,
                "more_body": False,
            }
        )
