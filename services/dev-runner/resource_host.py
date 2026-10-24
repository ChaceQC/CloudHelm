"""Explicit root maintenance entry for registered local execution boundaries."""

import json
import fcntl
import os
import re
import socket
import stat
import struct
from importlib import import_module
from contextlib import contextmanager

from pydantic import Field

from database.connection import create_engine_from_settings
from database.settings import load_database_settings
from database.uow import UnitOfWork
from modules.execution.application import ResourceApplication
from modules.execution.cli import LocalRunnerConfiguration, read_registration_file
from modules.execution.dispatch import ResourceDispatcher
from modules.execution.registry import register_pool_in_uow, register_runner_in_uow
from modules.identity.cli import SafeArgumentParser
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p1.resource_protocol import BACKEND, STORAGE_BACKEND
from .resource_channel import MAX_MESSAGE, SOCKET
from .resource_ledger import ResourceLedger
from .resource_runtime import ResourceRunner


class HostConfiguration(Contract):
    registrations: tuple[LocalRunnerConfiguration, ...] = Field(min_length=1, max_length=64)


class HostRequest(Contract):
    action: str = Field(pattern="^(accept|start|query|stop|network)$")
    executor_id: Identifier
    reservation_id: Identifier
    network_id: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


def boundary_for(configuration, ledger):
    registration = configuration.runner
    if registration.backend == BACKEND:
        module = import_module("services.dev-runner.resource_limits")
        return module.DockerScratchBoundary(registration, configuration.argv)
    if configuration.argv:
        raise ValueError("resource_managed_backend_rejects_custom_argv")
    if registration.backend == STORAGE_BACKEND:
        module = import_module("services.dev-runner.resource_storage")
        return module.StorageBoundary(registration)
    module = import_module("services.dev-runner.resource_development")
    return module.DevelopmentBoundary(registration, ledger)


@contextmanager
def _host_lock():
    descriptor = os.open(SOCKET + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_uid != 0 or state.st_nlink != 1 or state.st_mode & 0o077:
            raise ValueError("resource_host_lock_identity_mismatch")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("resource_host_already_running") from None
        if os.path.lexists(SOCKET):
            previous = os.lstat(SOCKET)
            if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != 0:
                raise ValueError("resource_host_socket_identity_mismatch")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                try:
                    probe.connect(SOCKET)
                except ConnectionRefusedError:
                    current = os.lstat(SOCKET)
                    if (current.st_dev, current.st_ino) != (previous.st_dev, previous.st_ino):
                        raise ValueError("resource_host_socket_changed")
                    os.unlink(SOCKET)
                else:
                    raise ValueError("resource_host_socket_has_live_listener")
        yield
    finally:
        os.close(descriptor)


def serve(configuration, application):
    dispatchers = {}
    for entry in configuration.registrations:
        identity = entry.runner.executor_instance_id
        if identity in dispatchers:
            raise ValueError("resource_host_duplicate_runner")
        ledger = ResourceLedger(entry.pool, entry.runner)
        runner = ResourceRunner(ledger, boundary_for(entry, ledger))
        dispatchers[identity] = ResourceDispatcher(application, runner)
    with _host_lock():
        _serve_dispatchers(dispatchers)


def _serve_dispatchers(dispatchers):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(SOCKET)
        identity = os.lstat(SOCKET)
        os.chown(SOCKET, 0, 1000)
        os.chmod(SOCKET, 0o660)
        listener.listen(8)
        try:
            while True:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(50)
                    try:
                        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid not in {0, 1000}:
                            raise ValueError("resource_host_peer_rejected")
                        with connection.makefile("rb") as stream:
                            raw = stream.readline(MAX_MESSAGE + 1)
                        if len(raw) > MAX_MESSAGE or not raw.endswith(b"\n"):
                            raise ValueError("resource_host_request_bound_exceeded")
                        request = HostRequest.model_validate_json(raw)
                        dispatcher = dispatchers[request.executor_id]
                        if request.action == "network":
                            if request.network_id is None:
                                raise ValueError("resource_network_identity_required")
                            dispatcher._request(request.reservation_id)
                            with dispatcher.runner.ledger.locked() as db:
                                resources, fact = dispatcher.runner._read(db, request.reservation_id)
                                if fact.state != "running":
                                    raise ValueError("resource_network_requires_running_binding")
                                application = dispatcher.application
                                application.check_start(request.reservation_id)
                                from .resource_network import authorize

                                authorize(dispatcher.runner.boundary, resources, request.network_id)
                            dispatcher.reconcile(request.reservation_id)
                            receipt = dispatcher.runner.query(request.reservation_id)
                            response = {"status": "ok", "receipt": receipt.model_dump(mode="json")}
                            connection.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
                            continue
                        if request.network_id is not None:
                            raise ValueError("resource_network_identity_unexpected")
                        method = {"accept": dispatcher.deliver, "start": dispatcher.start,
                                  "stop": dispatcher.stop, "query": dispatcher.reconcile}[request.action]
                        method(request.reservation_id)
                        receipt = dispatcher.runner.query(request.reservation_id)
                        response = {"status": "ok", "receipt": None if receipt is None else receipt.model_dump(mode="json")}
                    except Exception:
                        response = {"status": "rejected"}  # No database/configuration/daemon exception text.
                    try:
                        connection.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
                    except OSError:
                        pass  # A lost reply does not stop the host or erase its durable receipt.
        finally:
            current = os.lstat(SOCKET)
            if stat.S_ISSOCK(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                os.unlink(SOCKET)


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "serve"))
    parser.add_argument("--registration-file", required=True)
    arguments = parser.parse_args()
    engine = None
    try:
        if os.geteuid() != 0:
            raise ValueError("resource_host_explicit_root_maintenance_required")
        configuration = read_registration_file(arguments.registration_file, HostConfiguration)
        role = "migrator" if arguments.action == "register" else "worker"
        engine = create_engine_from_settings(load_database_settings(role), purpose="maintenance" if role == "migrator" else "control")
        if arguments.action == "register":
            with UnitOfWork(engine) as uow:
                for entry in configuration.registrations:
                    register_pool_in_uow(uow, entry.pool)
                    register_runner_in_uow(uow, entry.runner)
            print(json.dumps({"status": "registered", "runner_count": len(configuration.registrations)}))
        else:
            serve(configuration, ResourceApplication(engine, engine))
        return 0
    except Exception as error:
        code = str(error) if type(error) is ValueError else "resource_host_unavailable"
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
            code = "resource_host_rejected"
        print(json.dumps({"status": "rejected", "code": code}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
