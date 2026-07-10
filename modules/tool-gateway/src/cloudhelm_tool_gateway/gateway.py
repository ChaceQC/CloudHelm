"""Tool Gateway 统一执行流程。"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from cloudhelm_tool_gateway.audit import (
    redact_sensitive_text,
    sanitize_result_for_storage,
    stable_json_hash,
    summarize_mapping,
    truncate_text,
)
from cloudhelm_tool_gateway.policies import PolicyError, ToolPolicy
from cloudhelm_tool_gateway.rate_limit import SlidingWindowRateLimiter
from cloudhelm_tool_gateway.registry import ToolRegistry
from cloudhelm_tool_gateway.schemas.tool_call import ToolCallRequest, ToolCallResult, utc_now
from cloudhelm_tool_gateway.tools import build_default_registry


class ToolGateway:
    """工具调用统一入口。

    执行流程固定为：工具查找 -> 参数校验 -> 风险/审批判断 -> 工具执行 ->
    摘要脱敏 -> 返回结构化结果。Platform API 负责把结果写入数据库事务。
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        policy: ToolPolicy | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.policy = policy or ToolPolicy()
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()

    def list_tools(self) -> list[dict[str, Any]]:
        """列出可注册工具声明。"""

        return [tool.public_dict() for tool in self.registry.list_tools()]

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        """执行一次工具调用并返回可审计结果。"""

        started_at = utc_now()
        started_tick = perf_counter()
        arguments_summary = summarize_mapping(request.arguments)
        declaration = self.registry.get(request.tool_name)
        if declaration is None:
            return self._failed(
                "unknown_tool",
                f"未注册工具：{request.tool_name}",
                started_at,
                started_tick,
                arguments_summary,
                request,
                request.risk_level.value,
            )
        if request.risk_level != declaration.risk_level:
            return self._failed(
                "risk_level_mismatch",
                "请求风险等级与工具注册声明不一致。",
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
            )
        try:
            self.policy.ensure_agent_context(request.agent_run_id, request.agent_type)
            self.policy.ensure_system_call_allowed(request.agent_type, declaration.allow_system_call)
            self.policy.ensure_agent_allowed(request.agent_type, declaration.allowed_agent_types)
        except PolicyError as exc:
            return self._failed(
                exc.code,
                exc.message,
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
            )
        retry_after_seconds = self.rate_limiter.consume(self._rate_limit_key(request))
        if retry_after_seconds is not None:
            return self._failed(
                "rate_limit_exceeded",
                "工具调用超过当前主体的滑动窗口配额。",
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
                detail={"retry_after_seconds": retry_after_seconds},
            )
        try:
            parsed_arguments = declaration.input_model.model_validate(request.arguments)
        except ValidationError as exc:
            return self._failed(
                "invalid_arguments",
                "工具参数未通过 schema 校验。",
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
                detail={"errors": exc.errors(include_url=False)},
            )

        if declaration.requires_approval or self.policy.requires_approval(declaration.risk_level):
            return ToolCallResult(
                status="waiting_approval",
                summary=f"{request.tool_name} 风险等级为 {declaration.risk_level.value}，M5 只创建审批请求，不执行工具。",
                result_json=None,
                duration_ms=self._duration_ms(started_tick),
                started_at=started_at,
                finished_at=None,
                requires_approval=True,
                approval_reason=request.reason,
                arguments_summary=arguments_summary,
                audit_json=self._audit(request, declaration.risk_level.value, "waiting_approval"),
            )

        try:
            output = declaration.handler(parsed_arguments, self.policy)
        except PolicyError as exc:
            return self._failed(
                exc.code,
                exc.message,
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
            )
        except Exception as exc:  # noqa: BLE001 - 工具边界必须把异常转成稳定失败结构。
            return self._failed(
                "tool_execution_error",
                f"工具执行异常：{type(exc).__name__}",
                started_at,
                started_tick,
                arguments_summary,
                request,
                declaration.risk_level.value,
            )

        status = output.get("status", "succeeded")
        error_code = output.get("error_code")
        finished_at = utc_now()
        return ToolCallResult(
            status=status,
            summary=str(output.get("summary") or ("工具执行成功。" if status == "succeeded" else "工具执行失败。")),
            result_json=sanitize_result_for_storage(output.get("result_json")),
            stdout_summary=redact_sensitive_text(
                truncate_text(output.get("stdout_summary"), self.policy.max_output_chars)
            ),
            stderr_summary=redact_sensitive_text(
                truncate_text(output.get("stderr_summary"), self.policy.max_output_chars)
            ),
            duration_ms=self._duration_ms(started_tick),
            started_at=started_at,
            finished_at=finished_at,
            error_code=error_code,
            requires_approval=False,
            arguments_summary=arguments_summary,
            audit_json=self._audit(request, declaration.risk_level.value, status, error_code),
        )

    def _failed(
        self,
        code: str,
        message: str,
        started_at,
        started_tick: float,
        arguments_summary: str,
        request: ToolCallRequest,
        risk_level: str,
        detail: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        """构造脱敏失败结果，并保留与成功路径一致的审计主体。"""

        result_json = {"message": message}
        if detail:
            result_json.update(detail)
        return ToolCallResult(
            status="failed",
            summary=message,
            result_json=sanitize_result_for_storage(result_json),
            duration_ms=self._duration_ms(started_tick),
            started_at=started_at,
            finished_at=utc_now(),
            error_code=code,
            arguments_summary=arguments_summary,
            audit_json=self._audit(request, risk_level, "failed", code),
        )

    def _duration_ms(self, started_tick: float) -> int:
        """计算单次调用耗时。"""

        return max(0, int((perf_counter() - started_tick) * 1000))

    def _rate_limit_key(self, request: ToolCallRequest) -> str:
        """按 AgentRun 或任务形成限流主体，避免不同任务相互占用配额。"""

        if request.agent_run_id:
            return f"agent-run:{request.agent_run_id}"
        return f"task:{request.task_id}"

    def _audit(self, request: ToolCallRequest, risk_level: str, status: str, error_code: str | None = None) -> dict[str, Any]:
        """形成可写入 Platform API 的审计摘要。"""

        audit = {
            "tool": request.tool_name,
            "task_id": str(request.task_id),
            "agent_run_id": str(request.agent_run_id) if request.agent_run_id else None,
            "agent_type": request.agent_type,
            "risk_level": risk_level,
            "idempotency_key": request.idempotency_key,
            "arguments_hash": stable_json_hash(request.arguments),
            "reason_hash": stable_json_hash({"reason": request.reason}),
            "status": status,
        }
        if error_code:
            audit["error_code"] = error_code
        return audit


def create_default_gateway(
    max_calls: int = 60,
    window_seconds: int = 60,
    allowed_workspace_roots: tuple[str | Path, ...] | list[str | Path] = (),
) -> ToolGateway:
    """创建包含 M5 默认工具集和调用限流的 Gateway。"""

    return ToolGateway(
        policy=ToolPolicy(allowed_workspace_roots=allowed_workspace_roots),
        rate_limiter=SlidingWindowRateLimiter(max_calls=max_calls, window_seconds=window_seconds),
    )
