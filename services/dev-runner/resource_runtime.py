"""Durable acceptance/start/stop protocol shared by independent Runner instances."""

from packages.contracts.p0.resource_contracts import ResourceAllocation, ResourceRequest, validate_admission
from packages.contracts.p1.resource_protocol import (
    ExecutorReceipt, allocation_from_receipt, match_runner, resource_request_digest,
)
from .resource_ledger import ResourceLedger


class ResourceRunner:
    def __init__(self, ledger: ResourceLedger, boundary):
        self.ledger, self.boundary = ledger, boundary
        self.registration = ledger.registration
        if boundary.backend != self.registration.backend:
            raise ValueError("resource_boundary_capability_mismatch")
        if boundary.backend == "linux-development-storage-r1":
            boundary.ledger = ledger

    def _read(self, db, reservation_id):
        stored = self.ledger.read(db, reservation_id)
        if stored is None:
            raise ValueError("resource_local_reservation_not_found")
        request, receipt = ResourceRequest.model_validate(stored[0]), ExecutorReceipt.model_validate(stored[1])
        if request.identity.executor_instance_id != self.registration.executor_instance_id:
            raise ValueError("resource_local_executor_mismatch")
        return request, receipt

    def accept(self, request: ResourceRequest, *, backend):
        if request.request_digest != resource_request_digest(request):
            raise ValueError("resource_request_digest_mismatch")
        match_runner(self.registration, request, backend)
        with self.ledger.locked() as db:
            previous = self.ledger.read(db, request.identity.reservation_id)
            if previous is not None:
                if ResourceRequest.model_validate(previous[0]) != request:
                    raise ValueError("resource_local_identity_digest_conflict")
                return ExecutorReceipt.model_validate(previous[1])
            allocations = []
            for raw, fact in db.execute("SELECT request_json, receipt_json FROM allocations"):
                import json
                old = ResourceRequest.model_validate(json.loads(raw))
                receipt = ExecutorReceipt.model_validate_json(fact)
                if old.identity.operation_id == request.identity.operation_id:
                    raise ValueError("resource_local_operation_identity_conflict")
                if (old.identity.resource_group_id == request.identity.resource_group_id
                        and (old.identity.resource_generation >= request.identity.resource_generation
                             or receipt.state not in {"closed_unstarted", "stopped"} or not receipt.disk_reclaimed)):
                    raise ValueError("resource_local_generation_or_group_conflict")
                original = ResourceAllocation(identity=old.identity, creation_request_digest=old.request_digest,
                    allocation_revision=1, state="reserved", accounted_vector=old.accounted_vector,
                    hard_limits=old.hard_limits)
                allocations.append(allocation_from_receipt(original, receipt))
            try:
                validate_admission(self.ledger.pool.pool, tuple(allocations), request)
                self.boundary.check_capability(request)
            except Exception:
                receipt = ExecutorReceipt(identity=request.identity, request_digest=request.request_digest,
                    sequence=1, state="closed_unstarted", disk_reclaimed=True,
                    evidence={"local_admission_rejected": True})
            else:
                receipt = ExecutorReceipt(identity=request.identity, request_digest=request.request_digest,
                                          sequence=1, state="accepted")
            self.ledger.save(db, request, receipt, create=True)
            return receipt

    def _save(self, db, request, previous, **values):
        evidence = values.get("evidence", {})
        if values.get("state") == "stopped" and "disk_remaining_bytes" in evidence:
            values |= {"protocol_revision": "p1-resources-r2",
                       "disk_remaining_bytes": evidence["disk_remaining_bytes"]}
        receipt = ExecutorReceipt.model_validate(previous.model_dump() | {
            "sequence": previous.sequence + 1, **values,
        })
        self.ledger.save(db, request, receipt)
        return receipt

    def start(self, reservation_id, check_current_start):
        with self.ledger.locked() as db:
            request, previous = self._read(db, reservation_id)
            if previous.state != "accepted":
                return previous  # includes the durable closed fence and unknown launch.
            try:
                check_current_start()
                self.boundary.check_capability(request)
            except Exception:
                return self._save(db, request, previous, state="closed_unstarted", disk_reclaimed=True,
                                  evidence={"start_gate_closed": True})
            binding = self.boundary.binding(request)
            launching = self._save(db, request, previous, state="launching", process_binding=binding)
            # Commit the launch marker before the first physical side effect.
            # A crash here is reconciled by identity; never launch a second time.
            try:
                evidence = self.boundary.start(request)
            except Exception:
                return self._save(db, request, launching, state="unknown", evidence={"start_unconfirmed": True})
            return self._save(db, request, launching, state="running", evidence=evidence)

    def query(self, reservation_id):
        with self.ledger.locked() as db:
            if self.ledger.read(db, reservation_id) is None:
                return None
            request, previous = self._read(db, reservation_id)
            if previous.state == "stopped":
                observer = getattr(self.boundary, "observe_stopped", None)
                if previous.disk_reclaimed or not callable(observer):
                    return previous
                try:
                    state, reclaimed, evidence = observer(request)
                except Exception:
                    return previous  # A missing disk observation cannot undo the stop fence.
                if (state, reclaimed, evidence) == (previous.state, previous.disk_reclaimed, previous.evidence):
                    return previous
                return self._save(db, request, previous, state=state, disk_reclaimed=reclaimed, evidence=evidence)
            if previous.state not in {"launching", "running", "unknown", "stopped"} or previous.disk_reclaimed:
                return previous
            try:
                state, reclaimed, evidence = self.boundary.observe(request)
            except Exception:
                state, reclaimed, evidence = "unknown", False, {"observation_unconfirmed": True}
            if (state, reclaimed, evidence) == (previous.state, previous.disk_reclaimed, previous.evidence):
                return previous
            return self._save(db, request, previous, state=state, disk_reclaimed=reclaimed, evidence=evidence)

    def stop(self, reservation_id):
        with self.ledger.locked() as db:
            request, previous = self._read(db, reservation_id)
            if previous.state == "accepted":
                return self._save(db, request, previous, state="closed_unstarted", disk_reclaimed=True)
            if previous.state == "closed_unstarted" or (previous.state == "stopped" and previous.disk_reclaimed):
                return previous
            if previous.state == "stopped" and previous.protocol_revision == "p1-resources-r2":
                return self.query(reservation_id)
            try:
                reclaimed, evidence = self.boundary.stop(request)
            except Exception:
                return self._save(db, request, previous, state="unknown", disk_reclaimed=False,
                                  evidence={"stop_unconfirmed": True})
            return self._save(db, request, previous, state="stopped", disk_reclaimed=reclaimed, evidence=evidence)
