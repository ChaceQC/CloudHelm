"""No HTTP error includes request values, authentication material, or driver text."""

import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from database.commands import CommandConflict
from database.readiness import DatabaseNotReady
from database.uow import DatabaseFailure
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.errors import IdentityError
from modules.execution.errors import ResourceError
from modules.projects.source_operations import SourceImportError
from .contracts import ApiErrorResponse
from .denials import store_identity_denial


class ApiRequestError(HTTPException):
    def __init__(self, code: str, status_code: int = 422) -> None:
        self.code, self.status_code = code, status_code
        super().__init__(status_code=status_code, detail=code)


def error_response(code: str, status: int, *, object_ids=()) -> JSONResponse:
    safe_code = code if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "request_failed"
    body = ApiErrorResponse(code=safe_code, blocking_object_ids=tuple(object_ids))
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, content=body.model_dump(mode="json", exclude_defaults=True), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResourceError)
    async def resource_error(request: Request, error: ResourceError):
        return error_response(error.code, error.status_code)

    @app.exception_handler(IdentityError)
    async def identity_error(request: Request, error: IdentityError):
        await run_in_threadpool(store_identity_denial, request, error)
        return error_response(error.code, error.status_code)

    @app.exception_handler(ApiRequestError)
    async def api_error(request: Request, error: ApiRequestError):
        return error_response(error.code, error.status_code)

    @app.exception_handler(TaskBoundaryError)
    async def task_error(request: Request, error: TaskBoundaryError):
        status = error.status_code if error.status_code in {403, 404, 409, 422} else 500
        identifiers = error.object_ids if status in {409, 422} and hasattr(request.state, "actor") else ()
        return error_response(error.code, status, object_ids=identifiers)

    @app.exception_handler(CommandConflict)
    async def command_error(request: Request, error: CommandConflict):
        code = str(error)
        if code not in {"idempotency_digest_conflict", "idempotency_scope_mismatch"}:
            code = "command_conflict"
        return error_response(code, 409)

    @app.exception_handler(SourceImportError)
    async def source_error(request: Request, error: SourceImportError):
        code = str(error)
        return error_response(code, 404 if code == "source_import_not_found" else 409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return error_response("request_schema_invalid", 422)

    @app.exception_handler(ResponseValidationError)
    async def response_error(request: Request, error: ResponseValidationError):
        return error_response("response_unavailable", 500)

    @app.exception_handler(DatabaseFailure)
    @app.exception_handler(DatabaseNotReady)
    async def database_error(request: Request, error):
        return error_response("database_unavailable", 503)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        codes = {401: "authentication_required", 403: "permission_denied", 404: "not_found", 405: "method_not_allowed"}
        return error_response(codes.get(error.status_code, "request_rejected"), error.status_code)
