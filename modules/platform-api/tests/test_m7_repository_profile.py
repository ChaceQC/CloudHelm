"""M7-2B1 RepositoryProfile 与 snapshot 配置白盒测试。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.core.repository_config import (
    RepositoryProfileConfig,
)
from cloudhelm_platform_api.providers.repository_profile_provider import (
    RepositoryProfileProvider,
)
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    build_repository_binding_public_snapshot,
    repository_binding_internal_snapshot_hash,
)
from conftest import M7_REPOSITORY_PROFILES


def test_repository_profile_file_configuration_errors_are_stable(
    tmp_path: Path,
) -> None:
    """非法 profile 统一映射为稳定配置错误。"""

    profile_file = tmp_path / "repository-profiles.json"
    profile_file.write_text(
        json.dumps(
            {
                "profiles": {
                    "bad": {
                        "provider": "gitea",
                        "repository_external_id": "42",
                        "repository_owner": "cloudhelm",
                        "repository_name": "sample",
                        "clone_url": "http://gitea.example.test/sample.git",
                        "default_branch": "main",
                        "credential_ref": "test/repository/primary",
                        "workflow_id": ".gitea/workflows/ci.yml",
                        "release_ref_prefix": "refs/heads/cloudhelm/candidates",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={},
            repository_profiles_file=str(profile_file),
            repository_credentials={},
        )
    )

    with pytest.raises(ServiceError) as error:
        provider.get_profile("bad")
    assert error.value.code == "repository_profile_configuration_invalid"
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "clone_url",
    [
        "https://gitea.example.test/cloudhelm/sample.git?",
        "https://gitea.example.test/cloudhelm/sample.git#",
    ],
)
def test_repository_profile_rejects_empty_query_or_fragment_marker(
    clone_url: str,
) -> None:
    """即使 query/fragment 为空，也拒绝 URL 中出现分隔标记。"""

    with pytest.raises(ValidationError):
        RepositoryProfileConfig(
            **{
                **M7_REPOSITORY_PROFILES["test-primary"],
                "clone_url": clone_url,
            }
        )


def test_repository_profile_rejects_duplicate_env_and_file_key(
    tmp_path: Path,
) -> None:
    """同一 profile key 在环境变量与文件重复时返回稳定配置错误。"""

    profile_file = tmp_path / "repository-profiles.json"
    profile_file.write_text(
        json.dumps(
            {
                "profiles": {
                    "test-primary": M7_REPOSITORY_PROFILES["test-primary"]
                }
            }
        ),
        encoding="utf-8",
    )
    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={
                "test-primary": M7_REPOSITORY_PROFILES["test-primary"]
            },
            repository_profiles_file=str(profile_file),
            repository_credentials={},
        )
    )

    with pytest.raises(ServiceError) as error:
        provider.get_profile("test-primary")
    assert error.value.code == "repository_profile_configuration_invalid"


@pytest.mark.parametrize(
    "raw_content",
    [
        (
            '{"profiles":{"duplicate":'
            + json.dumps(M7_REPOSITORY_PROFILES["test-primary"])
            + ',"duplicate":'
            + json.dumps(M7_REPOSITORY_PROFILES["test-secondary"])
            + "}}"
        ),
        '{"profiles":{},"unexpected":{}}',
    ],
)
def test_repository_profile_file_rejects_ambiguous_json(
    tmp_path: Path,
    raw_content: str,
) -> None:
    """重复 JSON key 和 wrapper 额外字段均 fail closed。"""

    profile_file = tmp_path / "repository-profiles.json"
    profile_file.write_text(raw_content, encoding="utf-8")
    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={},
            repository_profiles_file=str(profile_file),
            repository_credentials={},
        )
    )

    with pytest.raises(ServiceError) as error:
        provider.get_profile("duplicate")
    assert error.value.code == "repository_profile_configuration_invalid"


@pytest.mark.parametrize("file_mode", ["missing", "invalid_utf8"])
def test_repository_profile_file_read_errors_are_stable(
    tmp_path: Path,
    file_mode: str,
) -> None:
    """文件缺失或 UTF-8 非法时隐藏路径并返回统一配置错误。"""

    profile_file = tmp_path / "repository-profiles.json"
    if file_mode == "invalid_utf8":
        profile_file.write_bytes(b"\xff\xfe\x00")
    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={},
            repository_profiles_file=str(profile_file),
            repository_credentials={},
        )
    )

    with pytest.raises(ServiceError) as error:
        provider.get_profile("test-primary")
    assert error.value.code == "repository_profile_configuration_invalid"
    assert str(profile_file) not in error.value.message


def test_repository_profile_rejects_blank_credential() -> None:
    """只含空白的 credential 与缺失配置使用同一不可用错误。"""

    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={
                "test-primary": M7_REPOSITORY_PROFILES["test-primary"]
            },
            repository_credentials={"test/repository/primary": "   "},
        )
    )
    profile = provider.get_profile("test-primary")

    with pytest.raises(ServiceError) as error:
        provider.get_credential(profile.credential_ref)
    assert error.value.code == "repository_profile_unusable"


def test_repository_profile_example_is_valid() -> None:
    """仓库内非敏感示例文件可被真实 Provider 读取。"""

    example_path = (
        Path(__file__).resolve().parents[1]
        / "repository-profiles.example.json"
    )
    provider = RepositoryProfileProvider(
        Settings(
            repository_profiles={},
            repository_profiles_file=str(example_path),
            repository_credentials={
                "secret/cloudhelm/gitea/sample-api": "test-only-token"
            },
        )
    )

    profile = provider.get_profile("demo-gitea-repository")
    assert profile.provider == "gitea"
    assert profile.repository_external_id == "42"
    assert provider.get_credential(
        profile.credential_ref
    ).get_secret_value() == "test-only-token"


def test_internal_snapshot_hash_covers_each_internal_field() -> None:
    """profile key、clone URL、credential ref 任一变化都改变 freshness hash。"""

    public_snapshot = build_repository_binding_public_snapshot(
        provider="gitea",
        repository_external_id="42",
        repository_owner="cloudhelm",
        repository_name="sample",
        default_branch="main",
        workflow_id=".gitea/workflows/ci.yml",
        release_ref_prefix="refs/heads/cloudhelm/candidates",
    )

    def snapshot_hash(
        *,
        profile_key: str = "primary",
        clone_url: str = "https://gitea.example.test/cloudhelm/sample.git",
        credential_ref: str = "credential/primary",
    ) -> str:
        return repository_binding_internal_snapshot_hash(
            public_snapshot=public_snapshot,
            profile_key=profile_key,
            clone_url=clone_url,
            credential_ref=credential_ref,
        )

    hashes = {
        snapshot_hash(),
        snapshot_hash(profile_key="alias"),
        snapshot_hash(
            clone_url="https://gitea.example.test/cloudhelm/sample-v2.git"
        ),
        snapshot_hash(credential_ref="credential/rotated"),
    }
    assert len(hashes) == 4
