"""Tool Gateway API 路由。"""

from uuid import UUID

from fastapi import APIRouter, status

from cloudhelm_platform_api.api.deps import DbSession
from cloudhelm_platform_api.schemas.common import PageResponse
from cloudhelm_platform_api.schemas.tool_call import ToolCallRead
from cloudhelm_platform_api.schemas.tool_gateway import ToolDeclarationRead, ToolGatewayCallCreate
from cloudhelm_platform_api.services.tool_gateway_service import ToolGatewayService

router = APIRouter(tags=["tool-gateway"])


@router.get("/api/tool-gateway/tools", response_model=PageResponse[ToolDeclarationRead], summary="列出 Tool Gateway 工具")
def list_tool_gateway_tools(db: DbSession) -> PageResponse[ToolDeclarationRead]:
    """读取当前注册的本地工具声明。"""

    return ToolGatewayService(db).list_tools()


@router.post(
    "/api/tasks/{task_id}/tool-gateway/call",
    response_model=ToolCallRead,
    status_code=status.HTTP_201_CREATED,
    summary="通过 Tool Gateway 执行本地工具",
)
def call_tool_gateway(task_id: UUID, payload: ToolGatewayCallCreate, db: DbSession) -> ToolCallRead:
    """执行低风险工具；L3/L4 或策略要求审批时只创建审批请求。"""

    return ToolGatewayService(db).call_tool(task_id, payload)
