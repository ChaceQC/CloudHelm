"""Executor-owned durable intent/results, including an explicit installation lineage."""

import fcntl
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from modules.delivery.release_recipe import delivery_digest


class RemoteError(RuntimeError):
    """Only stable public categories may escape the executor."""


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise RemoteError("remote_private_directory_required")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = path.stat()
    if value.st_uid != os.getuid() or value.st_mode & 0o077:
        raise RemoteError("remote_private_directory_required")
    return path


class Ledger:
    def __init__(self, directory, installation_id, *, initialize=False):
        self.directory = private_directory(directory)
        path = self.directory / "ledger.sqlite3"
        if not path.exists() and not initialize:
            raise RemoteError("remote_ledger_missing_reconcile_required")
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if initialize else 0), 0o600)
        value = os.fstat(descriptor)
        os.close(descriptor)
        if not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid() or value.st_mode & 0o077:
            raise RemoteError("remote_ledger_permissions_invalid")
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        if initialize:
            self.db.executescript("""
                CREATE TABLE lineage (installation TEXT PRIMARY KEY);
                CREATE TABLE operations (id TEXT PRIMARY KEY, binding TEXT NOT NULL, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active');
                CREATE UNIQUE INDEX binding_owner ON operations(binding) WHERE status != 'succeeded';
                CREATE TABLE grants (id TEXT PRIMARY KEY, operation TEXT NOT NULL, step TEXT NOT NULL,
                    acceptance TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE steps (operation TEXT NOT NULL, step TEXT NOT NULL, digest TEXT NOT NULL,
                    grant_id TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(operation, step));
                CREATE TABLE environments (binding TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            self.db.execute("INSERT INTO lineage VALUES (?)", (installation_id,))
        if (self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or self.db.execute("SELECT installation FROM lineage").fetchall()[0][0] != installation_id):
            raise RemoteError("remote_ledger_lineage_invalid")
        # A process restart can never revive an accepted, unstarted grant.
        self.db.execute("UPDATE grants SET closed=1 WHERE id NOT IN (SELECT grant_id FROM steps)")

    @contextmanager
    def locked(self, binding_id):
        name = delivery_digest({"binding": binding_id})[7:]
        descriptor = os.open(self.directory / (name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        except BlockingIOError:
            raise RemoteError("remote_binding_busy") from None
        finally:
            os.close(descriptor)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def receive(self, deployment):
        payload = deployment.model_dump_json()
        with self.transaction():
            previous = self.db.execute("SELECT * FROM operations WHERE id=?", (deployment.operation_id,)).fetchone()
            if previous:
                if previous["digest"] != deployment.plan_digest or previous["payload"] != payload:
                    raise RemoteError("remote_operation_digest_conflict")
                return
            try:
                self.db.execute("INSERT INTO operations(id,binding,digest,payload) VALUES (?,?,?,?)",
                    (deployment.operation_id, deployment.plan.binding.binding_id, deployment.plan_digest, payload))
            except sqlite3.IntegrityError:
                raise RemoteError("remote_binding_needs_reconciliation") from None

    def step(self, operation, step):
        return self.db.execute("SELECT * FROM steps WHERE operation=? AND step=?", (operation, step)).fetchone()

    def accept(self, operation, step, acceptance):
        grant = acceptance.grant
        previous = self.db.execute("SELECT * FROM grants WHERE id=?", (grant.grant_id,)).fetchone()
        if previous:
            if previous["closed"] or previous["acceptance"] != acceptance.model_dump_json():
                raise RemoteError("remote_grant_closed_or_rebound")
            return
        if self.step(operation, step):
            raise RemoteError("remote_step_already_started")
        with self.transaction():
            self.db.execute("UPDATE grants SET closed=1 WHERE operation=? AND step=?", (operation, step))
            self.db.execute("INSERT INTO grants(id,operation,step,acceptance) VALUES (?,?,?,?)",
                (grant.grant_id, operation, step, acceptance.model_dump_json()))

    def intent(self, operation, step, digest, grant_id):
        with self.transaction():
            row = self.db.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
            if row is None or row["closed"] or row["operation"] != operation or row["step"] != step:
                raise RemoteError("remote_grant_not_accepted")
            self.db.execute("INSERT INTO steps(operation,step,digest,grant_id,status) VALUES (?,?,?,?,'unknown')",
                (operation, step, digest, grant_id))

    def close_unstarted(self, operation, step):
        if self.step(operation, step) is not None:
            raise RemoteError("remote_original_step_unresolved")
        self.db.execute("UPDATE grants SET closed=1 WHERE operation=? AND step=?", (operation, step))

    def finish(self, result):
        row = self.step(result.operation_id, result.step_id)
        if row is None or row["digest"] != result.input_digest or row["grant_id"] != result.grant_id:
            raise RemoteError("remote_result_binding_invalid")
        if row["status"] == "succeeded" and row["result"] != result.model_dump_json():
            raise RemoteError("remote_result_immutable")
        with self.transaction():
            self.db.execute("UPDATE steps SET status=?,result=? WHERE operation=? AND step=?",
                (result.status, result.model_dump_json(), result.operation_id, result.step_id))

    def results(self, operation):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT result FROM steps WHERE operation=? AND result IS NOT NULL ORDER BY rowid", (operation,))]

    def complete(self, deployment, state):
        if any(self.step(deployment.operation_id, step.step_id)["status"] != "succeeded" for step in deployment.plan.steps):
            raise RemoteError("remote_steps_incomplete")
        with self.transaction():
            self.db.execute("INSERT INTO environments VALUES (?,?) ON CONFLICT(binding) DO UPDATE SET value=excluded.value",
                (deployment.plan.binding.binding_id, state.model_dump_json()))
            self.db.execute("UPDATE operations SET status='succeeded' WHERE id=?", (deployment.operation_id,))

    def close(self):
        self.db.close()
