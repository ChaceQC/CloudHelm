"""Worker composition for trusted, mutable Workspace development environments."""

from __future__ import annotations

from importlib import import_module
from contextlib import nullcontext
from typing import Callable

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.workspaces.development_application import WorkspaceDevelopmentApplication
from modules.workspaces.development_tables import (
    workspace_development_environment_operations as development_operations,
    workspace_development_environments as development_environments,
)
from modules.workspaces.development_queries import WorkspaceDevelopmentError
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.development_environment import (
    WorkspaceDevelopmentEnvironmentObservation,
)
from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.workspace_candidates import RegisteredWorkspaceReader
from packages.contracts.p1.workspace_git import WorkspaceBinding


_QUERY_NOT_FOUND = "workspace_development_operation_not_found"


def _runner_modules():
    registry_module = import_module("services.dev-runner.workspace_development_registry")
    lifecycle_module = import_module("services.dev-runner.workspace_development_lifecycle")
    return registry_module, lifecycle_module


class EngineeringDevelopmentRuntime:
    """One trusted C5 controller for the registered pool and its live readers."""

    def __init__(self, engine, control_engine, registry, *, controller_factory: Callable | None = None):
        self.engine, self.control_engine, self.registry = engine, control_engine, registry
        registry_module, lifecycle_module = _runner_modules()
        self._controller_type = lifecycle_module.WorkspaceDevelopmentController
        self._controller_factory = self._controller_type if controller_factory is None else controller_factory
        self._controller = None
        self.application = WorkspaceDevelopmentApplication(
            engine, control_engine,
            prepared_spec_for=registry_module.registered_development_spec,
            runtime_for=self.controller_for,
        )

    def _access(self, operation_id: str, *, reconciliation: bool):
        access = self.application.read_operation(operation_id, reconciliation=reconciliation)
        request = access.intent.request
        spec = getattr(request, "spec", None)
        raw_reference = spec.storage_ref if spec is not None else access.environment["storage_ref_json"]
        try:
            reference = (raw_reference if type(raw_reference) is DevelopmentStorageRef
                         else DevelopmentStorageRef.model_validate(raw_reference))
            registration = self.registry.registration
            if (registration is None or reference != registration.storage
                    or reference.purpose != "workspace"):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise WorkspaceDevelopmentError("workspace_development_storage_not_registered") from None
        return access

    def gate(self, operation_id: str):
        """Re-read authority and the current Task/Workspace state before a side effect."""
        return self._access(operation_id, reconciliation=False)

    def _controller_for_access(self, access):
        if self._controller is None:
            controller = self._controller_factory(self.registry, self.gate)
            if type(controller) is not self._controller_type:
                raise WorkspaceDevelopmentError("workspace_development_controller_required")
            self._controller = controller
        return self._controller

    def controller_for(self, operation_id: str):
        access = self._access(operation_id, reconciliation=True)
        controller = self._controller_for_access(access)
        if getattr(self, "resources", None) is not None:
            with self.resources.admitted() as storage:
                controller.resource_binding = self.resources.environment(access, storage)
        return controller

    @staticmethod
    def _observation_state(intent, observation):
        request = intent.request
        if observation.state == "failed":
            stopped = (
                observation.stop_fact is not None
                and observation.stop_fact.outcome == "confirmed_stopped"
                or observation.runtime_fact is not None
                and observation.runtime_fact.status == "stopped"
            )
            return "failed" if stopped else "unknown"
        target = {
            "prepare": "ready", "suspend": "suspended", "resume": "ready",
            "reset_data": "ready", "dispose": "disposed",
        }[request.action]
        return "succeeded" if observation.state == target else "unknown"

    @staticmethod
    def _result(operation_id, state, code):
        return {"operation_id": operation_id, "state": state, "code": code}

    def execute(self, operation_id: str):
        try:
            access = self._access(operation_id, reconciliation=True)
            request = access.intent.request
            with self.resources.admitted() as storage:
                journal_type = import_module("services.dev-runner.workspace_development_journal").WorkspaceDevelopmentJournal
                operation = journal_type(storage).operation(operation_id)
                start = request.action == "prepare" and operation is None
                if start:
                    self.gate(operation_id)
                binding = self.resources.environment(access, storage, start=start)
            controller = self._controller_for_access(access)
            controller.resource_binding = binding
            if binding is None and request.action not in {"suspend", "dispose"} and operation is None:
                return self._result(operation_id, "unknown", "workspace_development_legacy_start_retired")
            with binding.context() if binding is not None else nullcontext():
                result = self._execute(operation_id, allow_apply=binding is not None or request.action in {"suspend", "dispose"})
                if (binding is not None and not binding.stopped and request.action == "dispose"
                        and result["state"] == "succeeded"):
                    binding.stop()
                return result
        except Exception:
            return self._result(operation_id, "unknown", "workspace_development_resources_unsettled")

    def _execute(self, operation_id: str, *, allow_apply=True):
        """Query the stable physical identity first; apply only a proven absent operation."""
        try:
            access = self._access(operation_id, reconciliation=True)
            controller = self._controller_for_access(access)
        except Exception:
            return self._result(operation_id, "unknown", "workspace_development_hub_state_unavailable")

        try:
            prior = controller.query(operation_id)
            if type(prior) is not WorkspaceDevelopmentEnvironmentObservation:
                return self._result(operation_id, "unknown", "workspace_development_observation_unavailable")
        except Exception as error:
            if getattr(error, "category", None) != _QUERY_NOT_FOUND:
                return self._result(operation_id, "unknown", "workspace_development_query_unsettled")
            if not allow_apply:
                return self._result(operation_id, "unknown", "workspace_development_legacy_start_retired")
            try:
                current = self.gate(operation_id)
                applied = controller.apply(current.intent)
            except Exception as error:
                code = getattr(error, "category", None) or getattr(error, "code", None)
                return self._result(operation_id, "unknown", code or "workspace_development_operation_unsettled")
            if type(applied) is not WorkspaceDevelopmentEnvironmentObservation:
                return self._result(operation_id, "unknown", "workspace_development_operation_unsettled")

        try:
            binding = getattr(controller, "resource_binding", None)
            if access.intent.request.action == "dispose" and binding is not None and not binding.stopped:
                final = controller.query(operation_id)
                if final is not None and final.state == "disposed":
                    binding.stop()
            observation = self.application.register_observation(operation_id)
            if type(observation) is not WorkspaceDevelopmentEnvironmentObservation:
                return self._result(operation_id, "unknown", "workspace_development_observation_unavailable")
        except Exception:
            return self._result(operation_id, "unknown", "workspace_development_receipt_unsettled")

        state = self._observation_state(access.intent, observation)
        if state == "succeeded":
            return self._result(operation_id, state, "workspace_development_operation_registered")
        if state == "failed":
            return self._result(operation_id, state, "workspace_development_environment_failed")
        return self._result(operation_id, "unknown", "workspace_development_operation_unsettled")

    def registered_readers(self, binding: WorkspaceBinding):
        """Return only journal-backed readers for the one open, exact Workspace binding."""
        try:
            with UnitOfWork(self.control_engine) as uow:
                rows = uow.connection.execute(select(development_environments).where(
                    development_environments.c.workspace_id == binding.workspace_id,
                    development_environments.c.state != "disposed",
                ).limit(2)).mappings().all()
                if len(rows) > 1:
                    raise ValueError
                if not rows:
                    return ()
                environment = rows[0]
                current_binding = WorkspaceBinding.model_validate(environment["binding_json"])
                if current_binding != binding:
                    return ()
                operations = uow.connection.execute(select(
                    development_operations.c.operation_id,
                ).where(
                    development_operations.c.environment_id == environment["environment_id"],
                ).order_by(development_operations.c.accepted_environment_revision.desc()).limit(1)).all()
                if len(operations) != 1:
                    raise ValueError
                operation_id = operations[0][0]
            access = self._access(operation_id, reconciliation=True)
            if (access.intent.request.binding != binding
                    or access.environment["environment_id"] != environment["environment_id"]):
                raise ValueError
            readers = self.controller_for(operation_id).registered_readers(binding)
            if not isinstance(readers, tuple) or len(readers) > 32:
                raise ValueError
            checked = tuple(RegisteredWorkspaceReader.model_validate(item.model_dump())
                            for item in readers if type(item) is RegisteredWorkspaceReader)
            if (len(checked) != len(readers)
                    or len({item.container_id for item in checked}) != len(checked)):
                raise ValueError
            return checked
        except Exception:
            raise WorkspaceFileError("workspace_development_readers_unavailable") from None

    def close(self):
        controller = self._controller
        if controller is not None:
            controller.close()
            self._controller = None
