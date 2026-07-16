"""M7 部署与服务健康证据的严格内部类型。"""

from __future__ import annotations

import re
from typing import Annotated, TypeAlias

from pydantic import (
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    StrictStr,
    WithJsonSchema,
)

HEALTH_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SENSITIVE_HEALTH_KEY_PATTERN = (
    r"(^|_)(token|tokens|secret|secrets|credential|credentials|"
    r"password|passwords|cookie|cookies|authorization|raw_logs|"
    r"stdout|stderr|log|logs)(_|$)"
)

_SENSITIVE_HEALTH_KEY_RE = re.compile(
    SENSITIVE_HEALTH_KEY_PATTERN,
    re.IGNORECASE,
)

HealthKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=HEALTH_KEY_PATTERN,
    ),
]
HealthText = Annotated[StrictStr, Field(max_length=512)]
HealthScalar: TypeAlias = (
    HealthText | StrictBool | StrictInt | FiniteFloat | None
)

HEALTH_EVIDENCE_JSON_SCHEMA = {
    "type": "object",
    "maxProperties": 32,
    "propertyNames": {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": HEALTH_KEY_PATTERN,
        "not": {
            "pattern": SENSITIVE_HEALTH_KEY_PATTERN,
        },
    },
    "additionalProperties": {
        "anyOf": [
            {
                "type": "string",
                "maxLength": 512,
            },
            {
                "type": "boolean",
            },
            {
                "type": "integer",
            },
            {
                "type": "number",
            },
            {
                "type": "null",
            },
        ]
    },
}

HealthEvidence: TypeAlias = Annotated[
    dict[HealthKey, HealthScalar],
    Field(max_length=32),
    WithJsonSchema(HEALTH_EVIDENCE_JSON_SCHEMA),
]


def validate_health_evidence(
    value: dict[str, HealthScalar] | None,
) -> dict[str, HealthScalar] | None:
    """拒绝健康摘要中的凭据、原始日志和其他敏感字段名。"""

    if value is None:
        return None
    sensitive_keys = [
        key for key in value if _SENSITIVE_HEALTH_KEY_RE.search(key)
    ]
    if sensitive_keys:
        raise ValueError("健康证据包含敏感或原始日志字段。")
    return value
