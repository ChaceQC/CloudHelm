"""环境变量配置和 machine secret 文件读取测试。"""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from cloudhelm_remote_agent.config import Settings
from cloudhelm_remote_agent.credentials import read_machine_secret
from cloudhelm_remote_agent.exceptions import CredentialError
from conftest import TEST_TARGET_ID


def test_settings_read_all_remote_agent_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """运行配置均使用固定 CLOUDHELM_REMOTE_AGENT_ 前缀。"""

    credential_file = (tmp_path / "env.secret").resolve()
    credential_file.write_bytes(b"environment-secret")
    credential_file.chmod(0o600)
    values = {
        "PLATFORM_API_BASE_URL": "https://platform.example.test",
        "TARGET_ID": str(TEST_TARGET_ID),
        "AGENT_ID": "agent-env",
        "KEY_ID": "key-env",
        "CREDENTIAL_FILE": str(credential_file),
        "HEARTBEAT_SECONDS": "30",
        "REQUEST_TIMEOUT": "7.5",
        "VERSION": "0.5.1",
        "CAPABILITIES": json.dumps(["version", "heartbeat"]),
    }
    for name, value in values.items():
        monkeypatch.setenv(f"CLOUDHELM_REMOTE_AGENT_{name}", value)

    settings = Settings()

    assert settings.platform_api_origin == "https://platform.example.test"
    assert settings.target_id == TEST_TARGET_ID
    assert settings.agent_id == "agent-env"
    assert settings.key_id == "key-env"
    assert settings.credential_file == credential_file
    assert settings.heartbeat_seconds == 30
    assert settings.request_timeout == 7.5
    assert settings.version == "0.5.1"
    assert settings.capabilities == ("heartbeat", "version")
    assert "secret" not in Settings.model_fields


def test_settings_reject_http_non_uuid_and_invalid_identity(
    tmp_path: Path,
) -> None:
    """Remote Agent 启动前拒绝与 Platform machine-auth 不兼容的配置。"""

    credential_file = (tmp_path / "machine.secret").resolve()
    credential_file.write_bytes(b"environment-secret")
    credential_file.chmod(0o600)
    base = {
        "platform_api_base_url": "https://platform.example.test",
        "target_id": str(TEST_TARGET_ID),
        "agent_id": "agent-01",
        "key_id": "key-01",
        "credential_file": credential_file,
    }
    invalid_cases = (
        {**base, "platform_api_base_url": "http://platform.example.test"},
        {**base, "target_id": "target-env"},
        {**base, "agent_id": "bad agent"},
        {**base, "key_id": "bad key"},
    )

    for values in invalid_cases:
        with pytest.raises(ValidationError):
            Settings(**values)


def test_platform_ca_bundle_must_be_existing_absolute_file(
    tmp_path: Path,
) -> None:
    """自定义 CA 配置只接受真实绝对文件。"""

    credential_file = (tmp_path / "machine.secret").resolve()
    credential_file.write_bytes(b"environment-secret")
    credential_file.chmod(0o600)
    ca_bundle = (tmp_path / "platform-ca.pem").resolve()
    ca_bundle.write_text("test-ca", encoding="utf-8")

    settings = Settings(
        platform_api_base_url="https://platform.example.test",
        target_id=TEST_TARGET_ID,
        agent_id="agent-01",
        key_id="key-01",
        credential_file=credential_file,
        platform_ca_bundle=ca_bundle,
    )
    assert settings.platform_ca_bundle == ca_bundle

    with pytest.raises(ValidationError):
        Settings(
            platform_api_base_url="https://platform.example.test",
            target_id=TEST_TARGET_ID,
            agent_id="agent-01",
            key_id="key-01",
            credential_file=credential_file,
            platform_ca_bundle=tmp_path / "missing.pem",
        )


def test_machine_secret_is_read_only_from_file(tmp_path: Path) -> None:
    """读取时去除文件首尾空白，但不把正文写回配置或日志。"""

    credential_file = tmp_path / "machine.secret"
    credential_file.write_bytes(b"\nfile-only-secret\n")
    credential_file.chmod(0o600)

    assert read_machine_secret(credential_file) == b"file-only-secret"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"", "credential_file_empty"),
        (b" \r\n\t", "credential_file_empty"),
    ],
)
def test_empty_machine_secret_has_stable_error(
    tmp_path: Path,
    content: bytes,
    expected_code: str,
) -> None:
    """空白凭据不会进入 HMAC，并返回稳定错误码。"""

    credential_file = tmp_path / "empty.secret"
    credential_file.write_bytes(content)
    credential_file.chmod(0o600)

    with pytest.raises(CredentialError) as error:
        read_machine_secret(credential_file)

    assert error.value.code == expected_code
    assert str(credential_file) not in error.value.message


@pytest.mark.skipif(os.name == "nt", reason="Windows 使用服务账号 ACL，不用 POSIX mode 位判定。")
def test_posix_group_readable_credential_is_rejected(tmp_path: Path) -> None:
    """POSIX 上 group/other 任意权限均视为明显不安全。"""

    credential_file = tmp_path / "wide.secret"
    credential_file.write_bytes(b"not-safe")
    credential_file.chmod(0o640)

    with pytest.raises(CredentialError) as error:
        read_machine_secret(credential_file)

    assert error.value.code == "credential_file_insecure_permissions"


def test_symlink_credential_is_rejected_when_supported(tmp_path: Path) -> None:
    """凭据读取不跟随 symlink，防止目标在检查后被替换。"""

    source = tmp_path / "source.secret"
    source.write_bytes(b"source-secret")
    source.chmod(0o600)
    link = tmp_path / "linked.secret"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("当前 Windows 权限未启用符号链接创建。")

    with pytest.raises(CredentialError) as error:
        read_machine_secret(link)

    assert error.value.code == "credential_file_symlink"


def test_credential_larger_than_limit_is_rejected(tmp_path: Path) -> None:
    """读取使用同一 fd，并对实际读取字节执行 4096 bytes 上限。"""

    credential_file = tmp_path / "large.secret"
    credential_file.write_bytes(b"x" * 4097)
    credential_file.chmod(0o600)

    with pytest.raises(CredentialError) as error:
        read_machine_secret(credential_file)

    assert error.value.code == "credential_file_too_large"


def test_credential_replacement_between_lstat_and_open_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """路径在检查与打开之间被原子替换时不得读取替换后的 secret。"""

    credential_file = tmp_path / "machine.secret"
    credential_file.write_bytes(b"original-secret")
    credential_file.chmod(0o600)
    replacement = tmp_path / "replacement.secret"
    replacement.write_bytes(b"replacement-secret")
    replacement.chmod(0o600)
    original_open = os.open
    replaced = False

    def replacing_open(path, flags, mode=0o777):
        nonlocal replaced
        if not replaced and Path(path) == credential_file:
            os.replace(replacement, credential_file)
            replaced = True
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "open", replacing_open)
    with pytest.raises(CredentialError) as error:
        read_machine_secret(credential_file)

    assert error.value.code == "credential_file_changed"
