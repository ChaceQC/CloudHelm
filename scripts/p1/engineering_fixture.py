"""Private identity and process inputs for one real P1.2 engineering chain."""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from dbos import DBOSClient, DBOSPortableJSONSerializer
from pydantic import SecretStr
from sqlalchemy import func, select

from database.commands import commands
from database.connection import create_business_pools, create_engine_from_settings
from database.uow import UnitOfWork
from modules.identity.bootstrap import IdentityMaintenance
from modules.sync.tables import event_log, outbox
from modules.workflow.tables import workflow_bindings
from modules.workflow.version import APPLICATION_NAME, DBOS_SCHEMA
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.identity_contracts import ProjectView
from packages.contracts.p1.identity_requests import CreateProjectRequest, CreateUserRequest, IssueSessionRequest
from scripts.p1.database_fixture import DatabaseFixture

ROOT = Path(__file__).resolve().parents[2]
OWNER = "p12-engineering-owner"
PROJECT = "p12-engineering-project"
ENGINEERING_ACTIONS = ("workspace.write", "candidate.submit", "operation.request")
registry_module = importlib.import_module("services.dev-runner.engineering_registry")


class EngineeringCheckFailure(RuntimeError):
    """Only fixed method categories may be returned in public reports."""


def require(condition, code):
    if not condition:
        raise EngineeringCheckFailure(code)


@dataclass(frozen=True, slots=True)
class EngineeringDatabaseFixture(DatabaseFixture):
    registry_file: Path = field(repr=False)

    def environment_for(self, role):
        environment = super(EngineeringDatabaseFixture, self).environment_for(role)
        environment[registry_module.REGISTRY_ENV] = str(self.registry_file)
        return environment


def process_fixture(fixture: DatabaseFixture, storage: DevelopmentStorageRef) -> EngineeringDatabaseFixture:
    registration = registry_module.EngineeringRegistration(storage=storage)
    target = fixture.runtime_dir / "engineering-registration.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(registration.model_dump_json(indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return EngineeringDatabaseFixture(fixture.project_name, fixture.port, fixture.runtime_dir,
                                      fixture.baseline, target)


class EngineeringProbe:
    """All public commands use the real HTTP API; SQL is an independent observer."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.pools = self.maintenance_engine = self.client = None
        self.token = None
        self.http = None
        self.sequence = 0
        self.evidence = {"http_commands": [], "workflow_handoffs": []}

    def open(self):
        self.pools = create_business_pools(self.fixture.settings("api"))
        self.maintenance_engine = create_engine_from_settings(self.fixture.settings("migrator"), purpose="maintenance")
        self.client = DBOSClient(system_database_engine=self.pools.control, dbos_system_schema=DBOS_SCHEMA,
            application_name=APPLICATION_NAME, serializer=DBOSPortableJSONSerializer(),
            use_listen_notify=False, retry_connection_errors=False)
        maintenance = IdentityMaintenance(self.maintenance_engine)
        maintenance.create_user(CreateUserRequest(user_id=OWNER, display_name="P1.2 engineering verification owner"))
        maintenance.create_project(CreateProjectRequest(project_id=PROJECT, owner_user_id=OWNER,
                                                       name="Fixed reference engineering verification"))
        session = maintenance.issue_session(IssueSessionRequest(user_id=OWNER,
            credential_file=str(self.fixture.runtime_dir / "engineering-credentials" / "owner")))
        self.token = SecretStr(Path(session.credential_file).read_text(encoding="utf-8").strip())

    def close(self):
        self.token = None
        failures = []
        for resource, method in ((self.client, "destroy"), (self.pools, "dispose"),
                                 (self.maintenance_engine, "dispose")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    failures.append(method)
        require(not failures, "engineering_observer_cleanup_unconfirmed")

    def key(self, label):
        self.sequence += 1
        return f"p12-integration-{label}-{self.sequence}"

    def request(self, method, path, *, body=None, expected=200, key=None):
        headers = {"Authorization": "Bearer " + self.token.get_secret_value()}
        if key is not None:
            headers["Idempotency-Key"] = key
        payload = body.model_dump(mode="json") if hasattr(body, "model_dump") else body
        response = self.http.request(method, path, headers=headers, json=payload)
        require(len(response.content) <= 2_000_000, "engineering_http_response_exceeded")
        if response.status_code != expected:
            try:
                rejected = response.json()
                code = rejected.get("code") if isinstance(rejected, dict) else None
            except ValueError:
                code = None
            safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "response_unclassified"
            raise EngineeringCheckFailure(f"engineering_http_{response.status_code}_{safe_code}")
        try:
            value = response.json()
        except ValueError:
            raise EngineeringCheckFailure("engineering_http_json_invalid") from None
        require(type(value) is dict, "engineering_http_object_required")
        if method != "GET":
            self.evidence["http_commands"].append({"method": method, "path": path,
                "status_code": response.status_code, "idempotency_key": key,
                "command_id": value.get("command_id"), "code": value.get("code")})
        return value

    def get(self, path, schema):
        return schema.model_validate(self.request("GET", path))

    def post(self, path, body, schema, *, expected, key=None):
        key = key or self.key(path.rsplit("/", 1)[-1])
        return schema.model_validate(self.request("POST", path, body=body, expected=expected, key=key))

    def project(self):
        return self.get(f"/api/projects/{PROJECT}", ProjectView)

    def workflow_status(self, workflow_id):
        rows = self.client.list_workflows(workflow_ids=[workflow_id], load_input=False, load_output=False, limit=1)
        require(len(rows) <= 1, "engineering_duplicate_workflow_identity")
        return rows[0].status if rows else None

    def handoff(self, result):
        with UnitOfWork(self.pools.control) as uow:
            command_count = uow.connection.scalar(select(func.count()).select_from(commands).where(
                commands.c.command_id == result.command_id))
            command = uow.connection.execute(select(commands.c.request_digest, commands.c.result_json).where(
                commands.c.command_id == result.command_id)).mappings().one_or_none()
            rows = uow.connection.execute(select(workflow_bindings).where(
                workflow_bindings.c.command_id == result.command_id)).mappings().all()
            event_count = uow.connection.scalar(select(func.count()).select_from(event_log).where(
                event_log.c.command_id == result.command_id))
            outbox_count = uow.connection.scalar(select(func.count()).select_from(outbox.join(event_log)).where(
                event_log.c.command_id == result.command_id))
        require(command_count == 1 and len(rows) == 1 and event_count >= 1 and outbox_count == event_count,
                "engineering_command_event_enqueue_handoff_missing")
        row = rows[0]
        require(command["result_json"] == result.model_dump(mode="json"), "engineering_persisted_command_result_mismatch")
        expected_digest = result.request_digest if row["business_kind"] == "workspace" else command["request_digest"]
        require(row["request_digest"] == expected_digest, "engineering_workflow_digest_mismatch")
        status = self.workflow_status(row["workflow_id"])
        require(status is not None, "engineering_dbos_enqueue_missing")
        record = {name: row[name] for name in ("workflow_id", "command_id", "business_kind", "business_id",
            "process_type", "queue_name", "application_name", "application_version", "request_digest")}
        record.update(dbos_status_after_http=status, business_command_count=command_count,
                      event_count=event_count, outbox_count=outbox_count,
                      operation_request_digest=result.request_digest,
                      command_request_digest=command["request_digest"])
        self.evidence["workflow_handoffs"].append(record)
        return row["workflow_id"]

    def wait(self, path, schema, ready, *, workflow_id=None, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.get(path, schema)
            state = getattr(value, "state", None)
            require(state not in {"failed", "unknown"}, "engineering_physical_operation_unsettled")
            status = self.workflow_status(workflow_id) if workflow_id else None
            if status == "ERROR":
                try:
                    self.client.retrieve_workflow(workflow_id).get_result()
                except Exception as error:
                    code = getattr(error, "code", None) or getattr(error, "category", None)
                    if not isinstance(code, str):
                        codes = re.findall(r"\b(?:workspace|task|candidate|storage)_[a-z0-9_]{1,80}\b", str(error))
                        code = codes[-1] if codes else type(error).__name__.lower()
                    raise EngineeringCheckFailure("engineering_workflow_" + code) from None
            require(status not in {"ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"},
                    "engineering_worker_workflow_failed")
            if ready(value) and (workflow_id is None or status == "SUCCESS"):
                return value
            time.sleep(0.2)
        raise EngineeringCheckFailure("engineering_operation_timeout")


def fixed_inputs(manifest_path=None):
    from scripts.p1.engineering_manifest import current_files, verify

    if manifest_path is not None:
        return verify(manifest_path)
    import hashlib

    files = current_files()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"matches": True, "development_only": True, "file_count": len(files),
            "public_worktree_sha256": fingerprint, "files": files}
