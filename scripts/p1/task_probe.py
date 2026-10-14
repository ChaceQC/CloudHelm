"""Bounded test resources for the Task group; the coordinator owns the database."""

from pathlib import Path
import time

from dbos import DBOSClient, DBOSPortableJSONSerializer
from pydantic import SecretStr
from sqlalchemy import func, select

from database.commands import commands
from database.connection import create_business_pools, create_engine_from_settings
from database.uow import UnitOfWork
from modules.collaboration.application import TaskApplication
from modules.collaboration.tables import tasks, task_completion_reports, work_items
from modules.identity.authentication import authenticate_current
from modules.identity.bootstrap import IdentityMaintenance
from modules.projects.tables import projects
from modules.sync.tables import event_log, outbox
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, DBOS_SCHEMA
from packages.contracts.p1.identity_requests import CreateProjectRequest, CreateUserRequest, IssueSessionRequest
from packages.contracts.p1.task_requests import CancelTaskRequest, CompleteTaskRequest, CreateTaskRequest, StartTaskRequest
from packages.contracts.p1.task_results import TaskCommandResult
from scripts.p1.task_fixture import prepare_task_declaration

OWNER = "p11-task-owner"
PROJECT = "p11-task-project"


class TaskCheckFailure(RuntimeError):
    """Fixed check code only; never include rows, statements, hashes or credentials."""


def require(condition, code):
    if not condition:
        raise TaskCheckFailure(code)


class TaskProbe:
    def __init__(self, fixture) -> None:
        self.fixture = fixture
        self.pools = self.other_control = self.maintenance_engine = self.client = None
        self.token = self.declaration = self.session = None
        self.sequence = 0

    def open(self) -> None:
        self.pools = create_business_pools(self.fixture.settings("api"))
        self.other_control = create_engine_from_settings(self.fixture.settings("api"), purpose="control")
        self.maintenance_engine = create_engine_from_settings(self.fixture.settings("migrator"), purpose="maintenance")
        self.maintenance = IdentityMaintenance(self.maintenance_engine)
        self.client = DBOSClient(
            system_database_engine=self.pools.normal, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False,
        )
        self.app = TaskApplication(self.pools.normal, self.pools.control, self.client)
        self.other_app = TaskApplication(self.pools.normal, self.other_control, self.client)
        self.maintenance.create_user(CreateUserRequest(user_id=OWNER, display_name="P1 Task protocol owner"))
        self.maintenance.create_project(CreateProjectRequest(
            project_id=PROJECT, owner_user_id=OWNER, name="Synthetic Task protocol checks",
        ))
        self.issue_session("owner")
        self.declaration = prepare_task_declaration(self.fixture, PROJECT, self.token)

    def close(self) -> None:
        failures = []
        resources = ((self.client, "destroy"), (self.other_control, "dispose"),
                     (self.pools, "dispose"), (self.maintenance_engine, "dispose"))
        for resource, method in resources:
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    failures.append(method)
        if failures:
            raise TaskCheckFailure("task_resource_cleanup_failed")

    def issue_session(self, label):
        path = self.fixture.runtime_dir / "task-credentials" / label
        self.session = self.maintenance.issue_session(IssueSessionRequest(user_id=OWNER, credential_file=str(path)))
        self.token = SecretStr(Path(self.session.credential_file).read_text(encoding="utf-8").strip())

    def key(self, name):
        self.sequence += 1
        return f"p11-task-{name}-{self.sequence}"

    def actor(self):
        with UnitOfWork(self.pools.control) as uow:
            return authenticate_current(uow, self.token)

    def create_request(self):
        with UnitOfWork(self.pools.control) as uow:
            revision = uow.connection.scalar(select(projects.c.revision).where(projects.c.project_id == PROJECT))
        return CreateTaskRequest(expected_project_revision=revision, declaration=self.declaration)

    def create(self, label="create"):
        reply = self.app.create(self.actor(), PROJECT, self.create_request(), idempotency_key=self.key(label))
        require(reply.status_code == 201 and isinstance(reply.body, TaskCommandResult), "task_create_failed")
        return reply.body

    def start(self, created):
        request = StartTaskRequest(expected_version=created.version, expected_control_revision=created.control_revision,
                                   expected_input_validity_revision=created.input_validity_revision)
        reply = self.app.start(self.actor(), created.task_id, request, idempotency_key=self.key("start"))
        require(reply.status_code == 202 and reply.body.outcome == "started", "task_start_failed")
        return reply.body

    def row(self, task_id):
        with UnitOfWork(self.pools.control) as uow:
            return dict(uow.connection.execute(select(tasks).where(tasks.c.task_id == task_id)).mappings().one())

    def complete_request(self, task_id):
        row = self.row(task_id)
        return CompleteTaskRequest(expected_version=row["version"], expected_control_revision=row["control_revision"],
                                   expected_input_validity_revision=row["input_validity_revision"])

    def cancel_request(self, task_id):
        row = self.row(task_id)
        return CancelTaskRequest(expected_version=row["version"], expected_control_revision=row["control_revision"],
                                 cancel_reason="p11-task-protocol-cancel")

    def snapshot(self, task_id):
        with UnitOfWork(self.pools.control) as uow:
            task = dict(uow.connection.execute(select(tasks).where(tasks.c.task_id == task_id)).mappings().one())
            amounts = {
                "commands": uow.connection.scalar(select(func.count()).select_from(commands).where(
                    commands.c.resource_kind == "task", commands.c.resource_id == task_id)),
                "events": uow.connection.scalar(select(func.count()).select_from(event_log).where(event_log.c.aggregate_id == task_id)),
                "outbox": uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(event_log.c.aggregate_id == task_id)),
                "bindings": uow.connection.scalar(select(func.count()).select_from(workflow_bindings).where(workflow_bindings.c.business_id == task_id)),
                "items": uow.connection.scalar(select(func.count()).select_from(work_items).where(work_items.c.task_id == task_id)),
                "reports": uow.connection.scalar(select(func.count()).select_from(task_completion_reports).where(task_completion_reports.c.task_id == task_id)),
            }
        return task, amounts

    def workflow_status(self, workflow_id):
        rows = self.client.list_workflows(workflow_ids=[workflow_id], load_input=False, load_output=False, limit=1)
        return None if not rows else rows[0].status

    def wait_workflow(self, workflow_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.workflow_status(workflow_id)
            if status == "SUCCESS":
                return
            require(status not in {"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}, "task_workflow_failed")
            time.sleep(0.05)
        raise TaskCheckFailure("task_workflow_timeout")
