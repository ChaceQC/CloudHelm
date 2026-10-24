"""Fixed reference Alembic steps with one database transaction and original identity."""

import hashlib
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool
from psycopg import sql

HEAD = "0002_add_updated_at_index"
REVISIONS = ("0001_create_notes", HEAD)
POSTCHECKS = ("schema_integrity", "data_integrity", "application_probe")
SCRIPT_DIGESTS = {
    "migrations/versions/0001_create_notes.py": "sha256:7698b5b5f6554bd89026d808bab8a0acfa07ba02b25a9e28cf65483bf6ef0c6f",
    "migrations/versions/0002_add_updated_at_index.py": "sha256:5b2961617293966d5b39427ab3a57ddc6bc96ed0ee31d94d997ba07779399f5f",
}


def _rows(connection):
    digest, count = hashlib.sha256(), 0
    for row in connection.execute(text("SELECT id,title,body,created_at,updated_at FROM public.notes ORDER BY id")).yield_per(256):
        count += 1
        if count > 100000:
            raise ValueError("migration_data_scope_unsupported")
        digest.update(json.dumps(list(row), default=str, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return count, digest.hexdigest()


def postchecks(connection, baseline, *, verify_unchanged_data=True):
    schema = inspect(connection)
    columns = schema.get_columns("notes", schema="public")
    expected = {"id", "title", "body", "created_at", "updated_at"}
    if {item["name"] for item in columns} != expected or any(item["nullable"] for item in columns):
        raise ValueError("migration_schema_columns_invalid")
    types = {item["name"]: item["type"] for item in columns}
    if (str(types["id"]) != "INTEGER" or getattr(types["title"], "length", None) != 120
            or getattr(types["body"], "length", None) != 4000
            or not all(getattr(types[key], "timezone", False) for key in ("created_at", "updated_at"))
            or schema.get_pk_constraint("notes", schema="public")["constrained_columns"] != ["id"]
            or not any(item["name"] == "ix_notes_updated_at" and item["column_names"] == ["updated_at"]
                       and not item["unique"] for item in schema.get_indexes("notes", schema="public"))):
        raise ValueError("migration_schema_constraints_invalid")
    if verify_unchanged_data and _rows(connection) != baseline:
        raise ValueError("migration_data_changed")
    # Fixed read-only application query, independent of a running new backend.
    connection.execute(text("SET LOCAL ROLE reference_app"))
    if tuple(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars()) != (HEAD,):
        raise ValueError("migration_application_revision_unreadable")
    connection.execute(text("SELECT id,title,body,created_at,updated_at FROM public.notes ORDER BY updated_at DESC,id DESC LIMIT 1")).all()
    connection.execute(text("RESET ROLE"))
    return POSTCHECKS


def _load_revisions(directory, files):
    if files != SCRIPT_DIGESTS:
        raise ValueError("migration_unreviewed_scripts")
    modules = []
    for revision in REVISIONS:
        path = directory / (revision + ".py")
        expected = files.get("migrations/versions/" + path.name)
        if expected != "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("migration_script_digest_invalid")
        spec = importlib.util.spec_from_file_location("remote_migration_" + revision, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if (module.revision != revision or module.branch_labels or module.depends_on
                or module.down_revision != (None if not modules else modules[-1].revision)):
            raise ValueError("migration_chain_unsupported")
        modules.append(module)
    return modules


def _lock(connection, database_id):
    key = int.from_bytes(hashlib.sha256(("cloudhelm:migration-lock:v1\0" + database_id).encode("utf-8")).digest()[:8], "big", signed=True)
    if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
        raise ValueError("migration_lock_busy")


def _existing(connection, request):
    present = connection.scalar(text("SELECT to_regclass('cloudhelm_delivery.operations')"))
    if present is None:
        return None
    installation = connection.scalar(text("SELECT installation_id FROM cloudhelm_delivery.installation"))
    if installation != request["installation_id"]:
        raise ValueError("migration_database_lineage_invalid")
    row = connection.execute(text("SELECT operation_id,input_digest,target_revision,baseline_count,baseline_digest "
        "FROM cloudhelm_delivery.operations WHERE operation_id=:operation_id"), request).mappings().one_or_none()
    if row is not None and (row["input_digest"] != request["input_digest"] or row["target_revision"] != HEAD):
        raise ValueError("migration_original_identity_conflict")
    return row


def query(connection, request):
    """A missing row never means not_started; only the original success can settle."""
    row = _existing(connection, request)
    if row is None:
        return {"status": "unknown"}
    heads = tuple(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars())
    if heads != (HEAD,):
        return {"status": "unknown"}
    # The immutable owner-only row proves the data check committed with the DDL.
    # Legitimate application writes after commit do not retroactively fail that check.
    checks = postchecks(connection, (row["baseline_count"], row["baseline_digest"]), verify_unchanged_data=False)
    return {"status": "succeeded", "operation_id": row["operation_id"], "input_digest": row["input_digest"],
            "database_revision": HEAD, "postchecks": checks}


def run(connection, request, directory):
    if version("alembic") != "1.20.0":
        raise ValueError("migration_alembic_version_unsupported")
    if connection.scalar(text("SHOW server_version_num")) != "160013":
        raise ValueError("migration_postgres_version_unsupported")
    connection.execute(text("SET LOCAL log_statement='none'"))
    connection.execute(text("SET LOCAL log_min_error_statement='panic'"))
    connection.execute(text("SET LOCAL log_parameter_max_length=0"))
    connection.execute(text("SET LOCAL log_parameter_max_length_on_error=0"))
    connection.execute(text("SET LOCAL lock_timeout='5s'"))
    connection.execute(text("SET LOCAL statement_timeout='300s'"))
    _lock(connection, request["database_instance_id"])
    existing = _existing(connection, request)
    if existing is not None:
        return query(connection, request)
    if request.get("query_only"):
        return {"status": "unknown"}
    if connection.scalar(text("SELECT to_regclass('cloudhelm_delivery.operations')")) is not None:
        if request.get("expected_revision") != HEAD:
            raise ValueError("migration_start_revision_changed")
        heads = tuple(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars())
        if heads != (HEAD,):
            raise ValueError("migration_start_revision_changed")
        baseline = _rows(connection)
        postchecks(connection, baseline)
        _record_success(connection, request, baseline)
        return query(connection, request)
    # Existing data requires independent restore/compatibility evidence, not an implicit upgrade.
    if inspect(connection).get_table_names(schema="public"):
        raise ValueError("migration_existing_data_restore_evidence_required")
    revisions = _load_revisions(directory, request["migration_files"])
    connection.execute(text("CREATE SCHEMA cloudhelm_delivery"))
    connection.execute(text("REVOKE ALL ON SCHEMA cloudhelm_delivery FROM PUBLIC"))
    connection.execute(text("CREATE TABLE cloudhelm_delivery.installation(installation_id TEXT PRIMARY KEY)"))
    connection.execute(text("INSERT INTO cloudhelm_delivery.installation VALUES (:installation_id)"), request)
    connection.execute(text("CREATE TABLE cloudhelm_delivery.operations(operation_id TEXT PRIMARY KEY, "
        "input_digest TEXT NOT NULL,target_revision TEXT NOT NULL,baseline_count BIGINT NOT NULL,baseline_digest TEXT NOT NULL)"))
    context = MigrationContext.configure(connection, opts={"transactional_ddl": True})
    connection.execute(text("CREATE TABLE public.alembic_version(version_num VARCHAR(32) PRIMARY KEY)"))
    with Operations.context(context):
        for revision in revisions:
            revision.upgrade()
    connection.execute(text("INSERT INTO public.alembic_version(version_num) VALUES (:head)"), {"head": HEAD})
    statement = sql.SQL("CREATE ROLE reference_app LOGIN PASSWORD {}").format(sql.Literal(request["application_password"]))
    connection.connection.driver_connection.execute(statement)
    connection.execute(text("GRANT USAGE ON SCHEMA public TO reference_app"))
    connection.execute(text("GRANT SELECT,INSERT,UPDATE,DELETE ON public.notes TO reference_app"))
    connection.execute(text("GRANT SELECT ON public.alembic_version TO reference_app"))
    connection.execute(text("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO reference_app"))
    baseline = (0, hashlib.sha256().hexdigest())
    postchecks(connection, baseline)
    _record_success(connection, request, baseline)
    return query(connection, request)


def _record_success(connection, request, baseline):
    connection.execute(text("INSERT INTO cloudhelm_delivery.operations VALUES "
        "(:operation_id,:input_digest,:head,:count,:digest)"), request | {"head": HEAD, "count": baseline[0], "digest": baseline[1]})


def execute(database_url, request, *, directory=Path("/app/migrations/versions")):
    """No driver error, SQL parameter or URL is returned to the control channel."""
    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True, echo=False)
    try:
        with engine.begin() as connection:
            result = run(connection, request, directory)
        return result
    except Exception:
        return {"status": "unknown"}
    finally:
        engine.dispose()
