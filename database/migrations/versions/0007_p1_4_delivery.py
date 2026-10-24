"""Immutable archive releases/configuration/plans and independent deployment control."""

from alembic import op

revision = "0007_p1_4_delivery"
down_revision = "0006_p1_3_resource_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    # Fixed declarations live in this migration, independent of future ORM edits.
    for name, key in (("releases", "release_id"), ("environment_configs", "config_revision_id"),
                      ("deployment_plans", "plan_id"), ("deployment_approvals", "plan_id")):
        op.execute(f"""CREATE TABLE cloudhelm.{name} (
            {key} VARCHAR(160) PRIMARY KEY,
            project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
            digest VARCHAR(71) NOT NULL,
            value_json JSONB NOT NULL,
            command_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.commands(command_id) DEFERRABLE INITIALLY DEFERRED,
            authorization_decision_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.audit_records(decision_id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_{name}_digest CHECK (digest ~ '^sha256:[0-9a-f]{{64}}$'),
            CONSTRAINT ck_{name}_bounded_payload CHECK (jsonb_typeof(value_json) = 'object'
                AND octet_length(value_json::text) <= 131072)
        )""")
    op.execute("""CREATE TABLE cloudhelm.delivery_targets (
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
        target_id VARCHAR(160) NOT NULL,
        installation_id VARCHAR(160) NOT NULL,
        registration_json JSONB NOT NULL,
        digest VARCHAR(71) NOT NULL,
        PRIMARY KEY (project_id, target_id),
        CONSTRAINT ck_delivery_targets_bounded_registration CHECK (octet_length(registration_json::text) <= 16384)
    )""")
    op.execute("""CREATE TABLE cloudhelm.environment_bindings (
        binding_id VARCHAR(160) PRIMARY KEY,
        project_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.projects(project_id),
        environment_id VARCHAR(160) NOT NULL,
        value_json JSONB NOT NULL,
        digest VARCHAR(71) NOT NULL,
        environment_revision BIGINT NOT NULL DEFAULT 0,
        config_revision BIGINT NOT NULL DEFAULT 0,
        release_id VARCHAR(160) REFERENCES cloudhelm.releases(release_id),
        config_revision_id VARCHAR(160) REFERENCES cloudhelm.environment_configs(config_revision_id),
        active_operation_id VARCHAR(160),
        CONSTRAINT uq_environment_bindings_logical_environment UNIQUE(project_id, environment_id),
        CONSTRAINT ck_environment_bindings_revisions CHECK (environment_revision BETWEEN 0 AND 9007199254740991
            AND config_revision BETWEEN 0 AND 9007199254740991)
    )""")
    op.execute("""CREATE TABLE cloudhelm.delivery_target_observations (
        observation_id VARCHAR(160) PRIMARY KEY,
        binding_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.environment_bindings(binding_id),
        digest VARCHAR(71) NOT NULL,
        value_json JSONB NOT NULL,
        observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT ck_delivery_target_observations_bounded_observation CHECK (octet_length(value_json::text) <= 32768)
    )""")
    op.execute("""CREATE TABLE cloudhelm.environment_revisions (
        binding_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.environment_bindings(binding_id),
        environment_revision BIGINT NOT NULL,
        plan_id VARCHAR(160) NOT NULL REFERENCES cloudhelm.deployment_plans(plan_id),
        operation_id VARCHAR(160) NOT NULL UNIQUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (binding_id, environment_revision)
    )""")
    op.execute("ALTER TABLE cloudhelm.role_bindings DROP CONSTRAINT ck_role_bindings_binding_supported_role")
    op.execute("""ALTER TABLE cloudhelm.role_bindings ADD CONSTRAINT ck_role_bindings_binding_supported_role
                  CHECK (role IN ('developer', 'reviewer', 'deployment_approver'))""")
    op.execute("ALTER TABLE cloudhelm.workflow_bindings DROP CONSTRAINT ck_workflow_bindings_p1_business_kind")
    op.execute("""ALTER TABLE cloudhelm.workflow_bindings ADD CONSTRAINT ck_workflow_bindings_p1_business_kind
                  CHECK (business_kind IN ('task', 'project', 'workspace', 'build', 'deployment'))""")


def downgrade():
    raise RuntimeError("delivery_downgrade_requires_explicit_reconciliation")
