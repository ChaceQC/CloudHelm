"""Stable delivery failures; never include driver, host path or process diagnostics."""

from modules.collaboration.errors import TaskBoundaryError


class BuildBoundaryError(TaskBoundaryError):
    pass
