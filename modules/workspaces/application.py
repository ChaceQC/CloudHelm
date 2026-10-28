"""Transaction owner for workspace commands and trusted physical-query hooks."""

from database.uow import UnitOfWork
from modules.workspaces.commands import accept_workspace_command_in_uow
from modules.workspaces.operations import (
    WorkspaceError, candidate_spec, mutation_spec, read_workspace_row, resolve_workspace_operation_in_uow,
)
from modules.workspaces.queries import (
    query_workspace_in_uow, query_workspace_operation_in_uow, read_physical_candidate_in_uow,
    workspace_read_spec_in_uow,
)
from modules.workspaces.receipts import (
    register_workspace_receipt_in_uow, verify_candidate, verify_materialization, verify_mutation,
)
from packages.contracts.p1.workspace_requests import (
    CreateWorkspaceRequest, MaterializeWorkspaceRequest, MutateWorkspaceFileRequest, SubmitWorkspaceCandidateRequest,
    WorkspaceRequest,
)


class WorkspaceApplication:
    def __init__(self, engine, control_engine, *, admit_operation=None, runtime_scope_for=None,
                 load_mutation_content=None, enqueue_operation=None, notify_materialization=None):
        self.engine, self.control_engine = engine, control_engine
        self.admit_operation, self.runtime_scope_for = admit_operation, runtime_scope_for
        self.load_mutation_content, self.enqueue_operation = load_mutation_content, enqueue_operation
        self.notify_materialization = notify_materialization

    def _command(self, actor, target_id, request: WorkspaceRequest, schema, idempotency_key):
        if type(request) is not schema:
            raise WorkspaceError("workspace_request_invalid", status_code=422)
        with UnitOfWork(self.engine) as uow:
            workspace_id = None if schema is CreateWorkspaceRequest else target_id
            task_id = target_id if workspace_id is None else read_workspace_row(uow.connection, workspace_id)["task_id"]
            return accept_workspace_command_in_uow(
                uow, actor, task_id, request, idempotency_key=idempotency_key, workspace_id=workspace_id,
                runtime_scope_for=self.runtime_scope_for, enqueue_operation=self.enqueue_operation,
            )

    def create(self, actor, task_id, request: CreateWorkspaceRequest, *, idempotency_key):
        return self._command(actor, task_id, request, CreateWorkspaceRequest, idempotency_key)

    def materialize(self, actor, workspace_id, request: MaterializeWorkspaceRequest, *, idempotency_key):
        return self._command(actor, workspace_id, request, MaterializeWorkspaceRequest, idempotency_key)

    def mutate(self, actor, workspace_id, request: MutateWorkspaceFileRequest, *, idempotency_key):
        return self._command(actor, workspace_id, request, MutateWorkspaceFileRequest, idempotency_key)

    def submit_candidate(self, actor, workspace_id, request: SubmitWorkspaceCandidateRequest, *, idempotency_key):
        return self._command(actor, workspace_id, request, SubmitWorkspaceCandidateRequest, idempotency_key)

    def query(self, actor, workspace_id):
        with UnitOfWork(self.control_engine) as uow:
            return query_workspace_in_uow(uow, actor, workspace_id)

    def query_operation(self, actor, workspace_id, operation_id):
        with UnitOfWork(self.control_engine) as uow:
            return query_workspace_operation_in_uow(uow, actor, workspace_id, operation_id)

    def query_candidate(self, actor, workspace_id, candidate_id):
        with UnitOfWork(self.control_engine) as uow:
            return read_physical_candidate_in_uow(uow, actor, workspace_id, candidate_id)

    def read_spec(self, actor, workspace_id):
        with UnitOfWork(self.control_engine) as uow:
            return workspace_read_spec_in_uow(uow, actor, workspace_id)

    def _resolve(self, operation_id, kind, reconciliation):
        with UnitOfWork(self.control_engine) as uow:
            intent, _, _, _ = resolve_workspace_operation_in_uow(uow, operation_id, reconciliation=reconciliation)
            if intent.result.kind != kind:
                raise WorkspaceError("workspace_operation_kind_invalid")
        if not reconciliation:
            # The executor must already hold its real storage admission context.
            # This callback checks that live admission; it must not briefly open a
            # context and then return an unpinned path for subsequent operations.
            if self.admit_operation is None:
                raise WorkspaceError("workspace_execution_admission_unavailable")
            if self.admit_operation(operation_id, kind, intent.result.binding) is not None:
                raise WorkspaceError("workspace_execution_admission_invalid")
        return intent

    def resolve_materialization_operation(self, operation_id, *, reconciliation=False):
        """reconciliation=True is exclusively for WorkfileStore.query, never materialize."""
        return self._resolve(operation_id, "materialize", reconciliation).result.binding

    def resolve_mutation_operation(self, operation_id, content=None, *, reconciliation=False):
        """Resolve staged bytes by digest; reconciliation is exclusively query-only."""
        intent = self._resolve(operation_id, "mutate", reconciliation)
        if intent.request.action == "write" and content is None:
            if self.load_mutation_content is None:
                raise WorkspaceError("workspace_mutation_content_unavailable")
            content = self.load_mutation_content(operation_id)
        return mutation_spec(intent, content)

    def resolve_candidate_operation(self, operation_id, *, reconciliation=False):
        """reconciliation=True is exclusively for CandidateStore.query/open_candidate."""
        return candidate_spec(self._resolve(operation_id, "candidate", reconciliation))

    def finish_materialization(self, operation_id, store):
        binding = self.resolve_materialization_operation(operation_id, reconciliation=True)
        verified = verify_materialization(operation_id, binding, store)
        with UnitOfWork(self.engine) as uow:
            result = register_workspace_receipt_in_uow(uow, operation_id, verified)
            if self.notify_materialization is not None:
                self.notify_materialization(uow, operation_id)
            return result

    def finish_mutation(self, operation_id, service):
        verified = verify_mutation(operation_id, service)
        with UnitOfWork(self.engine) as uow:
            result = register_workspace_receipt_in_uow(uow, operation_id, verified)
            if self.notify_materialization is not None:
                self.notify_materialization(uow, operation_id)
            return result

    def finish_candidate(self, operation_id, store):
        verified = verify_candidate(operation_id, store)
        with UnitOfWork(self.engine) as uow:
            result = register_workspace_receipt_in_uow(uow, operation_id, verified)
            if self.notify_materialization is not None:
                self.notify_materialization(uow, operation_id)
            return result
