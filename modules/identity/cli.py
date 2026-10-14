"""Linux-only identity maintenance. Credentials are delivered exclusively to files."""

import argparse
import json
import sys

from pydantic import ValidationError

from database.connection import create_engine_from_settings
from database.readiness import DatabaseNotReady
from database.settings import DatabaseConfigurationError, load_database_settings
from database.uow import DatabaseFailure
from modules.identity.bootstrap import IdentityMaintenance
from modules.identity.bootstrap_support import MaintenanceError
from modules.identity.credential_files import CredentialFileError, validate_destination
from packages.contracts.p1.identity_requests import (
    CreateProjectRequest, CreateUserRequest, DisableUserRequest, IssueSessionRequest, RevokeSessionRequest,
)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, '{"code":"invalid_cli_arguments"}\n')


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        description="CloudHelm identity maintenance using the dedicated migrator database role.",
        epilog="Configuration: CLOUDHELM_MIGRATOR_DATABASE_URL or its _FILE source; values are never printed.",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeArgumentParser)
    user = commands.add_parser("create-user", help="Create one explicitly identified human user.")
    user.add_argument("--user-id", required=True)
    user.add_argument("--display-name", required=True)
    project = commands.add_parser("create-project", help="Create a project with an explicit existing owner.")
    project.add_argument("--project-id", required=True)
    project.add_argument("--owner-user-id", required=True)
    project.add_argument("--name", required=True)
    issue = commands.add_parser("issue-session", help="Write a limited-lifetime bearer to a new private file.")
    issue.add_argument("--user-id", required=True)
    issue.add_argument("--credential-file", required=True, help="Absolute Linux-native path; private directories are 0700.")
    issue.add_argument("--lifetime-seconds", type=int, default=28800, help="60..86400; default 28800.")
    disable = commands.add_parser("disable-user", help="Disable a user; subsequent requests and worker actions fail current checks.")
    disable.add_argument("--user-id", required=True)
    revoke = commands.add_parser("revoke-session", help="Revoke one session; already accepted commands retain their recorded origin.")
    revoke.add_argument("--session-id", required=True)
    return parser


def _request(arguments):
    values = vars(arguments).copy()
    command = values.pop("command")
    schemas = {
        "create-user": ("create_user", CreateUserRequest),
        "create-project": ("create_project", CreateProjectRequest),
        "issue-session": ("issue_session", IssueSessionRequest),
        "disable-user": ("disable_user", DisableUserRequest),
        "revoke-session": ("revoke_session", RevokeSessionRequest),
    }
    method, schema = schemas[command]
    return method, schema.model_validate(values)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    arguments = build_parser().parse_args(argv)
    engine = None
    try:
        method, request = _request(arguments)
        if sys.platform != "linux":
            raise MaintenanceError("maintenance_linux_required")
        if method == "issue_session":
            validate_destination(request.credential_file)
        settings = load_database_settings("migrator")
        engine = create_engine_from_settings(settings, purpose="maintenance")
        result = getattr(IdentityMaintenance(engine), method)(request)
        print(result.model_dump_json(exclude_none=True))
        return 0
    except MaintenanceError as error:
        print(json.dumps({"code": error.code, **error.references}, ensure_ascii=False), file=sys.stderr)
    except CredentialFileError as error:
        print(json.dumps({"code": str(error)}), file=sys.stderr)
    except (DatabaseConfigurationError, DatabaseNotReady, DatabaseFailure) as error:
        print(json.dumps({"code": str(error)}), file=sys.stderr)
    except (ValidationError, ValueError, TypeError):
        print('{"code":"maintenance_request_invalid"}', file=sys.stderr)
    except Exception:
        print('{"code":"maintenance_failed"}', file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
