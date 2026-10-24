"""Safe resource command errors; no stored rows or infrastructure diagnostics."""

import re


class ResourceError(Exception):
    def __init__(self, code):
        self.code = code if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) else "resource_request_invalid"
        self.status_code = 404 if self.code == "resource_reservation_not_found" else 409
        super().__init__(self.code)
