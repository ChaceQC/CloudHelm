"""Private identities, real Task commands and bounded P1.3 resource inputs."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import func, select

from database.commands import commands
from database.uow import UnitOfWork
from modules.collaboration.application import TaskApplication
from modules.execution.tables import resource_reservations
from modules.identity.authentication import authenticate_current
from modules.projects.commands import ProjectApplication
from modules.projects.queries import get_project
from modules.sync.tables import event_log, outbox
from packages.contracts.p0.resource_contracts import AllocationIdentity, HostResourcePool, ResourceRequest, ResourceVector
from packages.contracts.p1.identity_requests import CreateProjectRequest, CreateUserRequest, GrantProjectRoleRequest, IssueSessionRequest
from packages.contracts.p1.resource_protocol import PoolRegistration, ReserveResourcesRequest, RunnerRegistration, resource_request_digest
from packages.contracts.p1.task_requests import CreateTaskRequest
from scripts.p1.task_fixture import prepare_task_declaration

IMAGE = "sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"
ARGV = ("/usr/local/bin/python3", "-c", "import time; time.sleep(300)")


def require(value, code):
    if not value:
        raise AssertionError(code)


def reject(call, error_type, code=None):
    try:
        call()
    except error_type as error:
        require(code is None or str(error) == code, "resource_rejection_code_mismatch")
    else:
        raise AssertionError("resource_rejection_missing")


def pool_and_runners():
    ledger = import_module("services.dev-runner.resource_ledger")
    limits = import_module("services.dev-runner.resource_limits")
    vector = ResourceVector(memory_mib=128, cpu_millicores=500, disk_bytes=8 * 1024**2,
                            pids=32, heavy_slots=1, preview_slots=1)
    pool = HostResourcePool(host_resource_pool_id="p13-wsl-isolated-host", physical_host_id=ledger.observed_host_id(),
        executor_instance_ids=("p13-runner-a", "p13-runner-b"), capacity_revision=1,
        configured_budget=vector, measured_allocatable_capacity=vector,
        unknown_occupancy_upper_bound=ResourceVector(), host_identity_evidence_ref="p13-wsl-machine-identity",
        capacity_evidence_ref="p13-wsl-bounded-development-envelope", group_limits_evidence_ref="p13-cgroup-tmpfs-method")
    registration = PoolRegistration(pool=pool, hub_incarnation="p13-isolated-hub", resource_generation=1)
    runners = tuple(RunnerRegistration(executor_instance_id=name, host_resource_pool_id=pool.host_resource_pool_id,
        physical_host_id=pool.physical_host_id, hub_incarnation=registration.hub_incarnation,
        resource_generation=1, maximum=vector, cpu_period_us=100000,
        capability_evidence_ref="p13-linux-systemd-docker-scratch", image_id=IMAGE,
        recipe_digest=limits.recipe_digest(IMAGE, ARGV)) for name in pool.executor_instance_ids)
    return registration, runners


def subject(fixture, probe, name):
    user, project = "p13-user-" + name, "p11-resource-" + name
    probe.maintenance.create_user(CreateUserRequest(user_id=user, display_name="P1.3 isolated protocol identity"))
    probe.maintenance.create_project(CreateProjectRequest(project_id=project, owner_user_id=user,
                                                          name="P1.3 isolated resource protocol"))
    session = probe.maintenance.issue_session(IssueSessionRequest(
        user_id=user, credential_file=str(fixture.runtime_dir / "resource-credentials" / name)))
    bearer = SecretStr(Path(session.credential_file).read_text(encoding="utf-8").strip())
    with UnitOfWork(probe.pools.control) as uow:
        actor = authenticate_current(uow, bearer)
        view = get_project(uow, actor, project)
    granted = ProjectApplication(probe.pools.normal).grant_role(actor, project, GrantProjectRoleRequest(
        expected_project_revision=view.revision, expected_permission_revision=view.permission_revision,
        user_id=user, role="developer", actions=("operation.request",)), idempotency_key="resource-role-" + name)
    require(granted.status_code == 200, "resource_explicit_role_grant_failed")
    declaration = prepare_task_declaration(fixture, project, bearer)
    created = TaskApplication(probe.pools.normal, probe.pools.control, probe.client).create(actor, project,
        CreateTaskRequest(expected_project_revision=granted.body.project.revision, declaration=declaration),
        idempotency_key="resource-task-" + name)
    require(created.status_code == 201, "resource_task_setup_failed")
    return actor, created.body


def request_for(task, runner, *, resources=None):
    suffix = uuid4().hex
    vector = resources or runner.maximum.model_copy(update={"preview_slots": 0})
    identity = AllocationIdentity(reservation_id="p13-res-" + suffix, operation_id="p13-op-" + suffix,
        resource_group_id="p13-group-" + suffix, resource_group_digest=runner.recipe_digest,
        host_resource_pool_id=runner.host_resource_pool_id, executor_instance_id=runner.executor_instance_id,
        hub_incarnation=runner.hub_incarnation, resource_generation=runner.resource_generation,
        cpu_period_us=runner.cpu_period_us, conflict_keys=("scratch:" + suffix,))
    resource = ResourceRequest(identity=identity, request_digest="sha256:" + "0" * 64,
                               request_vector=vector, accounted_vector=vector, hard_limits=vector)
    resource = resource.model_copy(update={"request_digest": resource_request_digest(resource)})
    return ReserveResourcesRequest(expected_version=task.version, expected_control_revision=task.control_revision,
        expected_input_validity_revision=task.input_validity_revision,
        expires_at_utc=datetime.now(UTC) + timedelta(minutes=5), resources=resource)


def counts(engine):
    with UnitOfWork(engine) as uow:
        return tuple(uow.connection.scalar(select(func.count()).select_from(table))
                     for table in (commands, resource_reservations, event_log, outbox))


def accept_in_process(pool, registration, request, queue):
    """A separate process, sharing only the real local database/host lock."""
    try:
        ledger = import_module("services.dev-runner.resource_ledger")
        runtime = import_module("services.dev-runner.resource_runtime")
        limits = import_module("services.dev-runner.resource_limits")
        runner = runtime.ResourceRunner(ledger.ResourceLedger(pool, registration), limits.DockerScratchBoundary(registration, ARGV))
        queue.put(runner.accept(request, backend=registration.backend).state)
    except Exception:
        queue.put("failed")
