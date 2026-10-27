"""Bounded input and a final exception barrier that never logs request contents."""

import asyncio
import logging
from uuid import uuid4

from .contracts import API_SCHEMA_REVISION
from .errors import ApiRequestError, error_response
from .requests import MAX_BODY_BYTES

_LOGGER = logging.getLogger("cloudhelm.hub_api")


def _headers(scope) -> None:
    grouped = {}
    for key, value in scope.get("headers", ()):
        grouped.setdefault(key.lower(), []).append(value)
    authorization = grouped.get(b"authorization", [])
    if len(authorization) > 1 or any(len(value) > 128 for value in authorization):
        raise ApiRequestError("authentication_failed", 401)
    lengths = grouped.get(b"content-length", [])
    if len(lengths) > 1 or any(not value.isdigit() or len(value) > 10 for value in lengths):
        raise ApiRequestError("request_headers_invalid", 400)
    if lengths and int(lengths[0]) > MAX_BODY_BYTES:
        raise ApiRequestError("request_body_too_large", 413)
    revisions = grouped.get(b"x-cloudhelm-api-schema", [])
    if revisions and revisions != [API_SCHEMA_REVISION.encode("ascii")]:
        raise ApiRequestError("api_schema_not_supported", 409)
    if scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    media = grouped.get(b"content-type", [])
    if len(media) != 1 or media[0].split(b";", 1)[0].strip().lower() != b"application/json":
        raise ApiRequestError("json_content_type_required", 415)
    parameters = media[0].split(b";")[1:]
    if any(value.strip().lower() not in {b"charset=utf-8", b'charset="utf-8"'} for value in parameters):
        raise ApiRequestError("utf8_required", 415)
    if grouped.get(b"content-encoding", [b"identity"]) != [b"identity"]:
        raise ApiRequestError("content_encoding_not_supported", 415)


class SafeHttpBoundary:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started, received, body_complete = False, 0, False
        deadline = asyncio.get_running_loop().time() + 10

        async def limited_receive():
            nonlocal received, body_complete
            if body_complete:
                return await receive()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ApiRequestError("request_body_timeout", 408)
            try:
                message = await asyncio.wait_for(receive(), remaining)
            except TimeoutError:
                raise ApiRequestError("request_body_timeout", 408) from None
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise ApiRequestError("request_body_too_large", 413)
                body_complete = not message.get("more_body", False)
            return message

        async def safe_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [*message.get("headers", ()),
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                    (b"x-cloudhelm-api-schema", API_SCHEMA_REVISION.encode("ascii")),
                    (b"x-request-id", request_id.encode("ascii")),
                ]}
            await send(message)

        try:
            _headers(scope)
            await self.app(scope, limited_receive, safe_send)
        except ApiRequestError as error:
            if not started:
                await error_response(error.code, error.status_code)(scope, receive, safe_send)
        except Exception:
            _LOGGER.error("request_failed code=internal_error request_id=%s", request_id)
            if not started:
                await error_response("internal_error", 500)(scope, receive, safe_send)
            else:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
