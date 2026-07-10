"""Tool Gateway 审计脱敏白盒测试。"""

from cloudhelm_tool_gateway.audit import (
    redact_sensitive_text,
    sanitize_arguments_for_storage,
    sanitize_result_for_storage,
)
from cloudhelm_tool_gateway.gateway import create_default_gateway
from cloudhelm_tool_gateway.schemas.tool_call import RiskLevel, ToolCallRequest


def test_arguments_storage_redacts_secrets_and_file_content() -> None:
    """数据库参数快照不得保存密码、Token 或完整写入正文。"""

    stored = sanitize_arguments_for_storage(
        {
            "path": "src/demo.py",
            "content": "print('hello')",
            "password": "db-password",
            "nested": {"api_token": "secret-token", "safe": "value"},
        }
    )

    assert stored["password"] == "<redacted>"
    assert stored["nested"]["api_token"] == "<redacted>"
    assert stored["nested"]["safe"] == "value"
    assert stored["content"]["redacted"] is True
    assert stored["content"]["length"] == len("print('hello')")
    assert stored["content"]["sha256"].startswith("sha256:")


def test_result_and_output_redact_common_credential_patterns() -> None:
    """stdout、stderr 和结果 JSON 中常见凭据模式必须被移除。"""

    token = "sk-abcdefghijklmnopqrstuvwxyz123456"
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    text = redact_sensitive_text(f"token={token}\nAuthorization: Bearer abcdefghijklmnop\n{private_key}")
    assert token not in text
    assert "abcdefghijklmnop" not in text
    assert "BEGIN PRIVATE KEY" not in text

    result = sanitize_result_for_storage(
        {
            "access_token": token,
            "message": f"received {token}",
            "headers": {
                "Authorization": "Bearer abcdefghijklmnop",
                "x-api-key": "plain-api-key",
                "Cookie": "session=plain-cookie",
            },
            "items": [{"password": "plain"}, {"safe": "ok"}],
        }
    )
    assert result["access_token"] == "<redacted>"
    assert token not in result["message"]
    assert result["headers"]["Authorization"] == "<redacted>"
    assert result["headers"]["x-api-key"] == "<redacted>"
    assert result["headers"]["Cookie"] == "<redacted>"
    assert result["items"][0]["password"] == "<redacted>"
    assert result["items"][1]["safe"] == "ok"


def test_failed_validation_result_and_audit_are_sanitized() -> None:
    """参数校验失败也必须脱敏错误 input，并保留完整审计主体。"""

    token = "sk-abcdefghijklmnopqrstuvwxyz123456"
    request = ToolCallRequest(
        task_id="11111111-1111-4111-8111-111111111111",
        agent_run_id=None,
        agent_type=None,
        tool_name="repo.read_file",
        risk_level=RiskLevel.L0,
        idempotency_key="invalid-arguments",
        arguments={"workspace_root": ".", "path": {"token": token}},
        reason="验证错误结果脱敏",
    )
    result = create_default_gateway().execute(request)

    assert result.status == "failed"
    assert result.error_code == "invalid_arguments"
    assert token not in str(result.result_json)
    assert result.audit_json["tool"] == "repo.read_file"
    assert result.audit_json["task_id"] == str(request.task_id)
    assert result.audit_json["idempotency_key"] == "invalid-arguments"
    assert result.audit_json["arguments_hash"].startswith("sha256:")
    assert result.audit_json["status"] == "failed"
