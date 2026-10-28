"""The model can call only routes explicitly supplied by the application."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic_ai import Tool


Route = Callable[[dict[str, Any]], Awaitable[Any]]
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

        async def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
            """Call an available CloudHelm route with its validated business arguments."""
            if name not in self._routes:
                raise GatewayFailure("tool_not_allowed")
            try:
                await self._admit_tool(name)
            except Exception:
                raise GatewayFailure("tool_admission_denied") from None
            try:
                return await self._routes[name](arguments)
            except Exception:
                raise GatewayFailure("tool_execution_failed") from None

        # A provider may return several calls even when parallel calls are disabled.
        description = "Call a permitted CloudHelm route: " + ", ".join(sorted(self._routes))
        return [Tool(dispatch_tool, description=description, sequential=True)]
