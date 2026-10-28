"""Document fixed bodies while validating the original bounded UTF-8 JSON bytes."""

from fastapi import Body, Request

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.identity_contracts import canonical_json
from .errors import ApiRequestError

MAX_BODY_BYTES = 65_536


def strict_body(schema: type[Contract]):
    async def dependency(request: Request, documented_body=Body(...)) -> Contract:
        # FastAPI validates the annotated model once; check the original bytes for JCS rules.
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise ApiRequestError("request_body_too_large", 413)
        try:
            canonical_json(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError, RecursionError):
            raise ApiRequestError("request_schema_invalid", 422) from None
        return documented_body

    dependency.__annotations__["documented_body"] = schema
    dependency.__name__ = f"parse_{schema.__name__}"
    return dependency
