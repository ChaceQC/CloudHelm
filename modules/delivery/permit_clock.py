"""Linux RAW clock and reviewed continuous evidence; unsupported hosts fail closed."""

import time
import re
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from packages.contracts.p0.permit_contracts import TimeMapping
from packages.contracts.p1.remote_delivery import RemoteHello, RemoteTimeSample


@dataclass(frozen=True)
class ClockSupport:
    """Composition-root proof, never constructed from an HTTP request or a bare digest.

    The verifier owns the reviewed hardware/rate/read-error evidence and a current
    pre-start suspend/VM-pause continuity assertion for this exact host/process.
    No generic Linux/WSL verifier is claimed by this implementation.
    """

    evidence_digest: str
    sample_error_us: int
    local_read_error_us: int
    relative_rate_ppm: int
    verify_current: Callable[[], None]

    def __post_init__(self):
        if (not re.fullmatch(r"sha256:[0-9a-f]{64}", self.evidence_digest)
                or not 1 <= self.sample_error_us <= 10000 or not 1 <= self.local_read_error_us <= 1000
                or not 0 <= self.relative_rate_ppm <= 100):
            raise ValueError("clock_support_bounds_invalid")


class PermitClock:
    def __init__(self, support: ClockSupport | None = None):
        self.support = support
        self.incarnation = "hub-" + uuid4().hex
        self.epoch = "time-" + uuid4().hex
        self.origin = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        self.last = 0

    def now(self):
        if self.support is None:
            raise ValueError("clock_support_evidence_unavailable")
        try:
            self.support.verify_current()
        except Exception:
            self.support = None
            raise ValueError("clock_continuity_lost") from None
        value = (time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) - self.origin) // 1000
        if value < self.last:
            self.support = None
            raise ValueError("clock_continuity_lost")
        self.last = value
        return value

    def sample(self, hello: RemoteHello, channel_id):
        return RemoteTimeSample(hello=hello, hub_incarnation=self.incarnation, time_epoch=self.epoch,
            channel_binding_id=channel_id, hub_sample_us=self.now(),
            support_evidence_digest=self.support.evidence_digest)


class ExecutorClock:
    def __init__(self, support: ClockSupport | None = None):
        self.support = support
        self.continuity = "clock-" + uuid4().hex
        self.mapping_epoch = "mapping-" + uuid4().hex
        self.last = 0

    def now(self):
        if self.support is None:
            raise ValueError("clock_support_evidence_unavailable")
        try:
            self.support.verify_current()
            value = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000
            if value < self.last:
                raise ValueError("clock_rollback")
        except Exception:
            self.support = None
            self.continuity = "clock-" + uuid4().hex
            self.mapping_epoch = "mapping-" + uuid4().hex
            raise ValueError("clock_continuity_lost") from None
        self.last = value
        return value

    def sample(self, channel, executor, generation):
        hello = RemoteHello(executor_instance=executor, generation=generation,
            mapping_epoch=self.mapping_epoch, clock_continuity_id=self.continuity, sample_nonce=uuid4().hex)
        sent = self.now()
        sample = channel.sample(hello)
        received = self.now()
        if sample.hello != hello or sample.support_evidence_digest != self.support.evidence_digest:
            raise ValueError("time_sample_binding_invalid")
        return TimeMapping(time_epoch=sample.time_epoch, mapping_id="sample-" + hello.sample_nonce,
            mapping_epoch=hello.mapping_epoch, clock_continuity_id=hello.clock_continuity_id,
            hub_incarnation=sample.hub_incarnation, executor_instance=executor,
            channel_binding_id=sample.channel_binding_id, sample_nonce=hello.sample_nonce,
            support_evidence_digest=self.support.evidence_digest, sent_mono_us=sent, received_mono_us=received,
            hub_sample_us=sample.hub_sample_us, hub_sample_error_us=self.support.sample_error_us,
            local_read_error_us=self.support.local_read_error_us, relative_rate_ppm=self.support.relative_rate_ppm)
