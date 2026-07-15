"""Remote Agent CLI 配置失败与日志脱敏回归测试。"""

import asyncio
import logging
from pathlib import Path

import httpx2
import pytest

from cloudhelm_remote_agent import cli
from cloudhelm_remote_agent.config import get_settings
from cloudhelm_remote_agent.heartbeat import HeartbeatClient
from conftest import TEST_TARGET_ID, make_settings


def test_load_settings_handles_complex_environment_parse_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """复杂环境变量不是 JSON 时返回稳定失败，不泄露原始配置。"""

    credential_file = tmp_path / "machine.secret"
    for name, value in {
        "PLATFORM_API_BASE_URL": "https://platform.example.test",
        "TARGET_ID": str(TEST_TARGET_ID),
        "AGENT_ID": "agent-01",
        "KEY_ID": "key-2026-07-a",
        "CREDENTIAL_FILE": str(credential_file),
        "CAPABILITIES": "not-json-sensitive-value",
    }.items():
        monkeypatch.setenv(f"CLOUDHELM_REMOTE_AGENT_{name}", value)

    get_settings.cache_clear()
    try:
        with caplog.at_level(
            logging.ERROR,
            logger="cloudhelm_remote_agent.cli",
        ):
            assert cli._load_settings() is None
    finally:
        get_settings.cache_clear()

    assert "remote_agent_configuration_invalid" in caplog.text
    assert "not-json-sensitive-value" not in caplog.text
    assert "platform.example.test" not in caplog.text


def test_configure_logging_suppresses_platform_api_request_url(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """成功心跳不得由 HTTP client 的 INFO 日志记录控制面入口。"""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "target_id": str(TEST_TARGET_ID),
                "agent_id": "agent-01",
                "status": "online",
                "accepted_at": "2026-07-16T00:00:00Z",
                "next_heartbeat_after_seconds": 20,
            },
        )

    httpx_logger = logging.getLogger("httpx2")
    httpcore_logger = logging.getLogger("httpcore2")
    original_httpx_level = httpx_logger.level
    original_httpcore_level = httpcore_logger.level
    try:
        cli._configure_logging()
        with caplog.at_level(logging.INFO):
            asyncio.run(
                HeartbeatClient(
                    make_settings(tmp_path),
                    transport=httpx2.MockTransport(handler),
                ).send_once()
            )
    finally:
        httpx_logger.setLevel(original_httpx_level)
        httpcore_logger.setLevel(original_httpcore_level)

    assert "platform.example.test" not in caplog.text
    assert "/api/remote-agents/heartbeat" not in caplog.text
