"""machine-auth canonical request 和 HMAC 固定向量测试。"""

import pytest

from cloudhelm_remote_agent.auth import (
    authentication_headers,
    body_sha256,
    canonical_request,
    sign_request,
)
from cloudhelm_remote_agent.exceptions import HeartbeatError
from conftest import TEST_TARGET_ID

BODY = (
    b'{"agent_id":"agent-01","agent_version":"0.5.1",'
    b'"capabilities":["health","heartbeat"],'
    b'"reported_at":"2026-07-15T00:00:00Z",'
    b'"target_id":"00000000-0000-0000-0000-000000000001"}'
)
SECRET = b"fixed-test-secret-32-bytes-minimum"
TIMESTAMP = "1784073600"
NONCE = "fixed-nonce-0001"
PATH = "/api/remote-agents/heartbeat"


def test_hmac_fixed_vector_matches_contract() -> None:
    """固定向量锁定五行 canonical 和 lowercase hex 签名。"""

    expected_hash = "802af02028e8a9f438617a5ebce98c3085ef3cd69662bfa29207bb39ce415927"
    expected_canonical = (
        "POST\n"
        "/api/remote-agents/heartbeat\n"
        "1784073600\n"
        "fixed-nonce-0001\n"
        f"{expected_hash}"
    )

    assert body_sha256(BODY) == expected_hash
    assert (
        canonical_request("post", PATH, TIMESTAMP, NONCE, expected_hash)
        == expected_canonical
    )
    assert (
        sign_request(SECRET, "POST", PATH, TIMESTAMP, NONCE, BODY)
        == "a4999cf6baaf74d67f743dfcb8c5d8e4e30c9a3149c241062efba6e16865f33e"
    )


def test_any_signed_field_tamper_changes_signature() -> None:
    """body、path、timestamp 和 nonce 均属于签名覆盖范围。"""

    original = sign_request(SECRET, "POST", PATH, TIMESTAMP, NONCE, BODY)
    signatures = {
        sign_request(SECRET, "POST", PATH, TIMESTAMP, NONCE, BODY + b" "),
        sign_request(SECRET, "POST", PATH + "/other", TIMESTAMP, NONCE, BODY),
        sign_request(SECRET, "POST", PATH, "1784073601", NONCE, BODY),
        sign_request(SECRET, "POST", PATH, TIMESTAMP, "other-nonce-0001", BODY),
    }

    assert original not in signatures
    assert len(signatures) == 4


def test_authentication_headers_are_exact_six_cloudhelm_headers() -> None:
    """契约不增加 content hash header，也不为 signature 增加版本前缀。"""

    signature = sign_request(SECRET, "POST", PATH, TIMESTAMP, NONCE, BODY)
    headers = authentication_headers(
        target_id=str(TEST_TARGET_ID),
        agent_id="agent-01",
        key_id="key-01",
        timestamp=TIMESTAMP,
        nonce=NONCE,
        signature=signature,
    )

    assert headers == {
        "X-CloudHelm-Target-Id": str(TEST_TARGET_ID),
        "X-CloudHelm-Agent-Id": "agent-01",
        "X-CloudHelm-Key-Id": "key-01",
        "X-CloudHelm-Timestamp": TIMESTAMP,
        "X-CloudHelm-Nonce": NONCE,
        "X-CloudHelm-Signature": signature,
    }
    assert headers["X-CloudHelm-Signature"].isalnum()


@pytest.mark.parametrize(
    ("target_id", "agent_id", "key_id", "nonce"),
    [
        ("target-01", "agent-01", "key-01", NONCE),
        (str(TEST_TARGET_ID), "bad agent", "key-01", NONCE),
        (str(TEST_TARGET_ID), "agent-01", "bad key", NONCE),
        (str(TEST_TARGET_ID), "agent-01", "key-01", "too-short"),
    ],
)
def test_authentication_headers_reject_platform_incompatible_values(
    target_id: str,
    agent_id: str,
    key_id: str,
    nonce: str,
) -> None:
    """本地配置或 nonce 不满足 Platform 契约时不发送请求。"""

    signature = sign_request(
        SECRET,
        "POST",
        PATH,
        TIMESTAMP,
        NONCE,
        BODY,
    )
    with pytest.raises(HeartbeatError) as error:
        authentication_headers(
            target_id=target_id,
            agent_id=agent_id,
            key_id=key_id,
            timestamp=TIMESTAMP,
            nonce=nonce,
            signature=signature,
        )

    assert error.value.code == "machine_auth_headers_invalid"
