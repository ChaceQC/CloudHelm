"""Current workspace ownership at command and actual execution boundaries."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Connection

from modules.collaboration.errors import TaskBoundaryError
from modules.workspaces.handoff_tables import workspace_handoffs
from modules.workspaces.operations import WorkspaceError
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.workspace_candidates import candidate_freeze_digest
from packages.contracts.p1.workspace_git import WorkspaceBinding
from packages.contracts.p2.handoffs import WorkspaceHandoffRecord
from packages.contracts.p2.work_item_run import WorkItemRunHandoff


def active_handoff(connection, workspace_id):
    raw = connection.scalar(select(workspace_handoffs.c.record_json).where(
        workspace_handoffs.c.workspace_id == workspace_id, workspace_handoffs.c.state != "agent_owned"))
    return WorkspaceHandoffRecord.model_validate(raw) if raw is not None else None


def require_workspace_writer(connection, workspace, actor, kind, *, executing=False):
    record = active_handoff(connection, workspace["workspace_id"])
    if record is None:
        return
    if (record.state == "human_owned" and kind == "mutate" and actor.principal.kind == "human"
            and actor.principal.subject_id == record.human_user_id):
        if actor.authentication_source == "device_session":
            return
        # A Runtime may act under a recorded human command; that is not an interactive edit.
        from database.commands import get_by_id
        from modules.identity.tables import audit_records

        command = get_by_id(connection, actor.command_id)
        source = connection.scalar(select(audit_records.c.authentication_source).where(
            audit_records.c.decision_id == command.authorization_decision_id))
        if executing and source == "device_session":
            return
    raise WorkspaceError("workspace_write_ownership_conflict")


def require_agent_workspace(connection, task_id, work_item_id):
    from modules.workspaces.tables import workspaces

    workspace_id = connection.scalar(select(workspaces.c.workspace_id).where(
        workspaces.c.task_id == task_id, workspaces.c.work_item_id == work_item_id))
    if workspace_id is not None and active_handoff(connection, workspace_id) is not None:
        raise WorkspaceError("workspace_write_ownership_conflict")


def pending_handoffs(connection, task_id):
    records = connection.scalars(select(workspace_handoffs.c.record_json).where(
        workspace_handoffs.c.task_id == task_id, workspace_handoffs.c.state != "agent_owned")).all()
    result = []
    for raw in records:
        record = WorkspaceHandoffRecord.model_validate(raw)
        spec = record.return_spec or record.takeover_spec
        result.append(OperationClosureFact(operation_ref=EngineeringRef(
            kind="operation", object_id=record.handoff_id, revision="p2-workspace-handoff-r1",
            authority="workspaces", digest=candidate_freeze_digest(spec), digest_algorithm="sha256"),
            owner_kind="task", owner_id=task_id, affects_completion=True, closure="unknown"))
    return tuple(result)


def read_returned_handoff_spec(connection: Connection, workspace: WorkspaceBinding) -> WorkItemRunHandoff | None:
    """Identify the last acknowledged return without reading its changes or receipts."""
    record = workspace_handoffs.c.record_json
    row = connection.execute(select(
        workspace_handoffs.c.handoff_id,
        record[("baseline", "snapshot", "candidate_commit")].astext.label("baseline_commit"),
        record[("returned", "snapshot", "candidate_commit")].astext.label("returned_commit"),
        record[("baseline", "snapshot", "manifest_digest")].astext.label("baseline_manifest_digest"),
        record[("returned", "snapshot", "manifest_digest")].astext.label("returned_manifest_digest"),
    ).where(
        workspace_handoffs.c.workspace_id == workspace.workspace_id,
        workspace_handoffs.c.task_id == workspace.task_id,
        workspace_handoffs.c.state == "agent_owned",
    ).order_by(workspace_handoffs.c.created_at.desc(), workspace_handoffs.c.handoff_id.desc()).limit(1)).mappings().one_or_none()
    if row is None:
        return None
    try:
        return WorkItemRunHandoff.model_validate(row)
    except ValidationError:
        raise TaskBoundaryError("agent_work_item_handoff_invalid") from None
