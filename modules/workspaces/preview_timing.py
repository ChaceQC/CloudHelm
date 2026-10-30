"""Same-epoch preview measurements; reviewed clock evidence is supplied by the host."""

import time
from uuid import uuid4

from modules.delivery.permit_clock import ClockSupport


class PreviewClock:
    def __init__(self, support: ClockSupport | None = None):
        self.epoch = "preview-clock-" + uuid4().hex
        self.support = support

    def sample(self):
        if not hasattr(time, "CLOCK_BOOTTIME"):
            return None, None
        if self.support is not None:
            try:
                self.support.verify_current()
            except ValueError:
                self.support = None
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME), (
            self.support.evidence_digest if self.support is not None else None)

    def elapsed(self, record):
        revocation = record.revocation
        if revocation.hub_clock_epoch != self.epoch or record.revocation_started_boottime_ns is None:
            return revocation.elapsed_upper_ms, False
        observed, evidence = self.sample()
        if observed is None or observed < record.revocation_started_boottime_ns:
            return revocation.elapsed_upper_ms, False
        raw_ns = observed - record.revocation_started_boottime_ns
        trusted = evidence is not None and evidence == record.revocation_clock_evidence_digest
        # Both reads and the reviewed relative rate contribute to the upper bound.
        denominator = 1_000_000 - self.support.relative_rate_ppm if trusted else 1_000_000
        numerator = raw_ns + (2 * self.support.local_read_error_us * 1000 if trusted else 0)
        upper_ms = (numerator + denominator - 1) // denominator
        return max(revocation.elapsed_upper_ms, upper_ms), trusted

    def observe(self, record):
        if record.revocation is None or record.state == "revoked":
            return record
        elapsed, trusted = self.elapsed(record)
        return record.model_copy(update={"revocation": record.revocation.model_copy(update={
            "observed_hub_clock_epoch": self.epoch, "elapsed_upper_ms": elapsed,
            "timing_evidence_current": trusted})})


preview_clock = PreviewClock()
