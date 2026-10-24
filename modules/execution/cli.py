"""Trusted Linux resource maintenance/dispatch; never prints configuration values."""

import json
import os
import re
import stat
from importlib import import_module

from pydantic import Field

from database.connection import create_engine_from_settings
from database.settings import load_database_settings
from database.uow import UnitOfWork
from modules.identity.cli import SafeArgumentParser
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p1.resource_protocol import PoolRegistration, RunnerRegistration
from .application import ResourceApplication
from .dispatch import ResourceDispatcher
from .registry import register_pool_in_uow, register_runner_in_uow


class LocalRunnerConfiguration(Contract):
    pool: PoolRegistration
    runner: RunnerRegistration
    argv: tuple[str, ...] = Field(default=(), max_length=64)


def read_registration_file(path, model=LocalRunnerConfiguration):
    """Only this bounded, secret-free schema is read; raw values never escape."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        state = os.fstat(fd)
        if (not stat.S_ISREG(state.st_mode) or state.st_mode & 0o077 or state.st_nlink != 1
                or (os.geteuid() != 0 and state.st_uid != os.getuid()) or state.st_size > 65536):
            raise ValueError("resource_registration_file_not_private")
        raw = os.read(fd, 65537)
        after = os.fstat(fd)
        if (len(raw) != state.st_size or (state.st_size, state.st_mtime_ns, state.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("resource_registration_file_changed")
        return model.model_validate_json(raw)
    finally:
        os.close(fd)


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "accept", "start", "query", "stop"))
    parser.add_argument("--registration-file", required=True)
    parser.add_argument("--reservation-id")
    arguments = parser.parse_args()
    engine = None
    try:
        if os.name != "posix":
            raise ValueError("resource_linux_controller_required")
        configuration = read_registration_file(arguments.registration_file)
        role = "migrator" if arguments.action == "register" else "worker"
        engine = create_engine_from_settings(load_database_settings(role), purpose="maintenance" if role == "migrator" else "control")
        if arguments.action == "register":
            with UnitOfWork(engine) as uow:
                register_pool_in_uow(uow, configuration.pool)
                register_runner_in_uow(uow, configuration.runner)
            result = {"status": "registered"}
        else:
            if not arguments.reservation_id:
                raise ValueError("resource_reservation_id_required")
            ledger = import_module("services.dev-runner.resource_ledger")
            runtime = import_module("services.dev-runner.resource_runtime")
            host = import_module("services.dev-runner.resource_host")
            local = ledger.ResourceLedger(configuration.pool, configuration.runner)
            runner = runtime.ResourceRunner(local, host.boundary_for(configuration, local))
            application = ResourceApplication(engine, engine)
            dispatcher = ResourceDispatcher(application, runner)
            method = {"accept": dispatcher.deliver, "start": dispatcher.start,
                      "query": dispatcher.reconcile, "stop": dispatcher.stop}[arguments.action]
            allocation = method(arguments.reservation_id)
            result = {"status": allocation.state, "reservation_id": allocation.identity.reservation_id,
                      "allocation_revision": allocation.allocation_revision,
                      "accounted_vector": allocation.accounted_vector.model_dump()}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as failure:
        code = str(failure) if type(failure) is ValueError else "resource_controller_unavailable"
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
            code = "resource_controller_rejected"
        print(json.dumps({"status": "rejected", "code": code}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
