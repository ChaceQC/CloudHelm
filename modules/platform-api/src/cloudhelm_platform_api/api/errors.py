"""API 错误处理。"""

from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cloudhelm_platform_api.services.exceptions import ServiceError


def get_trace_id(request: Request) -> str:
    """读取请求 trace_id；缺失时生成兜底值。"""

    return str(getattr(request.state, "trace_id", None) or uuid4())


def error_payload(request: Request, code: str, message: str, detail: object | None = None) -> dict[str, object | None]:
    """构造统一错误响应体。"""

    return {
        "code": code,
        "message": message,
        "detail": detail,
        "trace_id": get_trace_id(request),
    }


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """将业务异常转换为统一 JSON 错误。"""

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, exc.code, exc.message, exc.detail),
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """将 FastAPI HTTPException 转换为统一 JSON 错误。"""

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, "http_error", str(exc.detail)),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """将请求校验错误转换为统一 JSON 错误。"""

    return JSONResponse(
        status_code=422,
        content=error_payload(request, "validation_error", "请求参数校验失败。", exc.errors()),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册平台 API 统一异常处理器。"""

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
