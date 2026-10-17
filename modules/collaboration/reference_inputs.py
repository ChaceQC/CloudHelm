"""Controlled real-reference input registration and atomic draft Task creation/binding.

This internal entry grants neither physical admission nor workspace write authority.
Public callers cannot supply metadata, an allowed flag, or a resource reservation.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib

import rfc8785
from sqlalchemy import select

from database.commands import CommandConflict
from database.uow import UnitOfWork, require_transaction
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.input_commands import bind_initial_input_in_uow
from modules.collaboration.lifecycle_commands import create_task
from modules.collaboration.records import (
    contract_digest, read_registered_reference, reference_key, register_fact_source, register_reference,
)
from modules.collaboration.tables import task_reference_records
from modules.identity.actors import AuthenticatedActor, AuthoritativeResource, validate_actor
from modules.identity.authorization import authorize_current
from modules.identity.errors import IdentityError
from modules.projects.reference_assets import ReferenceAssets, load_reference_assets
from modules.projects.source_operations import read_import_intent
from modules.projects.source_receipts import read_source_registration
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, input_set_digest
from packages.contracts.p1.source_records import SourceImportRegistration
from packages.contracts.p1.task_facts import (
    HumanPolicyMetadata, InputSetMetadata, RegisteredReference, ResourcePolicyMetadata, TaskFactSource,
)
from packages.contracts.p1.task_internal import BindInitialTaskInputRequest
from packages.contracts.p1.task_requests import CreateTaskRequest, TaskBudget, TaskDeclaration
from packages.contracts.p1.task_results import TaskHttpResult

RESOURCE_SCOPE_ID = "cloudhelm-wsl-controlled-development-r1"
REQUIRED_CAPABILITIES = ("workspace.write", "candidate.submit", "operation.request")
REGISTRATION_REVISION = "p1-reference-task-input-r1"


def _identity(*values) -> str:
    return hashlib.sha256(rfc8785.dumps(values)).hexdigest()


def _ref(kind, object_id, revision, authority, metadata):
    return EngineeringRef(kind=kind, object_id=object_id, revision=revision, authority=authority,
                          digest=contract_digest(metadata), digest_algorithm="sha256")


@dataclass(frozen=True, slots=True)
class RegisteredReferenceTaskInputs:
    declaration: TaskDeclaration
    input_set_ref: EngineeringRef
    resource_scope_id: str = RESOURCE_SCOPE_ID


@dataclass(frozen=True, slots=True)
class ReferenceTaskInputBinding:
    inputs: RegisteredReferenceTaskInputs
    created: TaskHttpResult
    bound: TaskHttpResult

    @property
    def task_id(self) -> str:
        return self.bound.body.task_id


def _archive(uow, project_id, source_id, reference, metadata, source_record_id, authorization):
    key = reference_key(project_id, reference)
    existing = uow.connection.scalar(select(task_reference_records.c.reference_key).where(
        task_reference_records.c.reference_key == key,
    ))
    if existing is not None:
        old = read_registered_reference(uow.connection, project_id, reference)
        if old.source_id != source_id or old.source_record_id != source_record_id or old.metadata != metadata:
            raise TaskBoundaryError("reference_identity_conflict")
        return
    record = RegisteredReference(
        project_id=project_id, registration_id="reference-input-" + _identity(project_id, key),
        source_id=source_id, source_record_id=source_record_id, reference=reference, metadata=metadata,
        observed_at_utc=datetime.now(UTC),
    )
    register_reference(uow.connection, record, source_bytes=rfc8785.dumps(metadata.model_dump(mode="json")),
                       authorization=authorization.envelope)


def register_reference_inputs_in_uow(
    uow, actor, project_id, registration: SourceImportRegistration, assets: ReferenceAssets,
    *, title: str, goal: str, budget: TaskBudget,
) -> RegisteredReferenceTaskInputs:
    """Participate in the caller's UoW; current permissions precede registration/replay."""
    require_transaction(uow.connection)
    validate_actor(actor)
    if not isinstance(actor, AuthenticatedActor):
        raise IdentityError("authentication_failed")
    resource = AuthoritativeResource(project_id, "project", project_id)
    management = authorize_current(uow, actor, resource, "project.manage")
    archive = authorize_current(uow, actor, resource, "fact.archive")
    authorize_current(uow, actor, resource, "task.command")
    authorize_current(uow, actor, resource, "resource.read")
    if type(registration) is not SourceImportRegistration:
        raise TaskBoundaryError("registered_reference_source_required")
    registration = SourceImportRegistration.model_validate(registration.model_dump(mode="python"))
    intent, _ = read_import_intent(uow.connection, registration.operation_id)
    if intent["project_id"] != project_id or read_source_registration(uow.connection, intent) != registration:
        raise TaskBoundaryError("registered_reference_source_mismatch")
    method_ref = _ref("method", "reference-http-r1", assets.method_revision + "-" + assets.bundle_digest[7:],
                      "integration", assets.method)
    sources = {}
    for domain in ("projects", "integration", "identity", "collaboration"):
        source = TaskFactSource(
            project_id=project_id,
            source_id="reference-inputs-" + domain + "-" + _identity(
                project_id, registration.operation_id, actor.principal.model_dump(mode="json"),
            ),
            producer_domain=domain, authority=domain, principal=actor.principal,
            purpose="product", method_ref=method_ref,
        )
        register_fact_source(uow.connection, source, authorization=management.envelope)
        sources[domain] = source.source_id
    _archive(uow, project_id, sources["integration"], method_ref, assets.method, assets.bundle_digest, archive)
    requirement_ref = _ref("requirement", "reference-requirements-r1",
                           assets.requirement_revision + "-" + assets.requirement_digest[7:], "projects", assets.requirement)
    acceptance = assets.acceptance(method_ref)
    acceptance_ref = _ref("acceptance_assets", "reference-acceptance-r1", assets.bundle_digest[7:], "integration", acceptance)
    resources = ResourcePolicyMetadata(resource_scope_ids=(RESOURCE_SCOPE_ID,), allowed_capabilities=REQUIRED_CAPABILITIES)
    resources_ref = _ref("policy", "reference-controlled-development", REGISTRATION_REVISION, "identity", resources)
    human = HumanPolicyMetadata(is_completion_gate=False, skip_allowed=False)
    human_ref = _ref("policy", "reference-human-policy-disabled", REGISTRATION_REVISION, "identity", human)
    for domain, reference, metadata, source_record_id in (
        ("projects", requirement_ref, assets.requirement, assets.requirement_digest),
        ("integration", acceptance_ref, acceptance, "acceptance-" + assets.bundle_digest),
        ("identity", resources_ref, resources, "resources-" + contract_digest(resources)),
        ("identity", human_ref, human, "human-policy-" + contract_digest(human)),
    ):
        _archive(uow, project_id, sources[domain], reference, metadata, source_record_id, archive)
    declaration = TaskDeclaration(
        title=title, goal=goal, budget=budget, requirement_ref=requirement_ref, acceptance_assets_ref=acceptance_ref,
        source_ref=registration.source_ref, resource_scope_ref=resources_ref, human_test_policy_ref=human_ref,
    )
    refs = (requirement_ref, acceptance_ref, registration.source_ref, resources_ref, human_ref, method_ref)
    set_digest = input_set_digest(refs)
    value = InputSet(input_set_id="reference-engineering-" + set_digest[7:], references=refs, set_digest=set_digest)
    metadata = InputSetMetadata(input_set=value)
    reference = _ref("input_set", value.input_set_id, REGISTRATION_REVISION, "collaboration", metadata)
    _archive(uow, project_id, sources["collaboration"], reference, metadata, set_digest, archive)
    return RegisteredReferenceTaskInputs(declaration, reference)


class ReferenceTaskApplication:
    def __init__(self, engine, asset_repository):
        self.engine, self.asset_repository = engine, asset_repository

    def create(
        self, actor, project_id: str, source_registration: SourceImportRegistration,
        *, expected_project_revision: int, idempotency_key: str,
        title: str = "固定便签参照的工程准备", goal: str = "按固定参照需求建立独立工程输入与工作区，后续构建和验收另行登记。",
        budget: TaskBudget | None = None,
    ) -> ReferenceTaskInputBinding:
        """One short transaction covers registration, draft creation and initial binding.

        Asset reading occurs before it. No Git, filesystem writes, workflow enqueue,
        candidate, acceptance result or human conclusion is produced by this call.
        """
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160:
            raise TaskBoundaryError("reference_task_idempotency_key_invalid", status_code=422)
        assets = load_reference_assets(self.asset_repository)
        key = "reference-task-" + _identity(idempotency_key)
        try:
            with UnitOfWork(self.engine) as uow:
                inputs = register_reference_inputs_in_uow(
                    uow, actor, project_id, source_registration, assets,
                    title=title, goal=goal, budget=budget or TaskBudget(amount="0", currency="USD"),
                )
                created = create_task(uow, actor, project_id, CreateTaskRequest(
                    expected_project_revision=expected_project_revision, declaration=inputs.declaration,
                ), key + "-create")
                if created.status_code != 201:
                    raise TaskBoundaryError(created.body.code, status_code=created.status_code)
                initial = BindInitialTaskInputRequest(
                    expected_version=created.body.version, expected_control_revision=created.body.control_revision,
                    expected_input_validity_revision=created.body.input_validity_revision, input_set_ref=inputs.input_set_ref,
                )
                bound = bind_initial_input_in_uow(uow, actor, created.body.task_id, initial, idempotency_key=key + "-bind")
                if bound.status_code != 200:
                    raise TaskBoundaryError(bound.body.code, status_code=bound.status_code)
                return ReferenceTaskInputBinding(inputs, created, bound)
        except CommandConflict as error:
            raise TaskBoundaryError(str(error)) from None
