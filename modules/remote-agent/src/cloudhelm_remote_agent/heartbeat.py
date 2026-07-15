"""发往 Platform API 的签名 heartbeat client。"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import json
import logging
from uuid import uuid4

import httpx2
from pydantic import ValidationError

from cloudhelm_remote_agent.auth import (
    authentication_headers,
    sign_request,
)
from cloudhelm_remote_agent.config import Settings
from cloudhelm_remote_agent.credentials import read_machine_secret
from cloudhelm_remote_agent.exceptions import CredentialError, HeartbeatError
from cloudhelm_remote_agent.schemas import HeartbeatAck, HeartbeatPayload

HEARTBEAT_PATH = "/api/remote-agents/heartbeat"
_MAX_HEARTBEAT_ACK_BYTES = 16 * 1024
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """返回包含 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def serialize_heartbeat(payload: HeartbeatPayload) -> bytes:
    """用 UTF-8、紧凑分隔符和 key 排序生成固定 JSON bytes。"""

    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class HeartbeatClient:
    """使用真实 HTTPX AsyncClient 周期性提交签名 heartbeat。

    测试可注入 ``MockTransport``；未注入时会创建默认网络 transport。
    ``trust_env=False`` 禁止代理环境变量改变请求目的地，redirect 默认拒绝。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        """保存非敏感配置和测试注入点，不缓存 machine secret。"""

        self.settings = settings
        self._transport = transport
        self._clock = clock
        self._nonce_factory = nonce_factory or (lambda: uuid4().hex)

    def _create_http_client(self) -> httpx2.AsyncClient:
        """创建显式 timeout、无代理继承、无 redirect 的 HTTP client。"""

        timeout = httpx2.Timeout(
            connect=self.settings.request_timeout,
            read=self.settings.request_timeout,
            write=self.settings.request_timeout,
            pool=self.settings.request_timeout,
        )
        return httpx2.AsyncClient(
            base_url=self.settings.platform_api_origin,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            verify=(
                str(self.settings.platform_ca_bundle)
                if self.settings.platform_ca_bundle is not None
                else True
            ),
            limits=httpx2.Limits(
                max_connections=4,
                max_keepalive_connections=2,
                keepalive_expiry=30.0,
            ),
            transport=self._transport,
        )

    def _build_request(self) -> tuple[bytes, dict[str, str]]:
        """读取最新凭据并生成与实际发送 bytes 完全一致的请求。"""

        now = self._clock().astimezone(UTC)
        timestamp = str(int(now.timestamp()))
        nonce = self._nonce_factory()
        payload = HeartbeatPayload(
            target_id=self.settings.target_id,
            agent_id=self.settings.agent_id,
            agent_version=self.settings.version,
            capabilities=list(self.settings.capabilities),
            reported_at=now,
        )
        body = serialize_heartbeat(payload)
        secret = read_machine_secret(self.settings.credential_file)
        signature = sign_request(
            secret,
            "POST",
            HEARTBEAT_PATH,
            timestamp,
            nonce,
            body,
        )
        headers = dict(
            authentication_headers(
                target_id=str(self.settings.target_id),
                agent_id=self.settings.agent_id,
                key_id=self.settings.key_id,
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
            )
        )
        headers["Content-Type"] = "application/json"
        return body, headers

    async def _send_with_client(
        self,
        client: httpx2.AsyncClient,
    ) -> HeartbeatAck:
        """发送一次 heartbeat，并严格校验状态码、JSON 和响应身份。"""

        body, headers = self._build_request()
        request = client.build_request(
            "POST",
            HEARTBEAT_PATH,
            content=body,
            headers=headers,
        )
        response = await client.send(request, stream=True)
        try:
            if response.status_code != 200:
                raise HeartbeatError(
                    "heartbeat_http_error",
                    "Platform API 拒绝或未处理 heartbeat。",
                    status_code=response.status_code,
                )
            content_length = response.headers.get("Content-Length")
            if (
                content_length is not None
                and content_length.isdecimal()
                and int(content_length) > _MAX_HEARTBEAT_ACK_BYTES
            ):
                raise HeartbeatError(
                    "heartbeat_response_too_large",
                    "Platform API heartbeat 响应超过大小限制。",
                    status_code=response.status_code,
                )
            chunks: list[bytes] = []
            received = 0
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > _MAX_HEARTBEAT_ACK_BYTES:
                    raise HeartbeatError(
                        "heartbeat_response_too_large",
                        "Platform API heartbeat 响应超过大小限制。",
                        status_code=response.status_code,
                    )
                chunks.append(chunk)
            try:
                ack = HeartbeatAck.model_validate(
                    json.loads(b"".join(chunks))
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
                raise HeartbeatError(
                    "heartbeat_response_invalid",
                    "Platform API heartbeat 响应结构无效。",
                    status_code=response.status_code,
                ) from exc
        finally:
            await response.aclose()
        if (
            ack.target_id != self.settings.target_id
            or ack.agent_id != self.settings.agent_id
        ):
            raise HeartbeatError(
                "heartbeat_response_identity_mismatch",
                "Platform API heartbeat 响应身份不匹配。",
                status_code=response.status_code,
            )
        return ack

    async def send_once(self) -> HeartbeatAck:
        """创建真实 AsyncClient，发送并校验一次 heartbeat。"""

        async with self._create_http_client() as client:
            return await self._send_with_client(client)

    async def run_forever(
        self,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """循环发送 heartbeat，失败后按有界间隔恢复，停止时关闭连接池。

        日志只保存稳定错误码、HTTP 状态和异常类型，不输出请求 header、
        body、凭据路径或 secret。
        """

        stop = stop_event or asyncio.Event()
        async with self._create_http_client() as client:
            while not stop.is_set():
                delay = self.settings.heartbeat_seconds
                try:
                    ack = await self._send_with_client(client)
                    delay = min(
                        float(ack.next_heartbeat_after_seconds),
                        self.settings.heartbeat_seconds,
                    )
                except CredentialError as exc:
                    logger.warning("heartbeat_failed code=%s", exc.code)
                except HeartbeatError as exc:
                    logger.warning(
                        "heartbeat_failed code=%s status=%s",
                        exc.code,
                        exc.status_code,
                    )
                except httpx2.HTTPError as exc:
                    logger.warning(
                        "heartbeat_failed code=heartbeat_transport_error type=%s",
                        type(exc).__name__,
                    )
                except Exception as exc:  # pragma: no cover - 最后一道持续运行保护
                    logger.error(
                        "heartbeat_failed code=heartbeat_unexpected_error type=%s",
                        type(exc).__name__,
                    )

                if stop.is_set():
                    break
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=delay,
                    )
                except TimeoutError:
                    continue
