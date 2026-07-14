"""Tool Gateway 策略层稳定错误。"""


class PolicyError(Exception):
    """策略拒绝时抛出的稳定异常。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
