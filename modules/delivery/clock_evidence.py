"""Continuous guards for one measured Linux pair; WSL requires an external signed witness."""

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

from modules.delivery.permit_clock import ClockSupport


def raw_us():
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000


class ContinuousClockEvidence:
    """Only a trusted composition root supplies the fixed evidence and public-key pin.

    A changed boot, clocksource, suspend counter, witness generation, signature or
    watchdog gap permanently closes this instance. It cannot silently rebaseline.
    """

    def __init__(self, profile, *, role, public_key=None, witness_url=None):
        self.profile, self.role = profile, role
        self.public_key, self.witness_url = public_key, witness_url
        self.digest = "sha256:" + hashlib.sha256(json.dumps(profile, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        if profile.get("scope") != "p14-fixed-measured-pair-r1" or not profile.get("sample_record_sha256"):
            raise ValueError("clock_evidence_record_required")
        bounds = profile["observed_rate_interval_ppm"]
        from decimal import Decimal
        if not Decimal("-100") <= Decimal(bounds[0]) <= Decimal(bounds[1]) <= Decimal("100"):
            raise ValueError("clock_measured_rate_outside_supported_bound")
        self.boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        if self.boot != profile[role]["boot_id"]:
            raise ValueError("clock_evidence_boot_mismatch")
        self.source = Path("/sys/devices/system/clocksource/clocksource0/current_clocksource")
        self.suspend = Path("/sys/power/suspend_stats/success")
        self.suspend_count = int(self.suspend.read_text(encoding="utf-8"))
        self.sleep_offset = self._sleep_offset()
        self.last_watch = raw_us()
        self.lost = None
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.native_identity = None
        self.client = httpx.Client(timeout=2, trust_env=False) if witness_url else None
        if role == "hub" and witness_url is None:
            raise ValueError("wsl_external_continuity_witness_required")
        if role == "target":
            actual = subprocess.run(["systemd-detect-virt"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if actual.stdout.strip() != b"none":
                raise ValueError("clock_target_bare_metal_required")
        if public_key:
            if hashlib.sha256(Path(public_key).read_bytes()).hexdigest() != profile["hub"]["witness_public_key_sha256"]:
                raise ValueError("clock_witness_key_pin_mismatch")
            self._native()
        self.thread = threading.Thread(target=self._watch, name="clock-continuity", daemon=True)
        self.thread.start()

    @staticmethod
    def _sleep_offset():
        return (time.clock_gettime_ns(time.CLOCK_BOOTTIME) - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) // 1000

    def _local(self):
        now = raw_us()
        if now < self.last_watch or now - self.last_watch > 200000:
            raise ValueError("clock_watchdog_continuity_gap")
        if (self.source.read_text(encoding="utf-8").strip() != self.profile[self.role]["clocksource"]
                or Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() != self.boot
                or int(self.suspend.read_text(encoding="utf-8")) != self.suspend_count
                or abs(self._sleep_offset() - self.sleep_offset) > 1000):
            raise ValueError("clock_platform_continuity_changed")

    def _watch(self):
        while not self.closed.wait(.025):
            try:
                self._local()
                self.last_watch = raw_us()
            except Exception:
                self.lost = "clock_local_continuity_lost"
                return

    def _native(self):
        nonce = uuid4().hex
        response = self.client.get(self.witness_url, params={"nonce": nonce})
        if response.status_code != 200 or len(response.content) > 16384:
            raise ValueError("clock_native_witness_unavailable")
        envelope = response.json()
        body = base64.b64decode(envelope["data"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        with tempfile.TemporaryDirectory(prefix="clock-signature-") as directory:
            data = Path(directory) / "data"
            sig = Path(directory) / "signature"
            data.write_bytes(body)
            sig.write_bytes(signature)
            result = subprocess.run(["/usr/bin/openssl", "dgst", "-sha256", "-verify", str(self.public_key),
                "-signature", str(sig), str(data)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        if result.returncode:
            raise ValueError("clock_witness_signature_invalid")
        value = json.loads(body)
        if (value["nonce"] != nonce or value.get("guard_revision") != "p14-native-witness-r2"
                or value["vm_state"] != "Running" or value["vm_id"] != self.profile["hub"]["vm_id"]):
            raise ValueError("clock_witness_binding_invalid")
        identity = (value["instance"], value["system_events"], value["power_events"], value["qpc_frequency"])
        if self.native_identity is not None and identity != self.native_identity:
            raise ValueError("clock_native_continuity_changed")
        self.native_identity = identity

    def verify_current(self):
        if self.lost:
            raise ValueError(self.lost)
        try:
            self._local()
            if self.client is not None:
                with self.lock:
                    self._native()
            self._local()
        except Exception:
            self.lost = "clock_continuity_untrusted"
            raise ValueError(self.lost) from None

    def support(self):
        return ClockSupport(self.digest, 10, 1, 100, self.verify_current)

    def close(self):
        self.closed.set()
        self.thread.join(timeout=2)
        if self.client is not None:
            self.client.close()
