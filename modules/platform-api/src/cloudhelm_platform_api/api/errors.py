"""API 错误处理。"""

import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cloudhelm_platform_api.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


def get_trace_id(request: Request) -> str:
    """读取请求 trace_id；缺失时生成兜底值。"""

    return str(getattr(request.state, "trace_id", None) or uuid4())


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: object | None = None,
) -> JSONResponse:
    """构造同时包含响应体和 `X-Trace-Id` 的统一错误响应。"""

    trace_id = get_trace_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "detail": detail,
            "trace_id": trace_id,
        },
        headers={"X-Trace-Id": trace_id},
    )


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """将业务异常转换为统一 JSON 错误。"""

    return error_response(request, exc.status_code, exc.code, exc.message, exc.detail)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """将 FastAPI HTTPException 转换为统一 JSON 错误。"""

    return error_response(request, exc.status_code, "http_error", str(exc.detail))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """将请求校验错误转换为不回显原始输入的统一 JSON 错误。"""

    return error_response(
        request,
        422,
        "validation_error",
        "请求参数校验失败。",
        [
            {
                "type": str(item.get("type", "validation_error")),
                "loc": [
                    value if isinstance(value, (str, int)) else str(value)
                    for value in item.get("loc", ())
                ],
                "message": str(item.get("msg", "请求参数无效。")),
            }
            for item in exc.errors()
        ],
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """隐藏未处理异常细节，并返回带 trace_id 的稳定 500 结构。"""

    logger.error(
        "未处理的 Platform API 异常，trace_id=%s",
        get_trace_id(request),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return error_response(request, 500, "internal_error", "平台 API 发生未处理错误。")


def register_exception_handlers(app: FastAPI) -> None:
    """注册平台 API 统一异常处理器。"""

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
