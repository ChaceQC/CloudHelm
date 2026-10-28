"""Linux-only local archive maintenance; credentials are read from private files."""

import argparse
import json
import os
import stat
import sys

from pydantic import SecretStr, TypeAdapter, ValidationError

from database.commands import CommandConflict
from database.connection import create_engine_from_settings
from database.maintenance import MaintenanceError as DatabaseMaintenanceError
from database.readiness import DatabaseNotReady
from database.settings import DatabaseConfigurationError, load_database_settings
from database.uow import DatabaseFailure, UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.delivery.archive_maintenance import (
    close_archive_deployment, issue_archive_session, receive_archive_closeout,
)
from modules.identity.bootstrap_support import MaintenanceError as IdentityMaintenanceError
from modules.identity.credential_files import CredentialFileError
from modules.identity.errors import IdentityError
from packages.contracts.p0.decision_common import Identifier
from packages.contracts.p0.identity_contracts import parse_request
from packages.contracts.p1.closeout_contracts import RemoteCloseoutReceipt
from packages.contracts.p1.delivery_requests import CloseDeploymentRequest
from packages.contracts.p1.identity_requests import IssueSessionRequest

MAX_INPUT_BYTES = 65_536


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"code":"invalid_cli_arguments"}\n')


def _private_file(path, limit):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise ValueError
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError
        return data
    except (OSError, ValueError):
        raise ValueError("private_input_file_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _input_body(path, schema):
    try:
        return parse_request(_private_file(path, MAX_INPUT_BYTES).decode("utf-8", errors="strict"), schema)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("archive_input_invalid") from None


def _token(path):
    try:
        return SecretStr(_private_file(path, 16_384).decode("ascii", errors="strict").strip())
    except UnicodeError:
        raise ValueError("archive_input_invalid") from None


def build_parser():
    parser = SafeArgumentParser(description="Restricted original-operation archive maintenance")
    commands = parser.add_subparsers(dest="action", required=True, parser_class=SafeArgumentParser)
    receive = commands.add_parser("receive-receipt")
    receive.add_argument("--operation-id", required=True)
    receive.add_argument("--token-file", required=True)
    receive.add_argument("--receipt-file", required=True)
    close = commands.add_parser("close")
    close.add_argument("--operation-id", required=True)
    close.add_argument("--bearer-file", required=True)
    close.add_argument("--request-file", required=True)
    close.add_argument("--idempotency-key", required=True)
    issue = commands.add_parser("issue-session")
    issue.add_argument("--operation-id", required=True)
    issue.add_argument("--user-id", required=True)
    issue.add_argument("--credential-file", required=True)
    issue.add_argument("--lifetime-seconds", type=int, default=28800)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    args = build_parser().parse_args(argv)
    engine = None
    try:
        if sys.platform != "linux":
            raise ValueError("maintenance_linux_required")
        operation_id = TypeAdapter(Identifier).validate_python(args.operation_id)
        if args.action == "issue-session":
            request = IssueSessionRequest(user_id=args.user_id, credential_file=args.credential_file,
                lifetime_seconds=args.lifetime_seconds)
        else:
            token = _token(args.token_file if args.action == "receive-receipt" else args.bearer_file)
            request = _input_body(args.receipt_file if args.action == "receive-receipt" else args.request_file,
                RemoteCloseoutReceipt if args.action == "receive-receipt" else CloseDeploymentRequest)
            if args.action == "close":
                idempotency_key = TypeAdapter(Identifier).validate_python(args.idempotency_key)
        engine = create_engine_from_settings(load_database_settings("migrator"), purpose="maintenance")
        if args.action == "issue-session":
            result = issue_archive_session(engine, operation_id, request)
            print(result.model_dump_json(exclude_none=True))
        else:
            with UnitOfWork(engine) as uow:
                if args.action == "receive-receipt":
                    result = receive_archive_closeout(uow, operation_id, token, request)
                else:
                    result = close_archive_deployment(uow, operation_id, token, request,
                        idempotency_key=idempotency_key)
            if args.action == "receive-receipt":
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(result.model_dump_json())
                return 0 if result.status_code == 200 else 1
        return 0
    except IdentityMaintenanceError as error:
        print(json.dumps({"code": error.code, **error.references}, ensure_ascii=False), file=sys.stderr)
    except (TaskBoundaryError, IdentityError) as error:
        print(json.dumps({"code": error.code}), file=sys.stderr)
    except (DatabaseMaintenanceError, DatabaseNotReady, DatabaseConfigurationError, DatabaseFailure,
            CredentialFileError, CommandConflict) as error:
        print(json.dumps({"code": str(error)}), file=sys.stderr)
    except (ValidationError, ValueError, TypeError):
        print('{"code":"archive_input_invalid"}', file=sys.stderr)
    except Exception:
        print('{"code":"archive_maintenance_unavailable"}', file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
