"""真实测试工具参数模型。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TestRunPytestArguments(BaseModel):
    """在受控 workspace 中执行 pytest 并生成 JUnit XML。"""

    model_config = ConfigDict(extra="forbid")

    workspace_root: str = Field(description="服务端绑定的 Task workspace。")
    cwd: str = Field(default=".", description="相对 workspace 的执行目录。")
    pytest_args: list[str] = Field(default_factory=lambda: ["-q"], max_length=24)
    junit_path: str = Field(
        default=".cloudhelm/artifacts/junit.xml",
        description="相对 workspace 的 JUnit XML 路径。",
    )
    timeout_seconds: int = Field(default=180, ge=1, le=300)
    max_output_chars: int = Field(default=12000, ge=200, le=50000)

    @field_validator("pytest_args")
    @classmethod
    def reject_unsafe_pytest_arguments(cls, value: list[str]) -> list[str]:
        """拒绝改写工作目录、执行任意 Python 或覆盖平台报告路径的参数。"""

        denied_prefixes = (
            "--rootdir",
            "--confcutdir",
            "--basetemp",
            "--junitxml",
            "--junit-xml",
            "-c",
        )
        for argument in value:
            if "\x00" in argument or any(
                argument == prefix or argument.startswith(f"{prefix}=")
                for prefix in denied_prefixes
            ):
                raise ValueError(f"pytest argument is managed by CloudHelm: {argument}")
        return value
