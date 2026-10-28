"""Dedicated Hub worker-role facade; it never starts an additional DBOS worker."""

from contextlib import asynccontextmanager
from importlib import import_module
import os
import json

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import SecretStr

from modules.collaboration.errors import TaskBoundaryError
from packages.contracts.p1.closeout_contracts import RemoteCloseoutReceipt
from packages.contracts.p1.remote_delivery import (
    RemoteBindings, RemoteHello, RemoteObservationRequest, RemotePermit, RemotePermitRequest, RemotePoll,
    RemotePollResult, RemoteStepResult, RemoteTimeSample,
)


def _unique_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate_key")
    return value


def _invalid_number(value):
    raise ValueError("non_finite_number")


def create_app(application=None):
    @asynccontextmanager
    async def lifespan(app):
        pools = None
        if app.state.remote is None:
            from database.connection import create_business_pools
            from database.settings import load_database_settings
            from modules.delivery.remote_application import RemoteApplication
            from modules.artifacts.content_store import ArtifactStore

            pools = create_business_pools(load_database_settings("worker"))
            artifact_root = os.environ.get("CLOUDHELM_REMOTE_ARTIFACT_ROOT")
            store = ArtifactStore(artifact_root) if artifact_root else None
            app.state.remote = RemoteApplication(pools.control, artifact_store=store)
        try:
            yield
        finally:
            if pools is not None:
                pools.dispose()

    app = FastAPI(title="CloudHelm Remote Agent channel", version="0.7.0", lifespan=lifespan,
        docs_url=None, redoc_url=None, debug=False)
    app.state.remote = application

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.scheme != "https" and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"code": "remote_tls_required"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdecimal() or int(length) > 131072:
            return JSONResponse({"code": "remote_message_too_large"}, status_code=413)
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > 131072:
                return JSONResponse({"code": "remote_message_too_large"}, status_code=413)
        request._body = bytes(body)
        if body:
            try:
                json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_number)
            except (ValueError, UnicodeError):
                return JSONResponse({"code": "remote_request_invalid"}, status_code=422)
        return await call_next(request)

    @app.exception_handler(TaskBoundaryError)
    async def rejected(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status_code)

    @app.exception_handler(ValueError)
    async def unavailable(request, error):
        # Validation/clock/provider errors are not safe to echo.
        return JSONResponse({"code": "remote_gate_unavailable"}, status_code=409)

    @app.exception_handler(Exception)
    async def failed(request, error):
        return JSONResponse({"code": "remote_channel_unavailable"}, status_code=503)

    @app.exception_handler(import_module("fastapi.exceptions").RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({"code": "remote_request_invalid"}, status_code=422)

    def token(authorization):
        if authorization is None or not authorization.startswith("Bearer "):
            raise TaskBoundaryError("remote_authentication_failed", status_code=401)
        return SecretStr(authorization[7:])

    @app.post("/remote/v1/sample", response_model=RemoteTimeSample)
    def sample(body: RemoteHello, authorization: str | None = Header(default=None)):
        return app.state.remote.sample(token(authorization), body)

    @app.post("/remote/v1/poll", response_model=RemotePollResult)
    def poll(body: RemotePoll, authorization: str | None = Header(default=None)):
        return app.state.remote.poll(token(authorization), body)

    @app.post("/remote/v1/bindings", response_model=RemoteBindings)
    def bindings(body: RemotePoll, authorization: str | None = Header(default=None)):
        return app.state.remote.bindings(token(authorization), body)

    @app.post("/remote/v1/observations")
    def observe(body: RemoteObservationRequest, authorization: str | None = Header(default=None)):
        return app.state.remote.observe(token(authorization), body)

    @app.post("/remote/v1/permits", response_model=RemotePermit)
    def permit(body: RemotePermitRequest, authorization: str | None = Header(default=None)):
        return app.state.remote.permit(token(authorization), body)

    @app.post("/remote/v1/results")
    def result(body: RemoteStepResult, authorization: str | None = Header(default=None)):
        return app.state.remote.report(token(authorization), body)

    @app.post("/remote/v1/closeouts", response_model=dict[str, str])
    def closeout(body: RemoteCloseoutReceipt, authorization: str | None = Header(default=None)):
        return app.state.remote.closeout(token(authorization), body)

    @app.get("/remote/v1/artifacts/{operation}/{storage_id}")
    def artifact(operation: str, storage_id: str, authorization: str | None = Header(default=None)):
        stream_context = app.state.remote.open_artifact(token(authorization), operation, storage_id)

        def chunks():
            with stream_context as stream:
                while block := stream.read(65536):
                    yield block

        return StreamingResponse(chunks(), media_type="application/octet-stream")

    return app
