"""Append-only observations tied to the original model request."""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from database.metadata import metadata
from .tables import agent_model_requests


agent_model_request_results = Table(
    "agent_model_request_results", metadata,
    Column("request_record_id", String(160), ForeignKey(
        agent_model_requests.c.request_record_id), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("result_json", JSONB, nullable=False),
    Column("price_revision", String(80), nullable=False),
    Column("calculation_json", JSONB(none_as_null=True)),
    Column("calculated_cost", Numeric(28, 12)),
    Column("billed_amount", Numeric(28, 12)),
    Column("billed_currency", String(3)),
    Column("reconciliation_evidence_ref", String(160)),
    Column("reservation_bound_exceeded", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("revision > 0", name="revision"),
    CheckConstraint("calculated_cost IS NULL OR calculated_cost >= 0", name="calculated_cost"),
    CheckConstraint("billed_amount IS NULL OR billed_amount >= 0", name="billed_amount"),
    CheckConstraint("octet_length(result_json::text) <= 8192", name="result_bounded"),
    CheckConstraint("octet_length(calculation_json::text) <= 8192", name="calculation_bounded"),
)
