"""Tool Gateway 进程内滑动窗口限流器。

M5 只承诺本地单实例工具入口，因此这里不引入 Redis 或分布式锁。限流器
按调用主体维护最近一段时间的时间戳，在 handler 执行前拒绝超额请求；
后续多 worker 或远端部署阶段应替换为共享存储实现。
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    """线程安全的固定配额滑动窗口限流器。"""

    def __init__(
        self,
        max_calls: int = 60,
        window_seconds: int = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls 必须大于等于 1。")
        if window_seconds < 1:
            raise ValueError("window_seconds 必须大于等于 1。")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def consume(self, key: str) -> int | None:
        """占用一次调用配额，超额时返回建议等待秒数。"""

        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            calls = self._calls[key]
            while calls and calls[0] <= cutoff:
                calls.popleft()
            if len(calls) >= self.max_calls:
                return max(1, int(calls[0] + self.window_seconds - now + 0.999))
            calls.append(now)
            return None
