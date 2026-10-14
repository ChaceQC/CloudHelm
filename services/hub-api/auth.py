"""HTTP authentication proofs are resolved from the selected bounded API pool."""

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from database.uow import UnitOfWork
from modules.identity.authentication import _token_digest, authenticate_current
from modules.identity.actors import AuthenticatedActor
from modules.identity.errors import IdentityError
from .errors import ApiRequestError
from .runtime import ApiRuntime

_BEARER = HTTPBearer(auto_error=False, scheme_name="CloudHelmSession", bearerFormat="opaque")


def get_runtime(request: Request) -> ApiRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise ApiRequestError("service_not_ready", 503)
    return runtime


def _authenticate(request: Request, credentials, purpose: str) -> AuthenticatedActor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise IdentityError("authentication_required")
    bearer = SecretStr(credentials.credentials)
    _token_digest(bearer)
    runtime = get_runtime(request)
    engine = runtime.pools.control if purpose == "control" else runtime.pools.normal
    with UnitOfWork(engine) as uow:
        actor = authenticate_current(uow, bearer)
    request.state.actor = actor
    return actor


def normal_actor(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> AuthenticatedActor:
    return _authenticate(request, credentials, "normal")


def control_actor(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> AuthenticatedActor:
    return _authenticate(request, credentials, "control")
