"""Execution binding supplied by trusted Hub composition, including read-only recovery."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from modules.execution.docker_endpoint import use_socket

_GROUP = ContextVar("cloudhelm_resource_group", default=None)


def current_group():
    return _GROUP.get()


class BoundGroup:
    def __init__(self, request, registration, dispatcher, *, stopped=False):
        from .resource_development import runtime_directory
        from .resource_limits import DockerScratchBoundary

        self.request, self.registration, self.dispatcher = request, registration, dispatcher
        self.binding = DockerScratchBoundary.binding(self, request.resources)
        self.unit = "cloudhelmresource" + self.binding[9:] + ".slice"
        self.path = Path("/sys/fs/cgroup") / self.unit
        self.socket = runtime_directory(self.binding) / "docker.sock"
        self.stopped = stopped

    @contextmanager
    def context(self):
        token = _GROUP.set(self)
        try:
            with use_socket(self.socket):
                yield self
        finally:
            _GROUP.reset(token)

    def observe(self):
        limits = self.request.resources.hard_limits
        period = self.request.resources.identity.cpu_period_us
        expected = {"cpu.max": f"{limits.cpu_millicores * period // 1000} {period}",
                    "memory.max": str(limits.memory_mib * 1024**2), "memory.swap.max": "0",
                    "pids.max": str(limits.pids)}
        actual = {name: (self.path / name).read_text(encoding="utf-8").strip() for name in expected}
        if actual != expected:
            raise ValueError("resource_bound_group_kernel_limits_mismatch")
        return {"unit": self.unit, "kernel_limits": actual,
                "memory_peak_bytes": int((self.path / "memory.peak").read_text(encoding="utf-8")),
                "pids_peak": int((self.path / "pids.peak").read_text(encoding="utf-8"))}

    def stop(self):
        allocation = self.dispatcher.stop(self.request.resources.identity.reservation_id)
        if allocation.state != "released":
            raise ValueError("resource_bound_group_stop_unconfirmed")
        self.stopped = True

    def authorize_network(self, network_id):
        self.dispatcher.runner.authorize_network(self.request.resources.identity.reservation_id, network_id)
