"""One private, synchronous SQLite ledger and start lock per observed Linux host."""

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from packages.contracts.p1.resource_protocol import PoolRegistration, RunnerRegistration

ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/resources")


def observed_host_id():
    # Registration also requires infrastructure review: this identifies an OS
    # host, and does not prove that two VMs have independent physical budgets.
    value = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
    if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("resource_host_identity_unavailable")
    return "linux-host-" + hashlib.sha256(value.encode("ascii")).hexdigest()


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.geteuid() == 0 and path != ROOT and ROOT.exists():
        # The privileged local controller uses the same service-owned ledger,
        # rather than creating a second root-owned copy of the host's budget.
        os.chown(path, ROOT.stat().st_uid, ROOT.stat().st_gid)
    for item in (path, *path.parents):
        state = item.lstat()
        if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
            raise ValueError("resource_ledger_directory_invalid")
        if state.st_mode & 0o022:
            raise ValueError("resource_ledger_parent_writable")
    state = path.stat()
    if (os.geteuid() != 0 and state.st_uid != os.getuid()) or state.st_mode & 0o077:
        raise ValueError("resource_ledger_directory_not_private")


def _file(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if os.geteuid() == 0:
        parent = path.parent.stat()
        os.fchown(fd, parent.st_uid, parent.st_gid)
    state = os.fstat(fd)
    if (not stat.S_ISREG(state.st_mode) or (os.geteuid() != 0 and state.st_uid != os.getuid())
            or state.st_mode & 0o077 or state.st_nlink != 1):
        os.close(fd)
        raise ValueError("resource_ledger_file_not_private")
    return fd


class ResourceLedger:
    def __init__(self, pool: PoolRegistration, runner: RunnerRegistration):
        if (pool.pool.physical_host_id != observed_host_id()
                or runner.physical_host_id != pool.pool.physical_host_id
                or runner.host_resource_pool_id != pool.pool.host_resource_pool_id
                or runner.executor_instance_id not in pool.pool.executor_instance_ids
                or runner.hub_incarnation != pool.hub_incarnation
                or runner.resource_generation != pool.resource_generation):
            raise ValueError("resource_local_host_registration_mismatch")
        self.pool, self.registration = pool, runner
        self.directory = ROOT / pool.pool.physical_host_id
        _private_directory(self.directory)
        self.path = self.directory / "ledger.sqlite3"
        with self.locked() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS configuration
                (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS allocations
                (reservation_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                 request_json TEXT NOT NULL, receipt_json TEXT NOT NULL);""")
            self._configuration(db, "pool", pool.model_dump_json())
            self._configuration(db, "runner:" + runner.executor_instance_id, runner.model_dump_json())

    def _configuration(self, db, key, value):
        existing = db.execute("SELECT value FROM configuration WHERE key=?", (key,)).fetchone()
        if existing is not None and json.loads(existing[0]) != json.loads(value):
            raise ValueError("resource_local_registration_conflict")
        db.execute("INSERT OR IGNORE INTO configuration VALUES (?, ?)", (key, value))

    @contextmanager
    def locked(self):
        fd = _file(self.directory / "start.lock")
        db = None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.close(_file(self.path))
            db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_mode=DELETE")
            yield db
        finally:
            if db is not None:
                db.close()
            os.close(fd)

    @staticmethod
    def read(db, reservation_id):
        row = db.execute("SELECT request_json, receipt_json FROM allocations WHERE reservation_id=?",
                         (reservation_id,)).fetchone()
        return None if row is None else (json.loads(row[0]), json.loads(row[1]))

    @staticmethod
    def save(db, request, receipt, *, create=False):
        db.execute("BEGIN IMMEDIATE")
        try:
            if create:
                db.execute("INSERT INTO allocations VALUES (?, ?, ?, ?)", (
                    request.identity.reservation_id, request.identity.operation_id,
                    request.model_dump_json(), receipt.model_dump_json()))
            else:
                db.execute("UPDATE allocations SET receipt_json=? WHERE reservation_id=?",
                           (receipt.model_dump_json(), request.identity.reservation_id))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
