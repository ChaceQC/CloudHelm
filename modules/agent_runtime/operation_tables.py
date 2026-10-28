"""The association between a Task wait and one deferred operation call."""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, String, Table, UniqueConstraint

from database.metadata import metadata


agent_operation_waits = Table(
    "agent_operation_waits", metadata,
    Column("wait_condition_id", String(160), ForeignKey("cloudhelm.task_wait_conditions.wait_condition_id"), primary_key=True),
    Column("session_id", String(160), ForeignKey("cloudhelm.agent_sessions.session_id"), nullable=False),
    Column("from_run_id", String(160), ForeignKey("cloudhelm.agent_runs.run_id"), nullable=False),
    Column("tool_call_id", String(160), nullable=False),
    Column("operation_id", String(160), nullable=False),
    Column("control_revision", BigInteger, nullable=False),
    Column("input_validity_revision", BigInteger, nullable=False),
    Column("continuation_run_id", String(160), ForeignKey("cloudhelm.agent_runs.run_id")),
    UniqueConstraint("from_run_id", "tool_call_id", name="uq_agent_operation_wait_call"),
    CheckConstraint("control_revision BETWEEN 0 AND 9007199254740991", name="control_revision"),
    CheckConstraint("input_validity_revision BETWEEN 0 AND 9007199254740991", name="input_revision"),
)
