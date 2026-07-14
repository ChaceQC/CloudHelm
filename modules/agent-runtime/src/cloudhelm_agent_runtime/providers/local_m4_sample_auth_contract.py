"""受控 auth/profile recipe 的 OpenAPI 与 SQLite 设计草案。"""

from typing import Any


def auth_profile_openapi() -> dict[str, Any]:
    """返回与受控 sample 实现一致的 OpenAPI 3.1 草案。"""

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "CloudHelm Sample Auth/Profile API",
            "version": "0.1.0",
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"}
            },
            "schemas": {
                "RegisterRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["email", "password", "display_name"],
                    "properties": {
                        "email": {
                            "type": "string",
                            "format": "email",
                            "maxLength": 254,
                        },
                        "password": {
                            "type": "string",
                            "minLength": 8,
                            "maxLength": 128,
                        },
                        "display_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50,
                        },
                    },
                },
                "LoginRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["email", "password"],
                    "properties": {
                        "email": {
                            "type": "string",
                            "format": "email",
                            "maxLength": 254,
                        },
                        "password": {
                            "type": "string",
                            "maxLength": 128,
                        },
                    },
                },
                "ProfileUpdateRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["display_name"],
                    "properties": {
                        "display_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50,
                        }
                    },
                },
                "PublicUser": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "email", "display_name", "created_at"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "email": {"type": "string", "format": "email"},
                        "display_name": {"type": "string"},
                        "created_at": {
                            "type": "string",
                            "format": "date-time",
                        },
                    },
                },
                "AccessTokenResponse": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["access_token", "token_type", "expires_in"],
                    "properties": {
                        "access_token": {"type": "string", "minLength": 1},
                        "token_type": {"type": "string", "const": "bearer"},
                        "expires_in": {
                            "type": "integer",
                            "const": 1800,
                        },
                    },
                },
                "ErrorDetail": {
                    "type": "object",
                    "required": ["code", "message"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
                "ErrorResponse": {
                    "type": "object",
                    "required": ["detail"],
                    "properties": {
                        "detail": {
                            "$ref": "#/components/schemas/ErrorDetail"
                        }
                    },
                },
            },
        },
        "paths": {
            "/auth/register": {
                "post": {
                    "summary": "注册用户",
                    "requestBody": _request("RegisterRequest"),
                    "responses": {
                        "201": _response("用户创建成功", "PublicUser"),
                        "409": _response(
                            "email 已注册",
                            "ErrorResponse",
                        ),
                        "422": {"description": "请求校验失败"},
                    },
                }
            },
            "/auth/login": {
                "post": {
                    "summary": "登录并签发短期 token",
                    "requestBody": _request("LoginRequest"),
                    "responses": {
                        "200": _response(
                            "登录成功",
                            "AccessTokenResponse",
                        ),
                        "401": _response("凭据无效", "ErrorResponse"),
                        "422": {"description": "请求校验失败"},
                    },
                }
            },
            "/profile": {
                "get": {
                    "summary": "读取当前用户资料",
                    "security": [{"BearerAuth": []}],
                    "responses": {
                        "200": _response("当前用户资料", "PublicUser"),
                        "401": _response(
                            "token 无效或过期",
                            "ErrorResponse",
                        ),
                    },
                },
                "patch": {
                    "summary": "更新当前用户显示名称",
                    "security": [{"BearerAuth": []}],
                    "requestBody": _request("ProfileUpdateRequest"),
                    "responses": {
                        "200": _response("资料更新成功", "PublicUser"),
                        "401": _response(
                            "token 无效或过期",
                            "ErrorResponse",
                        ),
                        "422": {"description": "请求校验失败"},
                    },
                },
            },
        },
    }


def auth_profile_db_schema() -> dict[str, Any]:
    """返回与 recipe `UserRepository.initialize()` 一致的 SQLite schema。"""

    return {
        "database": "sqlite",
        "tables": [
            {
                "name": "users",
                "columns": [
                    "id TEXT PRIMARY KEY",
                    "email TEXT NOT NULL UNIQUE",
                    "password_hash TEXT NOT NULL",
                    "display_name TEXT NOT NULL",
                    "created_at TEXT NOT NULL",
                ],
            }
        ],
        "notes": [
            "注册和登录先去除 email 首尾空白并转为小写。",
            "token 不落库；由 HMAC 签名载荷携带 user_id 与过期时间。",
            "测试使用临时 SQLite，默认运行使用受控 `.cloudhelm` 数据目录。",
        ],
    }


def _request(schema_name: str) -> dict[str, Any]:
    """构造必填 JSON request body。"""

    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "$ref": f"#/components/schemas/{schema_name}"
                }
            }
        },
    }


def _response(description: str, schema_name: str) -> dict[str, Any]:
    """构造 JSON response 引用。"""

    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "$ref": f"#/components/schemas/{schema_name}"
                }
            }
        },
    }
