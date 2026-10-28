"""The explicit v0-to-v1 SQLite upgrade and immutable local closeout fence."""

import re


_TABLES = {
    "lineage": "CREATE TABLE lineage (installation TEXT PRIMARY KEY)",
    "operations": "CREATE TABLE operations (id TEXT PRIMARY KEY, binding TEXT NOT NULL, digest TEXT NOT NULL, "
        "payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')",
    "grants": "CREATE TABLE grants (id TEXT PRIMARY KEY, operation TEXT NOT NULL, step TEXT NOT NULL, "
        "acceptance TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0)",
    "steps": "CREATE TABLE steps (operation TEXT NOT NULL, step TEXT NOT NULL, digest TEXT NOT NULL, "
        "grant_id TEXT NOT NULL, status TEXT NOT NULL, result TEXT, PRIMARY KEY(operation, step))",
    "environments": "CREATE TABLE environments (binding TEXT PRIMARY KEY, value TEXT NOT NULL)",
}

_SCHEMA = (
    "CREATE TABLE closeouts (operation TEXT PRIMARY KEY, fence_digest TEXT NOT NULL, "
    "ledger_facts TEXT NOT NULL, physical_evidence TEXT, receipt TEXT)",
    "DROP INDEX binding_owner",
    "CREATE UNIQUE INDEX binding_owner ON operations(binding) "
    "WHERE status NOT IN ('succeeded', 'closed_retained')",
    "CREATE TRIGGER closeout_grant_insert BEFORE INSERT ON grants "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=NEW.operation) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_grant_update BEFORE UPDATE ON grants "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.operation) AND "
    "(NEW.id != OLD.id OR NEW.operation != OLD.operation OR NEW.step != OLD.step OR "
    "NEW.acceptance != OLD.acceptance OR NEW.closed != 1) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_grant_delete BEFORE DELETE ON grants "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.operation) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_step_insert BEFORE INSERT ON steps "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=NEW.operation) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_step_update BEFORE UPDATE ON steps "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.operation) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_step_delete BEFORE DELETE ON steps "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.operation) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_operation_update BEFORE UPDATE ON operations "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.id) AND "
    "(NEW.id != OLD.id OR NEW.binding != OLD.binding OR NEW.digest != OLD.digest OR "
    "NEW.payload != OLD.payload OR NEW.status NOT IN ('active', 'closed_retained') OR "
    "(OLD.status='closed_retained' AND NEW.status != OLD.status) OR "
    "(NEW.status='closed_retained' AND (SELECT receipt FROM closeouts WHERE operation=OLD.id) IS NULL)) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_operation_delete BEFORE DELETE ON operations "
    "WHEN EXISTS (SELECT 1 FROM closeouts WHERE operation=OLD.id) "
    "BEGIN SELECT RAISE(ABORT, 'remote_operation_sealed'); END",
    "CREATE TRIGGER closeout_record_delete BEFORE DELETE ON closeouts "
    "BEGIN SELECT RAISE(ABORT, 'remote_closeout_immutable'); END",
    "CREATE TRIGGER closeout_record_update BEFORE UPDATE ON closeouts "
    "WHEN OLD.receipt IS NOT NULL OR NEW.operation != OLD.operation OR "
    "NEW.fence_digest != OLD.fence_digest OR NEW.ledger_facts != OLD.ledger_facts OR "
    "NEW.receipt IS NULL OR NEW.physical_evidence IS NULL "
    "BEGIN SELECT RAISE(ABORT, 'remote_closeout_immutable'); END",
)


def upgrade(db):
    """Called inside the maintenance transaction; never upgrades an ordinary open."""
    if db.execute("PRAGMA user_version").fetchone()[0] == 1:
        return
    if db.execute("PRAGMA user_version").fetchone()[0] != 0:
        raise ValueError("remote_ledger_schema_unsupported")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != set(_TABLES):
        raise ValueError("remote_ledger_schema_invalid")
    for name, expected in _TABLES.items():
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row is None or re.sub(r"\s+", " ", row[0]).strip().lower() != expected.lower():
            raise ValueError("remote_ledger_schema_invalid")
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='binding_owner'").fetchone()
    sql = "" if row is None else re.sub(r"\s+", " ", row[0]).strip().lower()
    if sql != "create unique index binding_owner on operations(binding) where status != 'succeeded'":
        raise ValueError("remote_ledger_schema_invalid")
    for statement in _SCHEMA:
        db.execute(statement)
    db.execute("PRAGMA user_version=1")


def validate(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        raise ValueError("remote_ledger_schema_unsupported")
    if version == 1:
        for statement in _SCHEMA:
            words = statement.split()
            if words[:2] == ["CREATE", "TRIGGER"]:
                kind, name = "trigger", words[2]
            elif words[:3] == ["CREATE", "UNIQUE", "INDEX"]:
                kind, name = "index", words[3]
            elif words[:2] == ["CREATE", "TABLE"]:
                kind, name = "table", words[2]
            else:
                continue
            row = db.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone()
            if row is None or re.sub(r"\s+", " ", row[0]).strip().lower() != statement.lower():
                raise ValueError("remote_ledger_schema_invalid")
    return version
