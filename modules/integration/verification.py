"""Trusted producer entry: execute fixed assets, then archive exact bounded facts."""

from datetime import UTC, datetime
from uuid import uuid4

import rfc8785
from sqlalchemy import insert, select

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress, task_resource
from modules.collaboration.records import read_fact_source, read_registered_reference, reference_key, register_reference
from modules.delivery.release_recipe import delivery_digest
from modules.integration.candidates import _current_input, _operation_access, _read, _ref
from modules.integration.reference_acceptance import CollectedPhase, collect_reference_phase
from modules.integration.tables import verification_dependencies
from modules.projects.reference_assets import ReferenceAssetError, load_reference_assets
from modules.sync.events import append_event
from modules.sync.tables import event_log
from packages.contracts.p0.engineering_contracts import EvidenceRecord, InputSet, input_set_digest
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p1.task_facts import EvidenceMetadata, RegisteredReference, SourceMetadata
from packages.contracts.p2.verification import (
    VERIFICATION_SCHEMA, FinalizeVerificationRequest, VerificationPhase, VerificationPhaseRequest, VerificationReport,
    VerificationSelection,
)


def _event(connection, event_id, event_type, model):
    payload = connection.scalar(select(event_log.c.payload).where(
        event_log.c.event_id == event_id, event_log.c.event_type == event_type,
    ))
    return model.model_validate(payload) if payload is not None else None


def _prepare(uow, actor, task_id, request, key):
    task, authorization = lock_task_access(uow, actor, task_id, "fact.archive")
    source = read_fact_source(uow.connection, task["project_id"], request.source_id)
    if (source.principal != actor.principal or source.producer_domain != "integration"
            or source.authority != "integration" or source.purpose != "product"):
        raise TaskBoundaryError("verification_product_source_required", status_code=403)
    resource = task_resource(task)
    intent = CommandIntent(request_schema_revision=VERIFICATION_SCHEMA, caller=actor.principal,
                           scope=resource.scope, target=resource.target_scope, action="fact.archive",
                           expected_resource_revision=request.expected_version)
    envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                               request_digest=request_digest(intent, request))
    return task, authorization, envelope, lock_and_get(uow.connection, envelope)


def _append(uow, command_id, task, event_id, event_type, payload):
    append_event(uow.connection, command_id=command_id, project_id=task["project_id"],
                 aggregate_kind="verification", aggregate_id=event_id, aggregate_version=1,
                 event_id=event_id, event_type=event_type, schema_version=VERIFICATION_SCHEMA, payload=payload)


def _assets(connection, project_id, candidate, repository):
    assets = load_reference_assets(repository)
    acceptance_ref = next(ref for ref in candidate.input_set.references if ref.kind == "acceptance_assets")
    acceptance = read_registered_reference(connection, project_id, acceptance_ref)
    method = read_registered_reference(connection, project_id, acceptance.metadata.method_ref)
    if acceptance.metadata != assets.acceptance(method.reference) or method.metadata != assets.method:
        raise TaskBoundaryError("verification_asset_revision_unsupported")
    return assets, acceptance, method


def report_evidence_ref(report):
    metadata = EvidenceMetadata(evidence=report.evidence, role="verification",
                                check_ids=report.expected_check_ids, acceptance_assets_ref=report.acceptance_assets_ref)
    return _ref("evidence", report.report_id, VERIFICATION_SCHEMA, "integration", metadata)


class VerificationApplication:
    def __init__(self, engine, control_engine, repository):
        self.engine, self.control_engine, self.repository = engine, control_engine, repository

    def run_phase(self, actor, task_id, request: VerificationPhaseRequest, *, base_url, idempotency_key,
                  timeout_seconds=300):
        """Internal trusted runner entry, never a public endpoint accepting an origin or report.

        The setup producer binds the disposable instance and restart/fault preparation.
        An intent without a finished fact is unknown and is never automatically rerun.
        """
        with UnitOfWork(self.engine) as uow:
            task, authorization, command, existing = _prepare(uow, actor, task_id, request, idempotency_key)
            if existing is not None:
                phase_id = "verification-phase-" + existing.envelope.command_id
                candidate = _read(uow.connection, task, request.candidate_id)
                _operation_access(uow, actor, task, candidate.build_operation_id)
                result = _event(uow.connection, phase_id, "verification.phase_finished", VerificationPhase)
                if result is None:
                    raise TaskBoundaryError("verification_phase_outcome_unknown", object_ids=(phase_id,))
                return result
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            candidate = _read(uow.connection, task, request.candidate_id)
            _operation_access(uow, actor, task, candidate.build_operation_id)
            if (candidate.control_revision != task["control_revision"]
                    or candidate.input_validity_revision != task["input_validity_revision"]
                    or _current_input(uow.connection, task) != reference_key(task["project_id"], candidate.source_input_set_ref)):
                raise TaskBoundaryError("verification_candidate_not_current")
            assets, _, _ = _assets(uow.connection, task["project_id"], candidate, self.repository)
            setup = read_registered_reference(uow.connection, task["project_id"], request.setup_evidence_ref)
            proof = setup.metadata
            expected_target = delivery_digest({"base_url": base_url, "phase": request.phase,
                                            "candidate_id": candidate.candidate_id,
                                            "input_set_digest": candidate.input_set.set_digest})
            if (read_fact_source(uow.connection, task["project_id"], setup.source_id).purpose != "product"
                    or not isinstance(proof, EvidenceMetadata) or proof.evidence.result != "passed"
                    or proof.evidence.subject_ref != _ref("candidate", candidate.candidate_id,
                        candidate.schema_revision, "integration", candidate)
                    or proof.evidence.input_set_ref != _ref("input_set", candidate.input_set.input_set_id,
                        candidate.schema_revision, "integration", candidate.input_set)
                    or proof.evidence.environment_ref != candidate.environment_ref
                    or request.phase not in proof.evidence.support_scope or proof.fact_digest != expected_target):
                raise TaskBoundaryError("verification_setup_evidence_mismatch")
            phase_id = "verification-phase-" + command.command_id
            _append(uow, command.command_id, task, phase_id + "-intent", "verification.phase_started", request)
            save_result(uow.connection, command, request, status_code=202, authorization=authorization.envelope)
        try:
            collected = collect_reference_phase(self.repository, base_url=base_url, phase=request.phase,
                                                timeout_seconds=timeout_seconds)
        except (ReferenceAssetError, ValueError):
            collected = CollectedPhase(request.phase, assets, (), (), ("verification_execution_unavailable",),
                                       None, "", datetime.now(UTC))
        result = VerificationPhase(phase_id=phase_id, project_id=task["project_id"], task_id=task_id,
            candidate_id=candidate.candidate_id, round_id=request.round_id, phase=request.phase,
            setup_evidence_ref=request.setup_evidence_ref, asset_bundle_digest=collected.assets.bundle_digest,
            passed_check_ids=collected.passed_check_ids, failed_check_ids=collected.failed_check_ids,
            integrity_errors=collected.integrity_errors, exit_code=collected.exit_code,
            output_digest=collected.output_digest or None, observed_at=collected.observed_at)
        with UnitOfWork(self.engine) as uow:
            current, _ = lock_task_access(uow, actor, task_id, "fact.archive")
            _append(uow, command.command_id, current, phase_id, "verification.phase_finished", result)
        return result

    def finalize(self, actor, task_id, request: FinalizeVerificationRequest, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            task, authorization, command, existing = _prepare(uow, actor, task_id, request, idempotency_key)
            if existing is not None:
                report = VerificationReport.model_validate(existing.result)
                _operation_access(uow, actor, task, report.build_operation_id)
                return report
            check_task_revisions(task, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            candidate = _read(uow.connection, task, request.candidate_id)
            _operation_access(uow, actor, task, candidate.build_operation_id)
            assets, acceptance, method = _assets(uow.connection, task["project_id"], candidate, self.repository)
            phases, errors = [], []
            for phase_id in request.phase_ids:
                phase = _event(uow.connection, phase_id, "verification.phase_finished", VerificationPhase)
                if phase is None:
                    errors.append("verification_phase_unfinished")
                    continue
                if (phase.project_id != task["project_id"] or phase.task_id != task_id
                        or phase.candidate_id != candidate.candidate_id or phase.round_id != request.round_id):
                    raise TaskBoundaryError("verification_phase_binding_mismatch")
                phases.append(phase)
                errors.extend(phase.integrity_errors)
                if phase.asset_bundle_digest != assets.bundle_digest:
                    errors.append("verification_asset_bundle_changed")
            if len({p.phase for p in phases}) != len(phases):
                errors.append("verification_duplicate_phase")
            passed = {item for phase in phases for item in phase.passed_check_ids}
            failed = {item for phase in phases for item in phase.failed_check_ids}
            expected = set(assets.required_check_ids)
            missing = expected - passed - failed
            result = ("failed" if failed else "not_run" if not phases and not errors else
                      "unknown" if errors or missing or any(p.exit_code != 0 for p in phases) else "passed")
            report_id = "verification-" + command.command_id
            from modules.delivery.queries import read_build_intent

            _, build = read_build_intent(uow.connection, candidate.build_operation_id)
            source_ref = _ref("source", "candidate-source-" + candidate.candidate_id,
                build.fixed_inputs.candidate.candidate_commit, "integration",
                SourceMetadata(commit=build.fixed_inputs.candidate.candidate_commit))
            refs = (*candidate.input_set.references, source_ref,
                    _ref("candidate", candidate.candidate_id, candidate.schema_revision, "integration", candidate),
                    *(phase.setup_evidence_ref for phase in phases))
            refs = tuple({ref.model_dump_json(): ref for ref in refs}.values())
            digest = input_set_digest(refs)
            inputs = InputSet(input_set_id="verification-inputs-" + digest[7:], references=refs, set_digest=digest)
            evidence = EvidenceRecord(evidence_id=report_id,
                subject_ref=_ref("candidate", candidate.candidate_id, candidate.schema_revision, "integration", candidate),
                input_set_ref=_ref("input_set", inputs.input_set_id, VERIFICATION_SCHEMA, "integration", inputs),
                method_ref=method.reference, environment_ref=candidate.environment_ref, result=result,
                observed_at=datetime.now(UTC), support_scope=("reference_http",))
            report = VerificationReport(report_id=report_id, project_id=task["project_id"], task_id=task_id,
                candidate_id=candidate.candidate_id, build_operation_id=candidate.build_operation_id, round_id=request.round_id,
                source_input_set_ref=candidate.source_input_set_ref, source_ref=source_ref, input_set=inputs,
                control_revision=candidate.control_revision,
                input_validity_revision=candidate.input_validity_revision, acceptance_assets_ref=acceptance.reference,
                asset_bundle_digest=assets.bundle_digest, expected_check_ids=assets.required_check_ids,
                passed_check_ids=tuple(sorted(passed - failed)), failed_check_ids=tuple(sorted(failed)),
                missing_check_ids=tuple(sorted(missing)), integrity_errors=tuple(sorted(set(errors))),
                phases=tuple(phases), evidence=evidence)
            _append(uow, command.command_id, task, report_id, "verification.reported", report)
            metadata = EvidenceMetadata(evidence=evidence, role="verification", check_ids=report.expected_check_ids,
                                        acceptance_assets_ref=acceptance.reference)
            registered = RegisteredReference(project_id=task["project_id"], registration_id=report_id,
                source_id=request.source_id, source_record_id=report_id, reference=report_evidence_ref(report),
                metadata=metadata, observed_at_utc=evidence.observed_at)
            register_reference(uow.connection, registered, source_bytes=rfc8785.dumps(metadata.model_dump(mode="json")),
                               authorization=authorization.envelope)
            refs = (*inputs.references, candidate.source_input_set_ref)
            keys = {reference_key(task["project_id"], ref) for ref in refs}
            uow.connection.execute(insert(verification_dependencies), [dict(report_id=report_id, producer_key=key,
                task_id=task_id, applicability="valid") for key in sorted(keys)])
            save_result(uow.connection, command, report, status_code=201, authorization=authorization.envelope)
            return report

    def accept(self, actor, task_id, request, *, idempotency_key):
        """Select current formal evidence; WorkItem review remains a separate decision."""
        from modules.integration.validity import require_verified_report

        with UnitOfWork(self.engine) as uow:
            task, authorization = lock_task_access(uow, actor, task_id, "task.command")
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-verification-accept-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="task.command",
                expected_resource_revision=request.expected_version)
            command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=idempotency_key,
                                      request_digest=request_digest(intent, request))
            existing = lock_and_get(uow.connection, command)
            if existing is not None:
                return VerificationSelection.model_validate(existing.result)
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            view = require_verified_report(uow.connection, task, request.report_id)
            _operation_access(uow, actor, task, view.report.build_operation_id)
            context = TaskCommandContext(uow, actor, task, authorization, command)
            update_task(context)
            result = VerificationSelection(command_id=command.command_id, task_id=task_id,
                                            version=context.task["version"], report_id=request.report_id)
            append_event(uow.connection, command_id=command.command_id, project_id=task["project_id"],
                aggregate_kind="task", aggregate_id=task_id, aggregate_version=result.version,
                event_id="verification-selection-" + command.command_id, event_type="verification.accepted",
                schema_version=VERIFICATION_SCHEMA, payload=result)
            save_result(uow.connection, command, result, status_code=200, authorization=authorization.envelope)
            return result

    def query(self, actor, task_id, report_id):
        from modules.integration.validity import verification_view

        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            view = verification_view(uow.connection, task, report_id)
            _operation_access(uow, actor, task, view.report.build_operation_id)
            return view
