"""Task-owned state. These tables do not own AgentRun, verification or executor state."""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    String, Table, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata
from modules.collaboration.fact_tables import (  # Re-export one metadata import entry.
    task_evidence_links, task_fact_sources, task_operation_links,
    task_operation_observations, task_reference_records,
)


task_declarations = Table(
    "task_declarations", metadata,
    Column("declaration_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("declaration_json", JSONB, nullable=False),
    Column("declaration_digest", String(71), nullable=False),
    Column("created_by_command_id", String(160),
           ForeignKey("cloudhelm.commands.command_id", use_alter=True,
                      name="fk_task_declarations_created_by_command_id_commands",
                      deferrable=True, initially="DEFERRED"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("project_id", "declaration_id", name="uq_task_declaration_project"),
    CheckConstraint("octet_length(declaration_json::text) <= 32768", name="declaration_bounded"),
)

tasks = Table(
    "tasks", metadata,
    Column("task_id", String(160), primary_key=True),
    Column("project_id", String(160), ForeignKey("cloudhelm.projects.project_id"), nullable=False),
    Column("declaration_id", String(160), nullable=False),
    Column("state", String(16), nullable=False, server_default="draft"),
    Column("version", BigInteger, nullable=False, server_default="1"),
    Column("control_revision", BigInteger, nullable=False, server_default="0"),
    Column("input_validity_revision", BigInteger, nullable=False, server_default="0"),
    Column("input_status", String(16), nullable=False, server_default="needs_review"),
    Column("operation_set_revision", BigInteger, nullable=False, server_default="0"),
    Column("ordinary_progress_closed", Boolean, nullable=False, server_default="false"),
    Column("cancel_command_id", String(160), ForeignKey(
        "cloudhelm.commands.command_id", use_alter=True, name="fk_tasks_cancel_command_id_commands",
        deferrable=True, initially="DEFERRED",
    )),
    Column("cancel_requested_at", DateTime(timezone=True)),
    Column("cancel_requested_by", JSONB),
    Column("cancel_reason", String(160)),
    Column("cancel_control_revision", BigInteger),
    Column("completion_report_id", String(160)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["project_id", "declaration_id"],
                         ["cloudhelm.task_declarations.project_id", "cloudhelm.task_declarations.declaration_id"]),
    ForeignKeyConstraint(["task_id", "completion_report_id"],
                         ["cloudhelm.task_completion_reports.task_id", "cloudhelm.task_completion_reports.report_id"],
                         use_alter=True, name="fk_tasks_completion_report", deferrable=True, initially="DEFERRED"),
    CheckConstraint("state IN ('draft', 'active', 'paused', 'waiting_input', 'completed', 'failed', 'cancelled')", name="task_state"),
    CheckConstraint("version BETWEEN 1 AND 9007199254740991", name="task_version"),
    CheckConstraint("control_revision BETWEEN 0 AND 9007199254740991", name="task_control_revision"),
    CheckConstraint("input_validity_revision BETWEEN 0 AND 9007199254740991", name="task_input_revision"),
    CheckConstraint("operation_set_revision BETWEEN 0 AND 9007199254740991", name="operation_set_revision"),
    CheckConstraint("input_status IN ('valid', 'needs_review', 'superseded')", name="task_input_status"),
    CheckConstraint("(state = 'completed') = (completion_report_id IS NOT NULL)", name="task_report_required"),
    CheckConstraint("state <> 'completed' OR cancel_requested_at IS NULL", name="completion_excludes_cancel"),
    CheckConstraint(
        "(cancel_command_id IS NULL AND cancel_requested_at IS NULL AND cancel_requested_by IS NULL "
        "AND cancel_reason IS NULL AND cancel_control_revision IS NULL) OR "
        "(cancel_command_id IS NOT NULL AND cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL "
        "AND cancel_reason IS NOT NULL AND cancel_control_revision IS NOT NULL "
        "AND cancel_control_revision BETWEEN 0 AND control_revision)", name="cancellation_complete",
    ),
    CheckConstraint("state <> 'cancelled' OR cancel_requested_at IS NOT NULL", name="cancelled_has_intent"),
    CheckConstraint("(state NOT IN ('completed', 'cancelled') AND cancel_requested_at IS NULL) OR ordinary_progress_closed", name="terminal_progress_closed"),
)

work_items = Table(
    "work_items", metadata,
    Column("work_item_id", String(160), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("declaration_id", String(160), ForeignKey("cloudhelm.task_declarations.declaration_id"), nullable=False),
    Column("revision", BigInteger, nullable=False, server_default="1"),
    Column("state", String(16), nullable=False, server_default="pending"),
    Column("required", Boolean, nullable=False, server_default="true"),
    Column("goal", String(4096), nullable=False),
    Column("owner_session_id", String(160)),
    Column("blocked_reason", String(160)),
    Column("accepted_input_set_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    Column("acceptance_evidence_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    CheckConstraint("state IN ('pending', 'ready', 'running', 'blocked', 'submitted', 'accepted', 'failed', 'cancelled')", name="work_item_state"),
    CheckConstraint("revision BETWEEN 1 AND 9007199254740991", name="work_item_revision"),
    CheckConstraint("state <> 'accepted' OR (accepted_input_set_key IS NOT NULL AND acceptance_evidence_key IS NOT NULL)", name="work_item_acceptance_evidence"),
)

task_inputs = Table(
    "task_inputs", metadata,
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), primary_key=True),
    Column("input_validity_revision", BigInteger, primary_key=True),
    Column("input_set_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key"), nullable=False),
    Column("source_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key"), nullable=False),
    Column("candidate_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    Column("human_conclusion_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    CheckConstraint("input_validity_revision BETWEEN 0 AND 9007199254740991", name="input_revision"),
)

task_wait_conditions = Table(
    "task_wait_conditions", metadata,
    Column("wait_condition_id", String(160), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("required_for_completion", Boolean, nullable=False),
    Column("state", String(16), nullable=False, server_default="waiting"),
    Column("input_set_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    Column("conclusion_evidence_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    Column("closed_control_revision", BigInteger),
    CheckConstraint("state IN ('waiting', 'satisfied', 'closed')", name="wait_state"),
    CheckConstraint("state <> 'satisfied' OR (input_set_key IS NOT NULL AND conclusion_evidence_key IS NOT NULL)", name="wait_conclusion_required"),
    CheckConstraint("closed_control_revision BETWEEN 0 AND 9007199254740991", name="wait_control_revision"),
)

task_run_links = Table(
    "task_run_links", metadata,
    Column("run_id", String(160), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False),
    Column("run_revision", BigInteger, nullable=False),
    Column("history_key", String(71), ForeignKey("cloudhelm.task_reference_records.reference_key")),
    Column("fenced_control_revision", BigInteger),
    CheckConstraint("run_revision BETWEEN 0 AND 9007199254740991", name="run_link_revision"),
    CheckConstraint("fenced_control_revision BETWEEN 0 AND 9007199254740991", name="run_fence_revision"),
)

task_completion_reports = Table(
    "task_completion_reports", metadata,
    Column("report_id", String(160), primary_key=True),
    Column("task_id", String(160), ForeignKey("cloudhelm.tasks.task_id"), nullable=False, unique=True),
    Column("command_id", String(160),
           ForeignKey("cloudhelm.commands.command_id", deferrable=True, initially="DEFERRED"), nullable=False, unique=True),
    Column("report_json", JSONB, nullable=False),
    Column("report_digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("task_id", "report_id", name="uq_task_completion_report_owner"),
    CheckConstraint("octet_length(report_json::text) <= 262144", name="report_bounded"),
)
