from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)


class SafeError(BaseModel):
    detail: str


def _strip_title(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


Title = Annotated[
    str,
    BeforeValidator(_strip_title),
    Field(min_length=1, max_length=120),
]
Body = Annotated[str, Field(max_length=4000)]


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    body: Body = ""


class NotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    body: Body | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_values(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(
            name in value and value[name] is None for name in ("title", "body")
        ):
            raise ValueError("null values are not accepted")
        return value

    @model_validator(mode="after")
    def require_a_field(self) -> "NotePatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
