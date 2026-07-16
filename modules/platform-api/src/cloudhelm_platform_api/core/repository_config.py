"""M7 server-controlled repository profile 配置与 Git ref 校验。"""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)

_FORBIDDEN_REF_CHARACTERS = frozenset("~^:?*[\\")


def validate_git_head_ref(value: str, *, max_length: int) -> str:
    """校验完整 `refs/heads/...`，对齐 M7 数据库 CHECK 与 Git ref 规则。

    该函数只处理纯字符串，不在 API 事务中启动 Git 子进程。它同时供
    RepositoryProfile 与后续 Candidate target ref 复用。
    """

    if not 12 <= len(value) <= max_length:
        raise ValueError("Git ref 长度非法。")
    if not value.startswith("refs/heads/"):
        raise ValueError("Git ref 必须使用完整 refs/heads/ 前缀。")
    if value.endswith(("/", ".")):
        raise ValueError("Git ref 不能以斜杠或点结尾。")
    if ".." in value or "//" in value or "@{" in value:
        raise ValueError("Git ref 包含禁止序列。")
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in _FORBIDDEN_REF_CHARACTERS
        or character.isspace()
        for character in value
    ):
        raise ValueError("Git ref 包含禁止字符。")

    components = value.split("/")
    if any(
        not component
        or component.startswith(".")
        or component.endswith(".lock")
        for component in components
    ):
        raise ValueError("Git ref component 格式非法。")
    return value


class RepositoryProfileConfig(BaseModel):
    """普通 API 只能按 key 引用的 Gitea repository 服务端配置。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    provider: Literal["gitea"] = Field(
        default="gitea",
        description="M7 固定 repository provider。",
    )
    repository_external_id: str = Field(
        min_length=1,
        max_length=255,
        description="Gitea repository 稳定外部 ID。",
    )
    repository_owner: str = Field(
        min_length=1,
        max_length=255,
        description="Gitea repository owner。",
    )
    repository_name: str = Field(
        min_length=1,
        max_length=255,
        description="Gitea repository name。",
    )
    clone_url: HttpUrl = Field(
        description="服务端受控 HTTPS clone URL。",
    )
    default_branch: str = Field(
        min_length=1,
        max_length=255,
        description="远端默认分支。",
    )
    credential_ref: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
        description="服务端 repository credential 引用。",
    )
    workflow_id: str = Field(
        min_length=1,
        max_length=512,
        description="固定 Gitea workflow identity。",
    )
    release_ref_prefix: str = Field(
        min_length=12,
        max_length=240,
        description="完整候选发布 refs/heads/... 前缀。",
    )

    @field_validator("clone_url")
    @classmethod
    def require_safe_clone_url(cls, value: HttpUrl) -> HttpUrl:
        """Clone URL 必须使用 HTTPS，且不能携带 userinfo、query 或 fragment。"""

        if value.scheme != "https":
            raise ValueError("Repository clone URL 必须使用 HTTPS。")
        if (
            value.username is not None
            or value.password is not None
            or value.query is not None
            or value.fragment is not None
        ):
            raise ValueError("Repository clone URL 不能包含凭据、query 或 fragment。")
        return value

    @field_validator(
        "repository_external_id",
        "repository_owner",
        "repository_name",
        "default_branch",
        "workflow_id",
    )
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        """显式拒绝清理后为空的 identity/config 字段。"""

        if not value:
            raise ValueError("Repository profile 字段不能为空。")
        return value

    @field_validator("default_branch")
    @classmethod
    def validate_default_branch(cls, value: str) -> str:
        """默认分支必须能组成安全完整 head ref。"""

        validate_git_head_ref(
            f"refs/heads/{value}",
            max_length=1024,
        )
        return value

    @field_validator("release_ref_prefix")
    @classmethod
    def validate_release_ref_prefix(cls, value: str) -> str:
        """候选发布前缀必须是无尾斜杠的安全完整 head ref。"""

        return validate_git_head_ref(value, max_length=240)
