"""One immutable source for the isolated, original-operation maintenance gate."""

from alembic import op

revision = "0011_p1_archive_maintenance"
down_revision = "0010_p1_archive_closeout"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE cloudhelm.archive_maintenance_sources (
        operation_id VARCHAR(160) PRIMARY KEY,
        singleton_key SMALLINT NOT NULL UNIQUE DEFAULT 1,
        installation_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.runtime_baseline(installation_id),
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
        plan_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.deployment_plans(plan_id),
        binding_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.environment_bindings(binding_id),
        snapshot_digest VARCHAR(71) NOT NULL,
        isolation_evidence_digest VARCHAR(71) NOT NULL,
        input_digest VARCHAR(71) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        CONSTRAINT ck_archive_maintenance_sources_single_scope CHECK (singleton_key = 1),
        CONSTRAINT ck_archive_maintenance_sources_snapshot_digest CHECK (snapshot_digest ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_archive_maintenance_sources_isolation_digest CHECK (isolation_evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_archive_maintenance_sources_input_digest CHECK (input_digest ~ '^sha256:[0-9a-f]{64}$')
    )""")
    op.execute("""CREATE FUNCTION cloudhelm.reject_archive_maintenance_source_change()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'archive_maintenance_source_immutable';
        END; $$""")
    op.execute("""CREATE TRIGGER archive_maintenance_sources_immutable
        BEFORE UPDATE OR DELETE ON cloudhelm.archive_maintenance_sources
        FOR EACH ROW EXECUTE FUNCTION cloudhelm.reject_archive_maintenance_source_change()""")
    op.execute("REVOKE ALL ON cloudhelm.archive_maintenance_sources FROM PUBLIC, cloudhelm_api, cloudhelm_worker")
    op.execute("GRANT SELECT ON cloudhelm.archive_maintenance_sources TO cloudhelm_api, cloudhelm_worker")


def downgrade():
    raise RuntimeError("archive_maintenance_downgrade_requires_reconciliation")
