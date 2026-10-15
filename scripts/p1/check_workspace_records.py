"""Narrow WSL structure checks; synthetic rows grant no engineering acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from database.commands import commands
from database.connection import create_engine_from_settings
from database.maintenance import initialize_database
from database.models import load_business_metadata
from database.permissions import WORKSPACE_INSERTS, WORKSPACE_RECEIPT_COLUMNS
from database.readiness import DatabaseNotReady, assert_runtime_ready, assert_schema_ready
from database.tables import BUSINESS_REVISION, runtime_baseline
from modules.collaboration.tables import task_declarations, tasks, work_items
from modules.identity.tables import audit_records, users
from modules.projects.source_tables import project_git_sources
from modules.projects.tables import projects
from modules.workspaces.tables import workspace_candidates, workspaces
from packages.contracts.p1.workspace_git import (
    CandidateSnapshot, RegisteredGitSource, WorkspaceBinding, WorkspaceFiles,
)
from packages.contracts.p1.workspace_records import (
    GitSourceRecord, PhysicalCandidateRecord, WorkspaceRecord, workspace_metadata_digest,
)
from scripts.p1.database_fixture import database_fixture

TABLES = (project_git_sources, workspaces, workspace_candidates)


class WorkspaceStructureFailure(AssertionError):
    """Only fixed categories may be printed; never driver or credential details."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise WorkspaceStructureFailure(code)


def expect_database_rejection(connection, operation, state: str, constraint: str | None = None) -> None:
    try:
        with connection.begin_nested():
            operation()
    except DBAPIError as failure:
        require(getattr(failure.orig, "sqlstate", None) == state, "unexpected_rejection_sqlstate")
        if constraint is not None:
            require(failure.orig.diag.constraint_name == constraint, "unexpected_rejection_constraint")
    else:
        raise WorkspaceStructureFailure("invalid_structure_was_allowed")


def records():
    source = RegisteredGitSource(
        project_id="structure-project-a", source_id="structure-source-a", source_revision=1,
        kind="managed_bare", target_branch="refs/heads/main", object_format="sha1", access_mode="read_write",
    )
    binding = WorkspaceBinding(
        workspace_id="structure-workspace", project_id=source.project_id, task_id="structure-task-a",
        work_item_id="structure-item-a", owner_user_id="structure-owner", source_id=source.source_id,
        source_revision=1, base_commit="a" * 40, workspace_revision=0, write_generation=0,
    )
    files = WorkspaceFiles(
        binding=binding, operation_id="structure-materialize", storage_id="workspace-" + "a" * 64,
        manifest_digest="sha256:" + "b" * 64, file_count=1, total_bytes=5,
    )
    snapshot = CandidateSnapshot(
        binding=binding, candidate_id="structure-candidate", candidate_commit="c" * 40,
        parent_commit=binding.base_commit, freeze_operation_id="structure-freeze",
        storage_id="candidate-" + "d" * 64, manifest_digest=files.manifest_digest,
    )
    common = {"authorization_decision_id": "structure-authorization", "created_at": datetime.now(UTC)}
    source_record = GitSourceRecord(
        source=source, source_digest=workspace_metadata_digest(source),
        registered_by_command_id="structure-source-a-command",
        authorization_decision_id=common["authorization_decision_id"], registered_at=common["created_at"],
    )
    workspace_record = WorkspaceRecord(
        binding=binding, binding_digest=workspace_metadata_digest(binding), files=files,
        files_digest=workspace_metadata_digest(files), created_by_command_id="structure-workspace-command", **common,
    )
    candidate_record = PhysicalCandidateRecord(
        snapshot=snapshot, snapshot_digest=workspace_metadata_digest(snapshot),
        created_by_command_id="structure-candidate-command", **common,
    )
    checks = (
        (source_record, {"source_digest": "sha256:" + "0" * 64}),
        (workspace_record, {"binding_digest": "sha256:" + "0" * 64}),
        (workspace_record, {"files_digest": None}),
        (workspace_record, {"files": {**files.model_dump(mode="json"),
                                     "binding": {**binding.model_dump(), "workspace_revision": 1}}}),
        (candidate_record, {"snapshot_digest": "sha256:" + "0" * 64}),
    )
    for record, changes in checks:
        try:
            type(record).model_validate({**record.model_dump(mode="json"), **changes})
        except ValidationError:
            pass
        else:
            raise WorkspaceStructureFailure("invalid_record_contract_was_allowed")
    return source_record, workspace_record, candidate_record


def workspace_values(record: WorkspaceRecord) -> dict:
    return {
        **record.binding.model_dump(), "binding_json": record.binding.model_dump(mode="json"),
        "binding_digest": record.binding_digest, "files_json": record.files.model_dump(mode="json"),
        "files_digest": record.files_digest, "materialization_operation_id": record.files.operation_id,
        "storage_id": record.files.storage_id, "created_by_command_id": record.created_by_command_id,
        "authorization_decision_id": record.authorization_decision_id,
    }


def seed(connection, source_record, workspace_record, candidate_record) -> None:
    """Maintenance-only synthetic FK parents; these are not accepted application commands."""
    connection.execute(insert(users).values(user_id="structure-owner", display_name="Structure fixture"))
    for suffix in ("a", "b"):
        connection.execute(insert(projects).values(
            project_id="structure-project-" + suffix, name="Structure fixture", owner_user_id="structure-owner",
        ))
    connection.execute(insert(audit_records).values(
        decision_id="structure-authorization", audit_session_id="structure-audit", authentication_source="maintenance",
        subject_id="structure-owner", scope_json={}, target_json={}, action="project.manage",
        outcome="allowed", reason_code="synthetic_structure_fixture",
    ))
    for name in ("declaration-a", "declaration-b", "source-a", "source-b", "workspace", "candidate", "spare"):
        connection.execute(insert(commands).values(
            command_id="structure-" + name + "-command", caller_kind="human", subject_id="structure-owner",
            project_id="structure-project-a", resource_kind="structure_fixture", resource_id=name,
            idempotency_key=name, request_digest="sha256:" + "e" * 64, envelope_json={}, status_code=202,
            result_json={"synthetic_structure_fixture": True}, audit_session_id="structure-audit",
            authorization_decision_id="structure-authorization",
        ))
    for suffix in ("a", "b"):
        connection.execute(insert(task_declarations).values(
            declaration_id="structure-declaration-" + suffix, project_id="structure-project-" + suffix,
            declaration_json={}, declaration_digest="sha256:" + "f" * 64,
            created_by_command_id="structure-declaration-" + suffix + "-command",
        ))
        connection.execute(insert(tasks).values(
            task_id="structure-task-" + suffix, project_id="structure-project-" + suffix,
            declaration_id="structure-declaration-" + suffix,
        ))
        connection.execute(insert(work_items).values(
            work_item_id="structure-item-" + suffix, task_id="structure-task-" + suffix,
            declaration_id="structure-declaration-" + suffix, goal="Synthetic structure check",
        ))
        source = RegisteredGitSource.model_validate({
            **source_record.source.model_dump(), "project_id": "structure-project-" + suffix,
            "source_id": "structure-source-" + suffix,
        })
        connection.execute(insert(project_git_sources).values(
            project_id=source.project_id, source_id=source.source_id, source_revision=source.source_revision,
            source_json=source.model_dump(mode="json"), source_digest=workspace_metadata_digest(source),
            registered_by_command_id="structure-source-" + suffix + "-command",
            authorization_decision_id="structure-authorization",
        ))
    connection.execute(insert(workspaces).values(**workspace_values(workspace_record)))
    snapshot = candidate_record.snapshot
    connection.execute(insert(workspace_candidates).values(
        **snapshot.binding.model_dump(exclude={"base_commit"}),
        **snapshot.model_dump(exclude={"binding", "manifest_digest"}),
        snapshot_json=snapshot.model_dump(mode="json"), snapshot_digest=candidate_record.snapshot_digest,
        created_by_command_id=candidate_record.created_by_command_id,
        authorization_decision_id=candidate_record.authorization_decision_id,
    ))


def check_structure(connection, source_record, workspace_record, candidate_record) -> int:
    metadata = load_business_metadata()
    names = {table.name for table in TABLES} | {"tasks", "work_items"}
    context = MigrationContext.configure(connection, opts={
        "include_schemas": True,
        "include_name": lambda name, kind, parent: kind != "schema" or name == "cloudhelm",
        "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table" or name in names,
    })
    require(not compare_metadata(context, metadata), "metadata_migration_drift")
    inspector = inspect(connection)
    for table in TABLES:
        expected = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}
        actual = {item["name"] for item in inspector.get_check_constraints(table.name, schema="cloudhelm")}
        require(expected == actual, "metadata_check_constraint_drift")
    seed(connection, source_record, workspace_record, candidate_record)
    def workspace_probe(changes):
        binding = {**workspace_record.binding.model_dump(), "workspace_id": "structure-probe-workspace", **changes}
        return insert(workspaces).values(
            **binding, binding_json=binding, binding_digest=workspace_metadata_digest(workspace_record.binding),
            created_by_command_id="structure-spare-command", authorization_decision_id="structure-authorization",
        )

    snapshot = candidate_record.snapshot.model_dump(mode="json")
    snapshot.update(candidate_id="structure-probe-candidate", freeze_operation_id="structure-probe-freeze",
                    storage_id="candidate-" + "0" * 64)
    snapshot["binding"]["owner_user_id"] = "unknown-owner"
    candidate_probe = insert(workspace_candidates).values(
        **{key: value for key, value in snapshot["binding"].items() if key != "base_commit"},
        **{key: value for key, value in snapshot.items() if key not in {"binding", "manifest_digest"}},
        snapshot_json=snapshot, snapshot_digest=candidate_record.snapshot_digest,
        created_by_command_id="structure-spare-command", authorization_decision_id="structure-authorization",
    )
    checks = (
        (update(project_git_sources).values(source_json={}), "23514", "ck_project_git_sources_source_identity"),
        (workspace_probe({"source_id": "structure-source-b"}), "23503", "fk_workspaces_source_binding"),
        (workspace_probe({"project_id": "structure-project-b", "source_id": "structure-source-b"}),
         "23503", "fk_workspaces_task_owner"),
        (workspace_probe({"work_item_id": "structure-item-b"}), "23503", "fk_workspaces_work_item_owner"),
        (update(workspaces).values(binding_json={}), "23514", "ck_workspaces_binding_identity"),
        (update(workspaces).values(files_digest=None), "23514", "ck_workspaces_files_receipt_complete"),
        (candidate_probe, "23503", "fk_candidates_workspace_owner"),
        (update(workspace_candidates).values(snapshot_json={}), "23514", "ck_workspace_candidates_snapshot_identity"),
    )
    for statement, state, constraint in checks:
        expect_database_rejection(connection, lambda: connection.execute(statement), state, constraint)
    return len(checks)


def check_roles(fixture) -> int:
    count = 0
    for role in ("api", "worker"):
        engine = create_engine_from_settings(fixture.settings(role))
        try:
            with engine.begin() as connection:
                assert_runtime_ready(connection, role=role)
                for table in TABLES:
                    statement = f"INSERT INTO cloudhelm.{table.name} SELECT * FROM cloudhelm.{table.name} WHERE false"
                    if table.name in WORKSPACE_INSERTS[role]:
                        connection.exec_driver_sql(statement)
                    else:
                        expect_database_rejection(connection, lambda: connection.exec_driver_sql(statement), "42501")
                    count += 1
                    for privilege in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                        require(not connection.scalar(text(
                            "SELECT has_table_privilege(current_user, :table, :privilege)"
                        ), {"table": "cloudhelm." + table.name, "privilege": privilege}), "runtime_table_overgrant")
                        count += 1
                for column in workspaces.c:
                    actual = connection.scalar(text(
                        "SELECT has_column_privilege(current_user, 'cloudhelm.workspaces', :column, 'UPDATE')"
                    ), {"column": column.name})
                    require(actual == (role == "worker" and column.name in WORKSPACE_RECEIPT_COLUMNS),
                            "runtime_workspace_column_overgrant")
                    count += 1
        finally:
            engine.dispose()
    return count


def check_old_baseline(fixture, engine) -> None:
    with engine.begin() as connection:
        connection.execute(update(runtime_baseline).values(business_revision="0001_p1_1"))
    try:
        try:
            initialize_database(fixture.settings("migrator"))
        except DatabaseNotReady as failure:
            require(str(failure) == "database_baseline_incompatible", "wrong_old_baseline_rejection")
        else:
            raise WorkspaceStructureFailure("old_baseline_was_accepted")
        with engine.begin() as connection:
            require(connection.scalar(select(runtime_baseline.c.business_revision)) == "0001_p1_1",
                    "initialize_mutated_old_baseline")
            require(connection.scalar(text("SELECT version_num FROM cloudhelm.alembic_version")) == BUSINESS_REVISION,
                    "initialize_changed_migration_head")
    finally:
        with engine.begin() as connection:
            connection.execute(update(runtime_baseline).values(business_revision=BUSINESS_REVISION))


def main() -> int:
    started_at = datetime.now(UTC).isoformat()
    print(json.dumps({"status": "running", "method": "p1-workspace-structure-r1", "started_at": started_at}), flush=True)
    try:
        load_business_metadata()
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "database/migrations"))
        script = ScriptDirectory.from_config(config)
        require(script.get_heads() == [BUSINESS_REVISION], "migration_head_mismatch")
        require(script.get_revision(BUSINESS_REVISION).down_revision == "0001_p1_1", "migration_chain_not_linear")
        source, workspace, candidate = records()
        with database_fixture() as fixture:
            engine = create_engine_from_settings(fixture.settings("migrator"), purpose="maintenance")
            try:
                with engine.begin() as connection:
                    baseline = assert_schema_ready(connection)
                    rejected = check_structure(connection, source, workspace, candidate)
                role_checks = check_roles(fixture)
                check_old_baseline(fixture, engine)
                with engine.begin() as connection:
                    require(assert_schema_ready(connection) == baseline, "baseline_was_not_restored")
            finally:
                engine.dispose()
        print(json.dumps({"status": "passed", "method": "p1-workspace-structure-r1",
                          "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
                          "baseline": BUSINESS_REVISION, "contract_rejections": 5, "database_rejections": rejected,
                          "role_checks": role_checks, "old_baseline_marker_rejected": True,
                          "metadata_matches_migration": True, "cleanup": "complete",
                          "input_kind": "development_worktree", "complete_scope": False,
                          "scope": "synthetic structure, metadata, roles and baseline marker; no application acceptance"}))
        return 0
    except Exception as failure:
        reason = str(failure) if isinstance(failure, WorkspaceStructureFailure) else type(failure).__name__
        print(json.dumps({"status": "failed", "method": "p1-workspace-structure-r1", "reason": reason,
                          "finished_at": datetime.now(UTC).isoformat()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
