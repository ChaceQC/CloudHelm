"""Actual cgroup, PID, writable-filesystem and stop-uncertainty observations."""

import json
from importlib import import_module

from scripts.p1.resource_fixture import require

PRESSURE = """
import errno, json, os, socket, threading
assert not os.path.exists('/var/run/docker.sock')
try:
    open('/outside-resource-group', 'w')
except OSError as e:
    assert e.errno == errno.EROFS
else:
    raise AssertionError('root_is_writable')
work, shm = os.statvfs('/work'), os.statvfs('/dev/shm')
limits = [work.f_blocks * work.f_frsize, shm.f_blocks * shm.f_frsize]
exhausted = False
with open('/work/fill', 'wb', buffering=0) as target:
    try:
        for _ in range(160):
            target.write(b'x' * 65536)
    except OSError as e:
        assert e.errno == errno.ENOSPC
        exhausted = True
assert exhausted
os.unlink('/work/fill')
event, threads, rejected = threading.Event(), [], False
try:
    for _ in range(48):
        thread = threading.Thread(target=event.wait, args=(3,))
        thread.start()
        threads.append(thread)
except RuntimeError:
    rejected = True
finally:
    event.set()
    for thread in threads:
        thread.join()
assert rejected
print(json.dumps({'writable_limit_bytes': sum(limits), 'enospc': exhausted,
                  'pid_limit_rejected_additional_threads': rejected,
                  'read_only_root': True, 'host_socket_absent': True}))
"""


class InterruptedBoundary:
    """A real running operation with a lost control channel, never a fake success."""
    def __init__(self, original):
        self.original, self.backend = original, original.backend

    def stop(self, request):
        raise TimeoutError("injected_lost_stop_channel")

    def observe(self, request):
        raise TimeoutError("injected_lost_observation_channel")


def run_physical(application, dispatcher, runner, request, actor):
    runtime = import_module("services.dev-runner.artifact_environment_docker")
    identity = request.resources.identity
    allocation = dispatcher.start(identity.reservation_id)
    require(allocation.state == "active", "resource_actual_start_failed")
    boundary = runner.boundary
    state, reclaimed, evidence = boundary.observe(request.resources)
    require(state == "running" and not reclaimed and evidence["process_descends_from_group"],
            "resource_actual_group_missing")
    container = boundary._container(request.resources)
    public_config = runner.ledger.directory / "public-docker"
    public_config.mkdir(mode=0o700, exist_ok=True)
    require(not (public_config / "config.json").exists(), "resource_method_docker_configuration_not_empty")
    result = runtime.command(["/usr/bin/docker", "--config", str(public_config), "--host", "unix:///var/run/docker.sock",
                              "exec", container["Id"], "/usr/local/bin/python3", "-c", PRESSURE], timeout=20)
    pressure = json.loads(result.stdout.decode("utf-8"))
    require(pressure["writable_limit_bytes"] == request.resources.hard_limits.disk_bytes,
            "resource_writable_limit_differs_from_accounting")
    try:
        runner.boundary = InterruptedBoundary(boundary)
        unknown = dispatcher.stop(identity.reservation_id)
        require(unknown.state == "orphaned" and unknown.accounted_vector == request.resources.accounted_vector,
                "resource_unknown_stop_released_charge")
        state, _, _ = boundary.observe(request.resources)
        require(state == "running", "resource_unknown_stop_not_a_real_live_process")
    finally:
        runner.boundary = boundary
    recovered = dispatcher.reconcile(identity.reservation_id)
    require(recovered.state == "active", "resource_original_process_reconciliation_failed")
    stopped = dispatcher.stop(identity.reservation_id)
    require(stopped.state == "released" and not any(stopped.accounted_vector.model_dump().values()),
            "resource_actual_stop_or_tmpfs_reclamation_failed")
    require(application.query(actor, identity.reservation_id) == stopped, "resource_query_differs_from_ledger")
    return {"process_binding": boundary.binding(request.resources), "parent_unit": boundary._unit(request.resources),
            "container_id": container["Id"], "parent_kernel_limits": evidence, "actual_pressure": pressure,
            "unknown_stop_kept_full_charge_and_real_process": True, "reconciled_original_process": True,
            "container_group_and_tmpfs_removed": True}
