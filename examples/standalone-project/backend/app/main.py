import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.database import build_database
from app.readiness import database_matches_head
from app.routes import router as notes_router
from app.schemas import SafeError


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def create_app(database_url: str | None) -> FastAPI:
    engine, session_factory = build_database(database_url)
    application = FastAPI(
        title="CloudHelm Notes Backend Reference",
        version="0.0.0",
        docs_url=None,
        redoc_url=None,
    )
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.include_router(notes_router)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "request validation failed"})

    @application.exception_handler(Exception)
    async def internal_error_handler(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", responses={503: {"model": SafeError}})
    def readiness() -> dict[str, str]:
        if not database_matches_head(engine, BACKEND_ROOT / "alembic.ini"):
            raise HTTPException(status_code=503, detail="not ready")
        return {"status": "ready"}

    return application


app = create_app(os.environ.get("DATABASE_URL"))
