"""Stable errors containing no submitted input or database diagnostics."""

from packages.contracts.p1.identity_contracts import IdentityErrorCode, IdentityErrorResponse
from packages.contracts.p1.identity_results import ManagementRejectionCode


_STATUS_CODES: dict[str, int] = {
    "authentication_required": 401,
    "authentication_failed": 401,
    "identity_not_current": 403,
    "permission_denied": 403,
    "role_action_denied": 403,
    "delegation_not_current": 403,
    "authorization_binding_mismatch": 403,
    "policy_not_current": 403,
    "recorded_actor_not_found": 409,
}


class IdentityError(Exception):
    def __init__(self, code: IdentityErrorCode) -> None:
        if code not in _STATUS_CODES:
            raise ValueError("unknown_identity_error")
        self.code = code
        self.status_code = _STATUS_CODES[code]
        super().__init__(code)

    def as_response(self) -> IdentityErrorResponse:
        return IdentityErrorResponse(code=self.code)


class ManagementRejection(Exception):
    """An authorized domain rejection which may be stored as the original result."""

    def __init__(self, code: ManagementRejectionCode) -> None:
        self.code = code
        super().__init__(code)
