"""Append supplier billing results and operation wait associations."""

from alembic import op

revision = "0013_p2_usage_waits"
down_revision = "0012_p2_agent_runtime"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.agent_model_request_results (
        request_record_id VARCHAR(160) NOT NULL,
        revision INTEGER NOT NULL,
        result_json JSONB NOT NULL,
        price_revision VARCHAR(80) NOT NULL,
        calculation_json JSONB,
        calculated_cost NUMERIC(28,12),
        billed_amount NUMERIC(28,12),
        billed_currency VARCHAR(3),
        reconciliation_evidence_ref VARCHAR(160),
        reservation_bound_exceeded BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_model_request_results PRIMARY KEY (request_record_id, revision),
        CONSTRAINT fk_agent_model_request_results_request_record_id_agent_model_requests
            FOREIGN KEY (request_record_id) REFERENCES cloudhelm.agent_model_requests(request_record_id),
        CONSTRAINT ck_agent_model_request_results_revision CHECK (revision > 0),
        CONSTRAINT ck_agent_model_request_results_calculated_cost CHECK (calculated_cost IS NULL OR calculated_cost >= 0),
        CONSTRAINT ck_agent_model_request_results_billed_amount CHECK (billed_amount IS NULL OR billed_amount >= 0),
        CONSTRAINT ck_agent_model_request_results_result_bounded CHECK (octet_length(result_json::text) <= 8192),
        CONSTRAINT ck_agent_model_request_results_calculation_bounded CHECK (octet_length(calculation_json::text) <= 8192)
    )""")
    op.execute("""CREATE TABLE cloudhelm.agent_operation_waits (
        wait_condition_id VARCHAR(160) NOT NULL,
        session_id VARCHAR(160) NOT NULL,
        from_run_id VARCHAR(160) NOT NULL,
        tool_call_id VARCHAR(160) NOT NULL,
        operation_id VARCHAR(160) NOT NULL,
        control_revision BIGINT NOT NULL,
        input_validity_revision BIGINT NOT NULL,
        continuation_run_id VARCHAR(160),
        CONSTRAINT pk_agent_operation_waits PRIMARY KEY (wait_condition_id),
        CONSTRAINT fk_agent_operation_waits_wait_condition_id_task_wait_conditions
            FOREIGN KEY (wait_condition_id) REFERENCES cloudhelm.task_wait_conditions(wait_condition_id),
        CONSTRAINT fk_agent_operation_waits_session_id_agent_sessions
            FOREIGN KEY (session_id) REFERENCES cloudhelm.agent_sessions(session_id),
        CONSTRAINT fk_agent_operation_waits_from_run_id_agent_runs
            FOREIGN KEY (from_run_id) REFERENCES cloudhelm.agent_runs(run_id),
        CONSTRAINT fk_agent_operation_waits_continuation_run_id_agent_runs
            FOREIGN KEY (continuation_run_id) REFERENCES cloudhelm.agent_runs(run_id),
        CONSTRAINT uq_agent_operation_wait_call UNIQUE (from_run_id, tool_call_id),
        CONSTRAINT ck_agent_operation_waits_control_revision
            CHECK (control_revision BETWEEN 0 AND 9007199254740991),
        CONSTRAINT ck_agent_operation_waits_input_revision
            CHECK (input_validity_revision BETWEEN 0 AND 9007199254740991)
    )""")


def downgrade():
    raise RuntimeError("agent_usage_wait_downgrade_requires_reconciliation")
