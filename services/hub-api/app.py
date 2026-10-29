"""Static API factory. Only lifespan acquires runtime resources."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from database.settings import DatabaseSettings
from modules.workflow.version import APPLICATION_VERSION
from .contracts import API_SCHEMA_REVISION, ApiErrorResponse, Liveness
from .errors import install_error_handlers
from .middleware import SafeHttpBoundary
from .routes_identity import router as identity_router
from .routes_projects import router as projects_router
from .routes_tasks import router as tasks_router
from .routes_agent import router as agent_router
from .routes_engineering import router as engineering_router
from .routes_development import router as development_router
from .routes_resources import router as resources_router
from .routes_delivery import router as delivery_router
from .routes_sync import router as sync_router
from .routes_integration import router as integration_router
from .routes_previews import router as previews_router
from .preview_proxy import PreviewProxy
from .preview_page import ManagementHostBoundary, router as preview_page_router
from .runtime import start_runtime


def create_app(settings: DatabaseSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = await run_in_threadpool(start_runtime, settings)
        app.state.runtime = runtime
        try:
            yield
        finally:
            app.state.runtime = None
            await run_in_threadpool(runtime.close)

    errors = {code: {"model": ApiErrorResponse} for code in (400, 401, 403, 404, 409, 413, 415, 422, 500, 503)}
    app = FastAPI(
        title="CloudHelm Hub API", version=APPLICATION_VERSION,
        description="Identity, Task control, bounded engineering and shared resource intents and queries.",
        lifespan=lifespan, docs_url=None, redoc_url=None, debug=False,
        redirect_slashes=False, responses=errors,
    )
    app.state.runtime = None
    app.add_middleware(SafeHttpBoundary)
    app.add_middleware(ManagementHostBoundary)
    app.add_middleware(PreviewProxy)
    install_error_handlers(app)
    app.include_router(identity_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(agent_router)
    app.include_router(engineering_router)
    app.include_router(development_router)
    app.include_router(resources_router)
    app.include_router(delivery_router)
    app.include_router(sync_router)
    app.include_router(integration_router)
    app.include_router(previews_router)
    app.include_router(preview_page_router)

    @app.get("/health/live", response_model=Liveness, tags=["health"])
    def liveness():
        return Liveness()

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema["x-cloudhelm-schema-revision"] = API_SCHEMA_REVISION
        return schema

    app.openapi = openapi
    return app
