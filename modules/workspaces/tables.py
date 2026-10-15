"""Workspace bindings and physical snapshots; no environment readiness or acceptance."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    String, Table, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata


workspaces = Table(
    "workspaces", metadata,
    Column("workspace_id", String(160), primary_key=True),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("work_item_id", String(160), nullable=False),
    Column("owner_user_id", String(160), ForeignKey("cloudhelm.users.user_id", name="fk_workspaces_owner_user"),
           nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("source_revision", BigInteger, nullable=False),
    Column("base_commit", String(64), nullable=False),
    Column("workspace_revision", BigInteger, nullable=False),
    Column("write_generation", BigInteger, nullable=False),
    Column("binding_json", JSONB, nullable=False),
    Column("binding_digest", String(71), nullable=False),
    Column("files_json", JSONB(none_as_null=True)),
    Column("files_digest", String(71)),
    Column("materialization_operation_id", String(160), unique=True),
    Column("storage_id", String(160), unique=True),
    Column("created_by_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_workspaces_command", deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160),
           ForeignKey("cloudhelm.audit_records.decision_id", name="fk_workspaces_authorization"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["project_id", "source_id", "source_revision"],
                         ["cloudhelm.project_git_sources.project_id", "cloudhelm.project_git_sources.source_id",
                          "cloudhelm.project_git_sources.source_revision"], name="fk_workspaces_source_binding"),
    ForeignKeyConstraint(["project_id", "task_id"],
                         ["cloudhelm.tasks.project_id", "cloudhelm.tasks.task_id"], name="fk_workspaces_task_owner"),
    ForeignKeyConstraint(["task_id", "work_item_id"],
                         ["cloudhelm.work_items.task_id", "cloudhelm.work_items.work_item_id"],
                         name="fk_workspaces_work_item_owner"),
    UniqueConstraint("workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id",
                     "source_id", "source_revision", name="uq_workspace_owner_binding"),
    CheckConstraint("source_revision BETWEEN 0 AND 9007199254740991", name="source_revision"),
    CheckConstraint("workspace_revision BETWEEN 0 AND 9007199254740991", name="workspace_revision"),
    CheckConstraint("write_generation BETWEEN 0 AND 9007199254740991", name="write_generation"),
    CheckConstraint("base_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="base_commit"),
    CheckConstraint("binding_digest ~ '^sha256:[0-9a-f]{64}$'", name="binding_digest"),
    CheckConstraint(
        "jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 16384",
        name="binding_bounded",
    ),
    CheckConstraint(
        "(binding_json ->> 'workspace_id') IS NOT DISTINCT FROM workspace_id AND "
        "(binding_json ->> 'project_id') IS NOT DISTINCT FROM project_id AND "
        "(binding_json ->> 'task_id') IS NOT DISTINCT FROM task_id AND "
        "(binding_json ->> 'work_item_id') IS NOT DISTINCT FROM work_item_id AND "
        "(binding_json ->> 'owner_user_id') IS NOT DISTINCT FROM owner_user_id AND "
        "(binding_json ->> 'source_id') IS NOT DISTINCT FROM source_id AND "
        "(binding_json ->> 'source_revision') IS NOT DISTINCT FROM source_revision::text AND "
        "(binding_json ->> 'base_commit') IS NOT DISTINCT FROM base_commit AND "
        "(binding_json ->> 'workspace_revision') IS NOT DISTINCT FROM workspace_revision::text AND "
        "(binding_json ->> 'write_generation') IS NOT DISTINCT FROM write_generation::text",
        name="binding_identity",
    ),
    CheckConstraint(
        "(files_json IS NULL AND files_digest IS NULL AND materialization_operation_id IS NULL AND storage_id IS NULL) OR "
        "(files_json IS NOT NULL AND files_digest IS NOT NULL AND materialization_operation_id IS NOT NULL "
        "AND storage_id IS NOT NULL AND files_digest ~ '^sha256:[0-9a-f]{64}$' "
        "AND jsonb_typeof(files_json) = 'object' AND octet_length(files_json::text) <= 32768 "
        "AND (files_json -> 'binding') IS NOT DISTINCT FROM binding_json "
        "AND (files_json ->> 'operation_id') IS NOT DISTINCT FROM materialization_operation_id "
        "AND (files_json ->> 'storage_id') IS NOT DISTINCT FROM storage_id)",
        name="files_receipt_complete",
    ),
)

workspace_candidates = Table(
    "workspace_candidates", metadata,
    Column("candidate_id", String(160), primary_key=True),
    Column("workspace_id", String(160), nullable=False),
    Column("project_id", String(160), nullable=False),
    Column("task_id", String(160), nullable=False),
    Column("work_item_id", String(160), nullable=False),
    Column("owner_user_id", String(160), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("source_revision", BigInteger, nullable=False),
    Column("workspace_revision", BigInteger, nullable=False),
    Column("write_generation", BigInteger, nullable=False),
    Column("candidate_commit", String(64), nullable=False),
    Column("parent_commit", String(64), nullable=False),
    Column("freeze_operation_id", String(160), nullable=False, unique=True),
    Column("storage_id", String(160), nullable=False, unique=True),
    Column("snapshot_json", JSONB, nullable=False),
    Column("snapshot_digest", String(71), nullable=False),
    Column("created_by_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", name="fk_candidates_command", deferrable=True, initially="DEFERRED",
    ), nullable=False, unique=True),
    Column("authorization_decision_id", String(160),
           ForeignKey("cloudhelm.audit_records.decision_id", name="fk_candidates_authorization"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workspace_id", "project_id", "task_id", "work_item_id", "owner_user_id", "source_id", "source_revision"],
        ["cloudhelm.workspaces.workspace_id", "cloudhelm.workspaces.project_id", "cloudhelm.workspaces.task_id",
         "cloudhelm.workspaces.work_item_id", "cloudhelm.workspaces.owner_user_id", "cloudhelm.workspaces.source_id",
         "cloudhelm.workspaces.source_revision"], name="fk_candidates_workspace_owner",
    ),
    CheckConstraint("source_revision BETWEEN 0 AND 9007199254740991", name="source_revision"),
    CheckConstraint("workspace_revision BETWEEN 0 AND 9007199254740991", name="workspace_revision"),
    CheckConstraint("write_generation BETWEEN 0 AND 9007199254740991", name="write_generation"),
    CheckConstraint("candidate_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="candidate_commit"),
    CheckConstraint("parent_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'", name="parent_commit"),
    CheckConstraint("snapshot_digest ~ '^sha256:[0-9a-f]{64}$'", name="snapshot_digest"),
    CheckConstraint(
        "jsonb_typeof(snapshot_json) = 'object' AND octet_length(snapshot_json::text) <= 32768",
        name="snapshot_bounded",
    ),
    CheckConstraint(
        "(snapshot_json ->> 'candidate_id') IS NOT DISTINCT FROM candidate_id AND "
        "(snapshot_json ->> 'candidate_commit') IS NOT DISTINCT FROM candidate_commit AND "
        "(snapshot_json ->> 'parent_commit') IS NOT DISTINCT FROM parent_commit AND "
        "(snapshot_json ->> 'freeze_operation_id') IS NOT DISTINCT FROM freeze_operation_id AND "
        "(snapshot_json ->> 'storage_id') IS NOT DISTINCT FROM storage_id AND "
        "(snapshot_json #>> '{binding,workspace_id}') IS NOT DISTINCT FROM workspace_id AND "
        "(snapshot_json #>> '{binding,project_id}') IS NOT DISTINCT FROM project_id AND "
        "(snapshot_json #>> '{binding,task_id}') IS NOT DISTINCT FROM task_id AND "
        "(snapshot_json #>> '{binding,work_item_id}') IS NOT DISTINCT FROM work_item_id AND "
        "(snapshot_json #>> '{binding,owner_user_id}') IS NOT DISTINCT FROM owner_user_id AND "
        "(snapshot_json #>> '{binding,source_id}') IS NOT DISTINCT FROM source_id AND "
        "(snapshot_json #>> '{binding,source_revision}') IS NOT DISTINCT FROM source_revision::text AND "
        "(snapshot_json #>> '{binding,workspace_revision}') IS NOT DISTINCT FROM workspace_revision::text AND "
        "(snapshot_json #>> '{binding,write_generation}') IS NOT DISTINCT FROM write_generation::text",
        name="snapshot_identity",
    ),
)
