"""Remote Agent 对外稳定错误。

异常消息只描述错误类别，不拼接凭据正文、凭据文件路径、签名或响应正文，
避免 systemd journal 和测试日志意外保存敏感信息。
"""


class RemoteAgentError(RuntimeError):
    """Remote Agent 可预期错误的基类。"""

    def __init__(self, code: str, message: str) -> None:
        """保存稳定错误码和脱敏消息。"""

        super().__init__(message)
        self.code = code
        self.message = message


class CredentialError(RemoteAgentError):
    """凭据文件缺失、为空或权限不安全。"""


class HeartbeatError(RemoteAgentError):
    """心跳请求构造、传输或响应校验失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
    ) -> None:
        """保存可审计的 HTTP 状态，但不保存响应正文。"""

        super().__init__(code, message)
        self.status_code = status_code
