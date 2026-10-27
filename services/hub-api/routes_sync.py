"""Authenticated finite SSE subscriptions; every batch releases its DB transaction."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from database.uow import DatabaseFailure
from modules.collaboration.errors import TaskBoundaryError
from modules.identity.actors import AuthenticatedActor
from modules.identity.errors import IdentityError
from modules.sync.application import SyncApplication
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p1.sync import SyncSnapshot
from .auth import control_actor, get_runtime

router = APIRouter(prefix="/api/projects/{project_id}", tags=["sync"])
ControlActor = Annotated[AuthenticatedActor, Depends(control_actor)]


def _application(request):
    runtime = get_runtime(request)
    return SyncApplication(runtime.pools.control, runtime.sync_epoch)


@router.get("/snapshot", response_model=SyncSnapshot, name="sync.snapshot")
def snapshot(request: Request, project_id: Identifier, actor: ControlActor):
    return _application(request).snapshot(actor, project_id)


def _frame(event, value):
    return "event: " + event + "\ndata: " + json.dumps(value, separators=(",", ":")) + "\n\n"


@router.get("/events", name="sync.events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}, "description": "p1-sync-r1 invalidation batches"}})
async def events(request: Request, project_id: Identifier, actor: ControlActor,
                 stream_id: Identifier, after: Annotated[int, Query(ge=0, le=9007199254740991)],
                 permission_revision: Annotated[int, Query(ge=0, le=9007199254740991)]):
    application = _application(request)
    # Validate before headers so the caller receives a normal 401/403/409 response.
    first = await run_in_threadpool(application.poll, actor, project_id, stream_id, after, permission_revision)

    async def generate():
        batch = first
        deadline = asyncio.get_running_loop().time() + 25
        while True:
            yield _frame("batch", batch.model_dump(mode="json"))
            if asyncio.get_running_loop().time() >= deadline or await request.is_disconnected():
                return
            await asyncio.sleep(2)
            try:
                batch = await run_in_threadpool(application.poll, actor, project_id, stream_id,
                                               batch.cursor, permission_revision)
            except IdentityError:
                yield _frame("access_revoked", {"code": "authorization_changed"})
                return
            except TaskBoundaryError as error:
                yield _frame("reset", {"code": error.code})
                return
            except DatabaseFailure:
                yield _frame("unavailable", {"code": "sync_unavailable"})
                return

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
