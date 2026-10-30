"""Explicit Linux UDS or loopback-only development serving; no TLS installation."""

import argparse
from contextlib import contextmanager
import os
import socket
import stat
import sys

from modules.identity.credential_files import _open_private_directory, validate_destination


class ServerArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, '{"code":"invalid_api_arguments"}\n')


def build_parser() -> argparse.ArgumentParser:
    parser = ServerArgumentParser(description="CloudHelm API: private Linux socket or explicit loopback development port.")
    listener = parser.add_mutually_exclusive_group(required=True)
    listener.add_argument("--uds", help="Absolute socket path inside a private, Linux-native 0700 directory.")
    listener.add_argument("--dev-loopback-port", type=int, help="Explicit 127.0.0.1 development port, 1024..65535.")
    return parser


@contextmanager
def private_socket(destination: str):
    path = validate_destination(destination)
    if len(os.fsencode(path)) > 107:
        raise ValueError("api_socket_path_too_long")
    directory_fd = _open_private_directory(path.parent)
    listener, created = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM), None
    try:
        old_mask = os.umask(0o177)
        try:
            listener.bind(f"/proc/self/fd/{directory_fd}/{path.name}")
        finally:
            os.umask(old_mask)
        created = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISSOCK(created.st_mode) or stat.S_IMODE(created.st_mode) != 0o600
                or created.st_uid != os.geteuid()):
            raise ValueError("api_socket_permissions_invalid")
        listener.set_inheritable(False)
        yield listener
    finally:
        listener.close()
        if created is not None:
            try:
                current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    os.unlink(path.name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    arguments = build_parser().parse_args(argv)
    try:
        if sys.platform != "linux":
            raise ValueError("api_linux_required")
        if arguments.dev_loopback_port is not None and not 1024 <= arguments.dev_loopback_port <= 65535:
            raise ValueError("api_port_invalid")
        from .app import create_app
        from .preview_transport import PreviewServer
        import uvicorn

        settings = {
            "access_log": False, "proxy_headers": False, "server_header": False,
            "log_level": "warning", "lifespan": "on", "timeout_graceful_shutdown": 10,
        }
        if arguments.uds:
            with private_socket(arguments.uds) as listener:
                server = PreviewServer(uvicorn.Config(create_app(), uds=arguments.uds, **settings))
                server.run(sockets=[listener])
        else:
            server = PreviewServer(uvicorn.Config(
                create_app(), host="127.0.0.1", port=arguments.dev_loopback_port, **settings,
            ))
            server.run()
        if not server.started:
            raise ValueError("api_startup_failed")
        return 0
    except ImportError:
        print('{"code":"api_runtime_dependency_unavailable"}', file=sys.stderr)
    except Exception:
        print('{"code":"api_server_failed"}', file=sys.stderr)
    return 2
