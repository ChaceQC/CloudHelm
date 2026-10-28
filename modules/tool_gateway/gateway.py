"""The model can call only routes explicitly supplied by the application."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.exceptions import CallDeferred, ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart


Route = Callable[[dict[str, Any], str], Awaitable[Any]]
ToolAdmission = Callable[[str], Awaitable[None]]


class GatewayFailure(Exception):
    """A fixed code, without the route's exception or input."""


class ToolGateway:
    def __init__(self, routes: Mapping[str, Route], admit_tool: ToolAdmission):
        self._routes = dict(routes)
        self._admit_tool = admit_tool

    def tools(self) -> list[Tool[Any]]:
        if not self._routes:
            return []

        async def dispatch_tool(ctx: RunContext[Any], name: str, arguments: dict[str, Any]) -> Any:
            """Call an available CloudHelm route with its validated business arguments."""
            if name not in self._routes:
                raise GatewayFailure("tool_not_allowed")
            response = next(message for message in reversed(ctx.messages) if isinstance(message, ModelResponse))
            calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
            if len(calls) > 8 or len(calls) > 1 and any(
                part.args_as_dict().get("name") in {"submit_operation", "await_operation",
                    "workspace.create_file", "workspace.apply_patch", "workspace.prepare_environment",
                    "workspace.control_environment"} for part in calls
            ):
                raise ModelRetry("Submit, edit or await one operation in a separate tool batch; query batches allow at most 8 calls.")
            try:
                await self._admit_tool(name)
            except Exception:
                raise GatewayFailure("tool_admission_denied") from None
            try:
                return await self._routes[name](arguments, ctx.tool_call_id)
            except (CallDeferred, ModelRetry):
                raise
            except Exception:
                raise GatewayFailure("tool_execution_failed") from None

        # A provider may return several calls even when parallel calls are disabled.
        description = "Call a permitted CloudHelm route: " + ", ".join(sorted(self._routes))
        return [Tool(dispatch_tool, description=description, sequential=True)]
