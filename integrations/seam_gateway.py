"""P0 Gateway adapter: current business gate and side effect share a transaction."""

from contextlib import contextmanager
from typing import Any, Iterator

from scripts.p0.gateway_probe import CurrentGate, GateDenied, Gateway
from integrations.seam_admission import ExecutionScope, SeamAdmission


class AdmittedGateway(Gateway):
    def __init__(self, probe_id: str, admission: SeamAdmission, scope: ExecutionScope):
        super().__init__(probe_id, CurrentGate())
        self.admission = admission
        self.scope = scope

    @contextmanager
    def _authorized_transaction(
        self, tool_name: str, operation_id: str | None, supplied_revision: str
    ) -> Iterator[Any]:
        allowed, _ = self.gate.decision(tool_name, supplied_revision)
        if not allowed:
            raise GateDenied("gateway_action_or_revision_denied")
        with self.admission.engine.begin() as connection:
            self.admission.check_current(self.scope, tool_name, connection=connection)
            yield connection.connection.driver_connection
