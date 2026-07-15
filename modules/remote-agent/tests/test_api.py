"""Remote Agent 健康、版本和 capability API 黑盒测试。"""

import asyncio
import json
from pathlib import Path

import httpx2

from cloudhelm_remote_agent.main import create_app
from conftest import make_settings


def _find_repository_root() -> Path:
    """从当前模块目录向上定位共享契约根，兼容 Windows/Linux pyc 路径。"""

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "packages" / "shared-contracts").is_dir():
            return candidate
    raise RuntimeError("未找到 CloudHelm repository root。")


REPOSITORY_ROOT = _find_repository_root()


def test_runtime_endpoints_expose_only_safe_metadata(tmp_path: Path) -> None:
    """三个只读端点返回真实配置，但不泄露 secret、路径或控制面地址。"""

    settings = make_settings(tmp_path, secret=b"endpoint-sensitive-secret")

    async def exercise() -> dict[str, httpx2.Response]:
        transport = httpx2.ASGITransport(app=create_app(settings))
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://remote-agent.test",
        ) as client:
            return {
                "health": await client.get("/health"),
                "version": await client.get("/version"),
                "capabilities": await client.get("/capabilities"),
            }

    responses = asyncio.run(exercise())

    assert responses["health"].status_code == 200
    assert responses["health"].json() == {
        "service": "cloudhelm-remote-agent",
        "status": "ok",
        "version": "0.5.1",
        "agent_id": "agent-01",
        "capabilities": ["health", "heartbeat"],
    }
    assert responses["version"].json() == {
        "service": "cloudhelm-remote-agent",
        "version": "0.5.1",
        "agent_id": "agent-01",
    }
    assert responses["capabilities"].json() == {
        "service": "cloudhelm-remote-agent",
        "agent_id": "agent-01",
        "capabilities": ["health", "heartbeat"],
    }
    combined = "\n".join(response.text for response in responses.values())
    assert "endpoint-sensitive-secret" not in combined
    assert str(settings.credential_file) not in combined
    assert settings.platform_api_origin not in combined


def test_committed_remote_agent_openapi_matches_runtime(
    tmp_path: Path,
) -> None:
    """提交版 Remote Agent OpenAPI 必须与运行时生成结果精确一致。"""

    contract_path = (
        REPOSITORY_ROOT
        / "packages"
        / "shared-contracts"
        / "openapi"
        / "cloudhelm-remote-agent.openapi.yaml"
    )
    with contract_path.open("r", encoding="utf-8") as stream:
        committed = json.load(stream)

    assert committed == create_app(make_settings(tmp_path)).openapi()
