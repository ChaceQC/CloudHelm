"""Remote Agent pytest 夹具。"""

from pathlib import Path
from uuid import UUID

from cloudhelm_remote_agent.config import Settings

TEST_TARGET_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_settings(
    tmp_path: Path,
    *,
    secret: bytes = b"remote-agent-test-secret-32-bytes",
    heartbeat_seconds: float = 0.1,
) -> Settings:
    """创建只指向临时凭据文件的隔离配置。"""

    credential_file = tmp_path / "machine.secret"
    credential_file.write_bytes(secret)
    credential_file.chmod(0o600)
    return Settings(
        platform_api_base_url="https://platform.example.test",
        target_id=TEST_TARGET_ID,
        agent_id="agent-01",
        key_id="key-2026-07-a",
        credential_file=credential_file,
        heartbeat_seconds=heartbeat_seconds,
        request_timeout=2.0,
        version="0.5.1",
        capabilities=["heartbeat", "health"],
    )
