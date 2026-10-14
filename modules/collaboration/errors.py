"""Public-safe Task boundary failures; never include stored records or driver errors."""


class TaskBoundaryError(ValueError):
    def __init__(self, code: str, *, status_code: int = 409, object_ids: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.object_ids = object_ids

    def as_response(self) -> dict[str, object]:
        return {"code": self.code, "blocking_object_ids": list(self.object_ids)}
