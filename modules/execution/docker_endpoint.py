"""Trusted local execution context; endpoint selection never comes from HTTP input."""

from contextlib import contextmanager
from contextvars import ContextVar

_ENDPOINT = ContextVar("cloudhelm_docker_socket", default="/var/run/docker.sock")


def socket_path():
    return _ENDPOINT.get()


@contextmanager
def use_socket(path):
    token = _ENDPOINT.set(str(path))
    try:
        yield
    finally:
        _ENDPOINT.reset(token)
