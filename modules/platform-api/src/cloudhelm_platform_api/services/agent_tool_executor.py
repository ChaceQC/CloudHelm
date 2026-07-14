"""M6 Agent tool call 到应用级 Tool Gateway 的适配器。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from typing import Any
from uuid import UUID

from cloudhelm_agent_runtime.providers import (
    ProviderToolCall,
    ProviderToolExecutionResult,
)
from cloudhelm_agent_runtime.providers.exchange import ToolExecutorFatalError
from cloudhelm_tool_gateway import ToolGateway
from cloudhelm_tool_gateway.audit import stable_json_hash
from pydantic import ValidationError

from cloudhelm_platform_api.core.config import Settings
from cloudhelm_platform_api.schemas.common import RiskLevel
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead
from cloudhelm_platform_api.schemas.tool_gateway import ToolGatewayCallCreate
from cloudhelm_platform_api.services.local_workspace_resolver import (
    LocalWorkspaceResolver,
)
from cloudhelm_platform_api.services.tool_gateway_service import (
    ToolGatewayService,
)

_LOSSLESS_RESULT_TOOLS = frozenset({"git.diff", "git.format_patch"})


class AgentToolExecutor:
    """绑定 Task workspace，执行工具并收集持久化 ToolCall DTO。"""

    def __init__(
        self,
        session,
        gateway: ToolGateway,
        settings: Settings,
        *,
        task_id: UUID,
        agent_run_id: UUID,
        workflow_step: str,
        attempt: int,
        approved_calls: Iterable[tuple[str, dict[str, Any]]] = (),
    ) -> None:
        self.gateway = gateway
        self.settings = settings
        self.task_id = task_id
        self.agent_run_id = agent_run_id
        self.workflow_step = workflow_step
        self.attempt = attempt
        self.workspace = LocalWorkspaceResolver(settings)
        self.service = ToolGatewayService(session, gateway)
        self.tool_calls: list[ToolCallRead] = []
        self._raw_results: dict[UUID, dict[str, Any]] = {}
        self._approved_calls: Counter[str] = Counter()
        self._used_calls: Counter[str] = Counter()
        for tool_name, arguments in approved_calls:
            self.approve_call(tool_name, arguments)

    def __call__(
        self,
        call: ProviderToolCall,
    ) -> ProviderToolExecutionResult:
        """执行一个模型 function/custom call。"""

        declaration = self.gateway.registry.get(call.name)
        if declaration is None:
            return ProviderToolExecutionResult(
                status="failed",
                result={"summary": f"未注册工具：{call.name}。"},
                error_code="unknown_tool",
            )
        arguments = self._bind_arguments(
            call.name,
            declaration.bound_arguments,
            call.arguments,
        )
        fingerprint, policy_error = self._execution_policy(
            call,
            declaration,
            arguments,
        )
        try:
            call_result = self.service.call_tool_for_agent(
                self.task_id,
                ToolGatewayCallCreate(
                    agent_run_id=self.agent_run_id,
                    provider_call_id=call.call_id,
                    provider_item_type=call.item_type,
                    tool_name=call.name,
                    risk_level=RiskLevel(declaration.risk_level.value),
                    idempotency_key=self._idempotency_key(call.call_id),
                    arguments=arguments,
                    reason=(
                        f"M6 {self.workflow_step} attempt {self.attempt} "
                        f"执行 {call.name}。"
                    ),
                ),
                execution_policy_fingerprint=fingerprint,
                execution_policy_error=policy_error,
            )
        except Exception as exc:
            raise ToolExecutorFatalError(
                f"Platform Tool Gateway 持久化失败：{type(exc).__name__}"
            ) from exc
        record = call_result.record
        if (
            call.name in _LOSSLESS_RESULT_TOOLS
            and call_result.raw_result_json is not None
        ):
            self._raw_results[record.id] = deepcopy(
                call_result.raw_result_json
            )
        self.tool_calls.append(record)
        provider_status = record.status.value
        provider_error = record.error_code
        if provider_status not in {
            "succeeded",
            "failed",
            "waiting_approval",
        }:
            provider_status = "failed"
            provider_error = provider_error or "tool_call_cancelled"
        return ProviderToolExecutionResult(
            status=provider_status,
            result={
                "tool_call_id": str(record.id),
                "summary": record.result_summary
                or f"{record.tool_name} 返回 {record.status.value}。",
                "result_json": record.result_json or {},
                "stdout_summary": record.stdout_summary,
                "stderr_summary": record.stderr_summary,
                "duration_ms": record.duration_ms,
            },
            error_code=provider_error,
        )

    def result_json(self, record: ToolCallRead) -> dict[str, Any]:
        """返回工具执行期原始结果；普通工具继续使用持久化安全投影。"""

        raw = self._raw_results.get(record.id)
        if raw is not None:
            return deepcopy(raw)
        if (
            record.tool_name in _LOSSLESS_RESULT_TOOLS
            and record.status.value == "succeeded"
        ):
            raise ToolExecutorFatalError(
                f"{record.tool_name} 缺少可验证的原始工具结果。"
            )
        return deepcopy(record.result_json or {})

    def execute(
        self,
        *,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ProviderToolExecutionResult:
        """供编排器执行确定性的门禁/Git 调用，并沿用同一审计路径。"""

        self.approve_call(tool_name, arguments)
        return self(
            ProviderToolCall(
                call_id=call_id,
                name=tool_name,
                arguments=arguments,
            )
        )

    def approve_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        """登记一个由当前 workflow 代码或已审批 recipe 产生的精确调用。"""

        declaration = self.gateway.registry.get(tool_name)
        if declaration is None:
            raise ValueError(f"cannot approve unknown tool: {tool_name}")
        bound = self._bind_arguments(
            tool_name,
            declaration.bound_arguments,
            arguments,
        )
        fingerprint = self._fingerprint(declaration, bound)
        self._approved_calls[fingerprint] += 1

    def _execution_policy(
        self,
        call: ProviderToolCall,
        declaration,
        arguments: dict[str, Any],
    ) -> tuple[str, tuple[str, str] | None]:
        """验证调用名称和规范化参数属于本步骤已审批调用多重集。"""

        try:
            fingerprint = self._fingerprint(declaration, arguments)
        except ValidationError:
            fingerprint = stable_json_hash(
                {"tool_name": call.name, "arguments": arguments}
            )
            return fingerprint, (
                "m6_execution_recipe_call_not_approved",
                "工具参数未匹配当前 M6 execution recipe。",
            )
        replay = any(
            item.provider_call_id == call.call_id for item in self.tool_calls
        )
        if replay:
            return fingerprint, None
        if self._used_calls[fingerprint] >= self._approved_calls[fingerprint]:
            return fingerprint, (
                "m6_execution_recipe_call_not_approved",
                "工具名称、参数或调用次数未匹配当前 M6 execution recipe。",
            )
        self._used_calls[fingerprint] += 1
        return fingerprint, None

    @staticmethod
    def _fingerprint(declaration, arguments: dict[str, Any]) -> str:
        """以工具 Pydantic 默认值规范化参数，再移除服务端绑定字段。"""

        parsed = declaration.input_model.model_validate(arguments).model_dump(
            mode="json"
        )
        provider_arguments = {
            key: value
            for key, value in parsed.items()
            if key not in declaration.bound_arguments
        }
        return stable_json_hash(
            {
                "tool_name": declaration.name,
                "arguments": provider_arguments,
            }
        )

    def _bind_arguments(
        self,
        tool_name: str,
        bound_arguments: tuple[str, ...],
        raw_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """覆盖模型不可控的 workspace、repo 和 scaffold 路径字段。"""

        arguments = deepcopy(raw_arguments)
        for field_name in bound_arguments:
            arguments.pop(field_name, None)
        if "workspace_root" in bound_arguments:
            arguments["workspace_root"] = (
                str(self.workspace.workspace_parent)
                if tool_name == "scaffold.prepare_workspace"
                else str(self.workspace.workspace(self.task_id))
            )
        if "source_root" in bound_arguments:
            arguments["source_root"] = str(self.workspace.sample_repo)
        if "target_directory" in bound_arguments:
            arguments["target_directory"] = f"{self.task_id}/repo"
        if "repo_root" in bound_arguments:
            arguments["repo_root"] = str(
                self.workspace.workspace(self.task_id)
            )
        return arguments

    def _idempotency_key(self, provider_call_id: str) -> str:
        """形成任务内、步骤内稳定且不超过数据库限制的幂等键。"""

        return (
            f"m6:{self.workflow_step}:{self.attempt}:{provider_call_id}"
        )[:128]
