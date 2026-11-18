"""Same-epoch preview measurements; reviewed clock evidence is supplied by the host."""

import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from modules.delivery.permit_clock import ClockSupport


@dataclass(frozen=True)
class PreviewClockSupport(ClockSupport):
    """Reviewed Linux BOOTTIME proof bound to one host boot and clocksource.

    The trusted composition root supplies a bounded, nonblocking verify_current
    callback. It raises on stale or unknown continuity, including loss of any
    required independent VM/host witness. Kernel metadata alone is not proof.
    """

    boot_id: str
    clocksource: str
    suspend_count: int

    def __post_init__(self):
        super().__post_init__()
        if not self.boot_id or not self.clocksource or self.suspend_count < 0:
            raise ValueError("preview_clock_binding_invalid")


class PreviewClock:
    def __init__(self, support: PreviewClockSupport | None = None):
        self.epoch = "preview-clock-" + uuid4().hex
        self._support = support if isinstance(support, PreviewClockSupport) else None
        self._last_ns = None
        self._lock = Lock()

    def sample(self) -> tuple[int | None, str | None]:
        with self._lock:
            support = self._support
            if support is None:
                return None, None
            try:
                observed = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
                binding = (
                    Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip(),
                    Path("/sys/devices/system/clocksource/clocksource0/current_clocksource")
                    .read_text(encoding="utf-8").strip(),
                    int(Path("/sys/power/suspend_stats/success").read_text(encoding="utf-8")),
                )
                if (binding != (support.boot_id, support.clocksource, support.suspend_count)
                        or (self._last_ns is not None and observed < self._last_ns)
                        or support.verify_current() is not None):
                    raise ValueError("preview_clock_continuity_lost")
            except Exception:
                self._support = None
                return None, None
            self._last_ns = observed
            return observed, support.evidence_digest

    def upper_ms(self, start_ns: int | None, end_ns: int | None) -> int | None:
        """Bound same-epoch endpoints after the caller verifies a fresh sample."""
        with self._lock:
            support = self._support
            if (support is None or self._last_ns is None or start_ns is None or end_ns is None
                    or not 0 <= start_ns <= end_ns <= self._last_ns):
                return None
            margin_ns = 2 * (support.local_read_error_us + support.sample_error_us) * 1000
            # The minimum reviewed clock rate scales the corrected nanoseconds to milliseconds.
            denominator = 1_000_000 - support.relative_rate_ppm
            return (end_ns - start_ns + margin_ns + denominator - 1) // denominator

    def elapsed(self, record) -> tuple[int, bool]:
        revocation = record.revocation
        start = record.revocation_started_boottime_ns
        if revocation.hub_clock_epoch != self.epoch or start is None:
            return revocation.elapsed_upper_ms, False
        observed, evidence = self.sample()
        upper = self.upper_ms(start, observed) if evidence == record.revocation_clock_evidence_digest else None
        if upper is None:
            return revocation.elapsed_upper_ms, False
        return max(revocation.elapsed_upper_ms, upper), True

    def observe(self, record):
        if record.revocation is None or record.state == "revoked":
            return record
        elapsed, trusted = self.elapsed(record)
        return record.model_copy(update={"revocation": record.revocation.model_copy(update={
            "observed_hub_clock_epoch": self.epoch, "elapsed_upper_ms": elapsed,
            "timing_evidence_current": trusted})})


preview_clock = PreviewClock()
