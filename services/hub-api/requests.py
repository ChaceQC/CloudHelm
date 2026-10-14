"""Document fixed bodies while validating the original bounded UTF-8 JSON bytes."""

from fastapi import Body, Request

from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.identity_contracts import parse_request
from .errors import ApiRequestError

MAX_BODY_BYTES = 65_536


def parse_public_body(raw: bytes, schema: type[Contract]) -> Contract:
    if len(raw) > MAX_BODY_BYTES:
        raise ApiRequestError("request_body_too_large", 413)
    try:
        return parse_request(raw.decode("utf-8", errors="strict"), schema)
    except (UnicodeError, ValueError, RecursionError):
        raise ApiRequestError("request_schema_invalid", 422) from None


def strict_body(schema: type[Contract]):
    async def dependency(request: Request, documented_body=Body(...)) -> Contract:
        # The annotated body supplies OpenAPI. Only original bytes feed canonical parsing.
        return parse_public_body(await request.body(), schema)

    dependency.__annotations__["documented_body"] = schema
    dependency.__name__ = f"parse_{schema.__name__}"
    return dependency
