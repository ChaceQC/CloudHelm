"""Current human session projection; no public credential issuance or bootstrap."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from database.uow import UnitOfWork
from modules.identity.actors import AuthenticatedActor
from modules.identity.authentication import current_identity
from packages.contracts.p1.identity_contracts import CurrentIdentity
from .auth import control_actor, get_runtime

router = APIRouter(prefix="/api/auth", tags=["identity"])


@router.get("/me", response_model=CurrentIdentity, name="identity.current")
def current_session(request: Request, actor: Annotated[AuthenticatedActor, Depends(control_actor)]):
    with UnitOfWork(get_runtime(request).pools.control) as uow:
        return current_identity(uow, actor)
