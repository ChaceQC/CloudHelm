"""Worker composition for registered engineering intents and real local stores."""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.projects.source_commands import SourceImportApplication
from modules.projects.source_tables import project_git_sources
from modules.workspaces.application import WorkspaceApplication
from modules.workspaces.candidate_freeze import CandidateFreezeController
from modules.workspaces.candidate_store import CandidateStore
from modules.workspaces.candidate_writers import process_start_ticks
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.git_objects import GitObjectStore
from modules.workspaces.operations import resolve_workspace_operation_in_uow
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, exists_at
from modules.workspaces.source_import import ReferenceSourceImporter
from modules.workspaces.workfiles import WorkfileStore, _storage_id
from packages.contracts.p1.workspace_candidates import WorkspaceWriterScope, workspace_runtime_scope_id
from packages.contracts.p1.workspace_git import RegisteredGitSource
from packages.contracts.p1.workspace_records import workspace_metadata_digest

from .engineering_development import EngineeringDevelopmentRuntime

registry_module = importlib.import_module("services.dev-runner.engineering_registry")


def _result(operation_id, state, code, **payload):
    return {"operation_id": operation_id, "state": state, "code": code, **payload}


class EngineeringRuntime:
    def __init__(self, engine, control_engine, registry, *, development_controller_factory=None, client=None):
        self.engine, self.control_engine, self.registry = engine, control_engine, registry
        from .engineering_resources import EngineeringResources

        self.resources = EngineeringResources(engine, control_engine, registry)
        self.instance_id = "engineering-worker-" + uuid4().hex
        self.sources = SourceImportApplication(engine, control_engine)
        if client is not None:
            from modules.agent_runtime.operations import notify_operation_in_uow

            notify = lambda uow, operation_id: notify_operation_in_uow(uow, client, operation_id)
        else:
            notify = None
        self.workspaces = WorkspaceApplication(
            engine, control_engine, admit_operation=self._admitted,
            runtime_scope_for=self.runtime_scope_for, load_mutation_content=self._load_mutation_content,
            notify_materialization=notify,
        )
        self._development = EngineeringDevelopmentRuntime(
            engine, control_engine, registry, controller_factory=development_controller_factory,
        )
        self._development.resources = self.resources
        self.development = self._development.application

    def development_controller_for(self, operation_id):
        return self._development.controller_for(operation_id)

    def development_environment(self, operation_id):
        return self._development.execute(operation_id)

    def close(self):
        self._development.close()

    def _admitted(self, operation_id, kind, binding):
        self.registry.current_storage()

    @staticmethod
    def runtime_scope_for(binding):
        return workspace_runtime_scope_id(binding)

    def _source_spec(self, operation_id):
        self.registry.current_storage()
        return self.sources.resolve_import_operation(operation_id)

    def _intent(self, operation_id):
        with UnitOfWork(self.control_engine) as uow:
            return resolve_workspace_operation_in_uow(uow, operation_id, reconciliation=True)[0]

    @contextmanager
    def _git(self, storage, project_id):
        with UnitOfWork(self.control_engine) as uow:
            row = uow.connection.execute(select(project_git_sources).where(
                project_git_sources.c.project_id == project_id,
            )).mappings().one()
            source = RegisteredGitSource.model_validate(row["source_json"])
            if workspace_metadata_digest(source) != row["source_digest"]:
                raise WorkspaceFileError("git_source_record_invalid")
        git = GitObjectStore(storage.git_root)
        try:
            git.register_source(source)
            yield git
        finally:
            git.close()

    def source_import(self, operation_id):
        with self.registry.admit(64 * 1024**2) as storage:
            importer = ReferenceSourceImporter(storage.git_root, registry_module.REPOSITORY, self._source_spec)
            try:
                status = importer.query(operation_id)
                if status.state == "not_found":
                    importer.import_reference(operation_id)
                    status = importer.query(operation_id)
                if status.state != "published":
                    state = "failed" if status.state == "failed" else "unknown"
                    return _result(operation_id, state, status.reason_code or "source_import_unsettled")
                registered = self.sources.finish_import(operation_id, importer)
                return _result(operation_id, "registered", "source_import_registered",
                               registration=registered.model_dump(mode="json"))
            finally:
                importer.close()

    def _materialize(self, storage, git, operation_id, intent):
        reconcile = lambda value: self.workspaces.resolve_materialization_operation(value, reconciliation=True)
        store = WorkfileStore(storage.workspace_root, git, reconcile)
        try:
            root = PrivateRoot(storage.workspace_root)
            try:
                with root.exclusive() as directory:
                    present = exists_at(directory, _storage_id(intent.result.binding))
                    unfinished = any(name.startswith("stage-") for name in os.listdir(directory))
            finally:
                root.close()
            if not present:
                if unfinished:
                    return _result(operation_id, "unknown", "workspace_materialization_pending_reconciliation")
                store.close()
                store = WorkfileStore(storage.workspace_root, git, self.workspaces.resolve_materialization_operation)
                binding = self.workspaces.resolve_materialization_operation(operation_id)
                store.materialize(binding, operation_id)
                store.close()
                store = WorkfileStore(storage.workspace_root, git, reconcile)
            value = self.workspaces.finish_materialization(operation_id, store)
            return _result(operation_id, "registered", "workspace_materialization_registered",
                           registration=value.model_dump(mode="json"))
        finally:
            store.close()

    def _mutate(self, storage, git, operation_id):
        reconcile = lambda value: self.workspaces.resolve_mutation_operation(value, reconciliation=True)
        service = WorkspaceFileService(storage.workspace_root, git, reconcile)
        try:
            status = service.query(operation_id)
            if status.state == "not_found":
                service.close()
                service = WorkspaceFileService(storage.workspace_root, git, self.workspaces.resolve_mutation_operation)
                service.apply(operation_id)
                service.close()
                service = WorkspaceFileService(storage.workspace_root, git, reconcile)
                status = service.query(operation_id)
            if status.state not in {"applied", "not_applied"}:
                return _result(operation_id, "unknown", status.reason_code or "workspace_mutation_unsettled")
            value = self.workspaces.finish_mutation(operation_id, service)
            return _result(operation_id, "registered", "workspace_mutation_registered",
                           registration=value.model_dump(mode="json"))
        finally:
            service.close()

    def _candidate_store(self, storage, git, intent, *, reconciliation):
        def resolve_scope(scope_id):
            self.registry.current_storage()
            spec = self.workspaces.resolve_candidate_operation(intent.result.operation_id)
            if scope_id != spec.runtime_scope_id or scope_id != self.runtime_scope_for(spec.binding):
                raise WorkspaceFileError("workspace_runtime_scope_mismatch")
            readers = self._development.registered_readers(spec.binding)
            return WorkspaceWriterScope(scope_id=scope_id, binding=spec.binding,
                service_instance_id=self.instance_id, service_pid=os.getpid(),
                service_start_ticks=process_start_ticks(os.getpid()), readers=readers)

        resolver = lambda value: self.workspaces.resolve_candidate_operation(value, reconciliation=reconciliation)
        return CandidateStore(storage.workspace_root, git, resolver, CandidateFreezeController(resolve_scope))

    def _candidate(self, storage, git, operation_id, intent):
        store = self._candidate_store(storage, git, intent, reconciliation=True)
        try:
            status = store.query(operation_id)
            if status.state == "not_found":
                store.close()
                store = self._candidate_store(storage, git, intent, reconciliation=False)
                store.capture(operation_id)
                store.close()
                store = self._candidate_store(storage, git, intent, reconciliation=True)
                status = store.query(operation_id)
            if status.state != "captured":
                return _result(operation_id, "unknown", status.reason_code or "workspace_candidate_unsettled")
            value = self.workspaces.finish_candidate(operation_id, store)
            return _result(operation_id, "registered", "workspace_candidate_registered",
                           registration=value.model_dump(mode="json"))
        finally:
            store.close()

    def workspace_operation(self, operation_id):
        with self.registry.admit(128 * 1024**2) as storage:
            intent = self._intent(operation_id)
            with self._git(storage, intent.result.binding.project_id) as git:
                kind = intent.result.kind
                if kind == "materialize":
                    return self._materialize(storage, git, operation_id, intent)
                if kind == "mutate":
                    return self._mutate(storage, git, operation_id)
                if kind == "candidate":
                    return self._candidate(storage, git, operation_id, intent)
                raise WorkspaceFileError("workspace_operation_kind_invalid")

    def stage_mutation_content(self, content: bytes):
        """Internal authenticated adapter: stage before accepting the digest-only intent."""
        payloads = importlib.import_module("services.dev-runner.engineering_payloads")
        return payloads.stage_mutation_content(self.registry, content)

    def _load_mutation_content(self, operation_id):
        storage = self.registry.current_storage()
        intent = self._intent(operation_id)
        replacement = intent.request.replacement
        if intent.request.kind != "mutate" or replacement is None:
            raise WorkspaceFileError("workspace_mutation_content_invalid")
        payloads = importlib.import_module("services.dev-runner.engineering_payloads")
        return payloads.load_mutation_content(storage, replacement)

    def build(self, operation_id):
        from .engineering_build import execute_build

        return execute_build(self, operation_id)


def create_engineering_runtime(pools, registration=None, *, development_controller_factory=None, client=None):
    selected = registry_module.load_registration() if registration is None else registration
    return EngineeringRuntime(
        pools.normal, pools.control, registry_module.EngineeringRegistry(selected),
        development_controller_factory=development_controller_factory, client=client,
    )
