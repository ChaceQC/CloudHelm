"""平台 API 配置。

配置通过环境变量注入，避免把数据库地址、端口、环境、版本和后续外部
服务地址写死在业务代码中。M2 开始接入 PostgreSQL，所有数据库连接均
从 `CLOUDHELM_DATABASE_URL` 读取，便于本地开发、测试和后续部署环境
使用不同配置。M4 增加 Agent provider 配置；M5 增加 Tool Gateway 入口；
M6 增加受控 sample workspace、Artifact 与本地开发工具配置。
真实密钥只允许通过环境变量
注入，不能提交到 Git。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    """平台 API 运行配置。

    环境变量使用 `CLOUDHELM_` 前缀。集中声明配置可以避免业务层硬编码
    部署差异，同时让测试夹具能够通过环境变量切换隔离数据库。
    """

    model_config = SettingsConfigDict(env_prefix="CLOUDHELM_", extra="ignore")

    env: str = Field(default="development", description="当前运行环境。")
    version: str = Field(default="0.5.0", description="当前服务版本。")
    service_name: str = Field(
        default="cloudhelm-platform-api",
        description="健康检查和观测日志使用的服务名。",
    )
    database_url: str = Field(
        default="postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm",
        description="SQLAlchemy 数据库连接串，M2 默认指向本地 PostgreSQL。",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis 预留连接串；M2 暂不接入生产路径。",
    )
    tool_rate_limit_calls: int = Field(
        default=60,
        ge=1,
        description="M5 单进程内每个任务或 AgentRun 在窗口内允许的工具调用次数。",
    )
    tool_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="M5 Tool Gateway 滑动窗口秒数。",
    )
    tool_workspace_roots: list[str] = Field(
        default_factory=list,
        description="Tool Gateway 允许访问的本地 workspace 根目录；空列表默认拒绝文件和命令工具。",
    )
    tool_max_timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=600,
        description="M6 pytest、安全扫描和本地命令的统一最大超时。",
    )
    tool_max_output_chars: int = Field(
        default=50000,
        ge=1000,
        le=1000000,
        description="Tool Gateway stdout/stderr 默认最大保存字符数。",
    )
    m6_sample_repo_root: str = Field(
        default=str(_REPOSITORY_ROOT / "examples" / "sample-repo-python"),
        description="M6 受控 sample repo fixture 根目录。",
    )
    m6_recipe_root: str = Field(
        default=str(
            _REPOSITORY_ROOT
            / "examples"
            / "sample-repo-python"
            / "demo-issues"
        ),
        description="M6 已批准本地 execution recipe 的受控根目录。",
    )
    m6_workspace_root: str = Field(
        default=str(_REPOSITORY_ROOT / "output" / "m6-workspaces"),
        description="M6 Task 独立 Git workspace 父目录。",
    )
    artifact_root: str = Field(
        default=str(_REPOSITORY_ROOT / "output" / "artifacts"),
        description="Artifact 文件内容的受控本地存储根目录。",
    )
    artifact_preview_bytes: int = Field(
        default=65536,
        ge=1024,
        le=65536,
        description="Artifact 详情 API 最大预览字节数。",
    )
    m6_branch_prefix: str = Field(
        default="codex",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$",
        description="M6 本地任务分支前缀。",
    )
    agent_provider: str = Field(
        default="local_structured",
        description="M4 Agent provider，支持 local_structured 或 openai_compatible。",
    )
    llm_provider: str | None = Field(
        default=None,
        description="外部 LLM 供应商名称，仅用于审计和运行记录。",
    )
    llm_model: str | None = Field(
        default=None,
        description="外部 LLM 模型名称；local_structured provider 可为空。",
    )
    llm_api_base: str | None = Field(
        default=None,
        description="OpenAI 兼容 API 根地址；不提交真实私有地址。",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="OpenAI 兼容 API Key；只能由环境变量注入。",
    )
    llm_api_mode: Literal["responses", "chat_completions"] = Field(
        default="responses",
        description="外部模型 API 模式；GPT-5.6 类推理模型优先使用 Responses API。",
    )
    llm_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] = Field(
        default="xhigh",
        description="OpenAI 推理强度；当前 gpt-5.6-sol 真实流程固定使用 xhigh，同时保留 max 兼容值。",
    )
    llm_reasoning_summary: Literal["auto", "concise", "detailed"] | None = Field(
        default="auto",
        description="Responses reasoning summary 模式；隐藏思维链仍只以 encrypted content 回放。",
    )
    llm_reasoning_context: Literal["current_turn", "all_turns"] | None = Field(
        default="all_turns",
        description="Responses 多轮 reasoning 上下文；root/child conversation 各自独立。",
    )
    llm_max_output_tokens: int = Field(
        default=32768,
        ge=256,
        le=131072,
        description="外部模型最大输出 token，需同时容纳 reasoning token 和最终结构化输出。",
    )
    llm_timeout_seconds: int = Field(
        default=120,
        ge=1,
        le=600,
        description="单次外部模型 HTTP 请求超时秒数。",
    )
    llm_max_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        description="外部模型请求或结构化响应失败时的总尝试次数。",
    )
    llm_retry_backoff_seconds: float = Field(
        default=1.0,
        ge=0,
        le=60,
        description="外部模型重试的初始退避秒数，后续按 2 的幂增长。",
    )
    llm_explicit_cache_breakpoint: bool = Field(
        default=False,
        description=(
            "是否发送 Responses 显式 Prompt Cache 协议："
            "prompt_cache_options.mode=explicit 与 prompt_cache_breakpoint；"
            "仅对明确支持该协议的端点启用。"
        ),
    )
    llm_user_agent: str = Field(
        default="codex_cli_rs/0.0.0 (CloudHelm)",
        min_length=1,
        description="外部模型 HTTP User-Agent；Codex 路由兼容端点需要 codex_cli_rs 标识。",
    )
    llm_originator: str = Field(
        default="codex_cli_rs",
        min_length=1,
        description="外部模型请求 originator 审计头。",
    )
    agent_max_subagent_depth: int = Field(
        default=2,
        ge=1,
        le=8,
        description="显式 subagent conversation 的最大树深度。",
    )
    agent_max_subagent_threads: int = Field(
        default=4,
        ge=1,
        le=32,
        description="单个 Task 同时 active 的最大子 Agent 会话数。",
    )
    cors_origins: list[str] = Field(
        default=["http://127.0.0.1:5173", "http://localhost:5173"],
        description="本地控制台允许访问平台 API 的来源。",
    )

    @property
    def effective_tool_workspace_roots(self) -> list[str]:
        """合并显式 allowlist 与 M6 固定 fixture/workspace 根目录。"""

        ordered = [
            *self.tool_workspace_roots,
            self.m6_sample_repo_root,
            self.m6_workspace_root,
        ]
        return list(dict.fromkeys(ordered))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存平台 API 配置。

    返回:
        `Settings` 实例。缓存可避免每个请求重复解析环境变量。
    """

    return Settings()
