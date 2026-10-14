"""Synthetic Task source metadata on the coordinator's isolated database fixture.

This prepares registered declarations, never accepted work, success commands,
HTTP responses, real development evidence or human test conclusions.
"""

import hashlib
from datetime import UTC

from pydantic import SecretStr
from sqlalchemy import func, select

from database.connection import create_engine_from_settings
from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_registered_reference, register_fact_source, register_reference
from modules.identity.actors import AuthoritativeResource
from modules.identity.authentication import authenticate_current
from modules.identity.authorization import authorize_current
from modules.projects.tables import projects
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import (
    AcceptanceMetadata, HumanPolicyMetadata, MethodMetadata, RegisteredReference,
    RequirementMetadata, ResourcePolicyMetadata, SourceMetadata, TaskFactSource,
)
from packages.contracts.p1.task_requests import TaskBudget, TaskDeclaration
from scripts.p1.database_fixture import DatabaseFixture


class TaskFixtureFailure(RuntimeError):
    """Only fixed fixture categories may escape; no credential, hash or record dump."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TaskFixtureFailure(code)


class FixtureSources:
    """Controlled synthetic producers sharing one real authenticated owner UoW."""

    def __init__(self, uow: UnitOfWork, project_id: str, bearer: SecretStr) -> None:
        self.uow, self.project_id = uow, project_id
        self.actor = authenticate_current(uow, bearer)
        revision = uow.connection.scalar(select(projects.c.revision).where(projects.c.project_id == project_id))
        require(revision is not None and project_id.startswith("p11-"), "task_fixture_project_invalid")
        self.resource = AuthoritativeResource(project_id, "project", project_id, revision=revision)
        self.management = authorize_current(uow, self.actor, self.resource, "project.manage")
        require(self.management.envelope.role == "project_owner", "task_fixture_owner_required")
        self.archive = authorize_current(uow, self.actor, self.resource, "fact.archive")
        self.prefix = "p11-task-" + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:16]
        self.method_metadata = MethodMetadata(description="Synthetic P1.1 protocol method; no product acceptance.")
        self.method_ref = self.make_ref("method", self.method_metadata)
        self._sources: set[str] = set()
        self.add("method", self.method_metadata, domain="projects")

    def identity(self, name: str) -> str:
        return self.prefix + "-" + name

    def make_ref(self, name, metadata, *, revision="fixture-r1") -> EngineeringRef:
        kind = {"resource_policy": "policy", "human_policy": "policy", "human_conclusion": "evidence",
                "run_history": "history"}.get(metadata.record_kind, metadata.record_kind)
        object_id = self.identity(name)
        if metadata.record_kind == "source":
            revision = metadata.commit
        elif metadata.record_kind == "input_set":
            object_id = metadata.input_set.input_set_id
        elif metadata.record_kind == "evidence":
            object_id = metadata.evidence.evidence_id
        digest = "sha256:" + hashlib.sha256(metadata.model_dump_json().encode("utf-8")).hexdigest()
        return EngineeringRef(kind=kind, object_id=object_id, revision=revision,
                              digest=digest, digest_algorithm="sha256")

    def _source(self, domain: str) -> str:
        source_id = self.identity("producer-" + domain)
        if domain not in self._sources:
            source = TaskFactSource(
                project_id=self.project_id, source_id=source_id, producer_domain=domain,
                authority="cloudhelm", principal=self.actor.principal, purpose="protocol_validation",
                method_ref=self.method_ref,
                executor_ids=(self.identity("executor"),) if domain == "execution" else (),
            )
            register_fact_source(self.uow.connection, source, authorization=self.management.envelope)
            self._sources.add(domain)
        return source_id

    def add(self, name, metadata, *, domain: str, revision="fixture-r1") -> EngineeringRef:
        reference = self.make_ref(name, metadata, revision=revision)
        source_id = self._source(domain)
        try:
            existing = read_registered_reference(self.uow.connection, self.project_id, reference)
        except TaskBoundaryError as error:
            if error.code != "reference_not_registered":
                raise TaskFixtureFailure("task_fixture_reference_unavailable") from None
        else:
            require(existing.metadata == metadata and existing.source_id == source_id,
                    "task_fixture_reference_conflict")
            return reference
        record = RegisteredReference(
            project_id=self.project_id, registration_id=self.identity("registration-" + name),
            source_id=source_id, source_record_id=self.identity("record-" + name), reference=reference,
            metadata=metadata,
            observed_at_utc=self.uow.connection.scalar(select(func.clock_timestamp())).astimezone(UTC),
        )
        register_reference(self.uow.connection, record,
                           source_bytes=metadata.model_dump_json().encode("utf-8"),
                           authorization=self.archive.envelope)
        return reference

    def declaration(self) -> TaskDeclaration:
        requirement = self.add("requirement", RequirementMetadata(
            statement="Synthetic command/transaction validation only; no delivered product or human acceptance.",
        ), domain="projects")
        assets = self.add("acceptance", AcceptanceMetadata(
            required_check_ids=("p11-task-synthetic-required",), method_ref=self.method_ref,
        ), domain="integration")
        source = self.add("source", SourceMetadata(commit="1" * 40), domain="projects")
        resources = self.add("resource-policy", ResourcePolicyMetadata(
            resource_scope_ids=("p11-task-isolated-fixture",), allowed_capabilities=("task-control-protocol",),
        ), domain="identity")
        human = self.add("human-policy", HumanPolicyMetadata(
            is_completion_gate=False, skip_allowed=False,
        ), domain="identity")
        return TaskDeclaration(
            title="Synthetic P1.1 control fixture", goal="Validate bounded Task commands without product acceptance.",
            requirement_ref=requirement, acceptance_assets_ref=assets, source_ref=source,
            budget=TaskBudget(amount="0", currency="USD"), resource_scope_ref=resources,
            human_test_policy_ref=human,
        )


def prepare_task_declaration(
    fixture: DatabaseFixture, project_id: str, owner_bearer: SecretStr,
) -> TaskDeclaration:
    require(isinstance(fixture, DatabaseFixture) and fixture.baseline is not None,
            "task_initialized_fixture_required")
    require(isinstance(owner_bearer, SecretStr), "task_fixture_credential_required")
    engine = None
    try:
        engine = create_engine_from_settings(fixture.settings("api"), purpose="control")
        with UnitOfWork(engine) as uow:
            return FixtureSources(uow, project_id, owner_bearer).declaration()
    except TaskFixtureFailure:
        raise
    except Exception:
        raise TaskFixtureFailure("task_declaration_fixture_failed") from None
    finally:
        if engine is not None:
            engine.dispose()
