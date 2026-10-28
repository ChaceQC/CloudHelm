"""Per-request supplier observations and P0 official-price calculations."""

import json
from decimal import Decimal
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import case, func, insert, select

from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.tables import tasks
from packages.contracts.p2.model_usage import ModelUsageResult, ModelUsageScope, SafeIdentifier
from .billing_tables import agent_model_request_results
from .tables import agent_model_requests, agent_runs, agent_sessions


_PRICE = json.loads((Path(__file__).resolve().parents[2] / "packages/contracts/p0/"
                     "official-model-prices-r1.json").read_text(encoding="utf-8"))
_EVIDENCE_REF = TypeAdapter(SafeIdentifier)


def _latest(column):
    return (select(column).where(
        agent_model_request_results.c.request_record_id == agent_model_requests.c.request_record_id,
    ).order_by(agent_model_request_results.c.revision.desc()).limit(1)
        .correlate(agent_model_requests).scalar_subquery())


def model_request_cost():
    """Known cost, or the reservation plus any larger known USD bill."""
    currency = _latest(agent_model_request_results.c.billed_currency)
    billed = func.coalesce(case((currency == "USD", _latest(
        agent_model_request_results.c.billed_amount))), 0)
    calculated = _latest(agent_model_request_results.c.calculated_cost)
    return case((calculated.is_(None), func.greatest(agent_model_requests.c.reserved_cost, billed)),
                else_=func.greatest(calculated, billed))


def model_request_unknown():
    """Usage/official cost still needs reconciliation, even if a bill is known."""
    return _latest(agent_model_request_results.c.calculated_cost).is_(None)


def model_request_bound_exceeded():
    return func.coalesce(_latest(agent_model_request_results.c.reservation_bound_exceeded), False)


def _merge(old: ModelUsageResult | None, incoming: ModelUsageResult) -> ModelUsageResult:
    if old is None:
        return incoming
    merged, addition = old.model_dump(), incoming.model_dump()
    for field, value in addition.items():
        if value is None:
            continue
        if field == "usage" and merged[field] is not None:
            for name, count in value.items():
                if count is not None:
                    if merged[field][name] is not None and merged[field][name] != count:
                        raise TaskBoundaryError("model_result_conflict")
                    merged[field][name] = count
        elif merged[field] is not None and merged[field] != value:
            raise TaskBoundaryError("model_result_conflict")
        else:
            merged[field] = value
    return ModelUsageResult.model_validate(merged)


def _calculate(result: ModelUsageResult, start: dict):
    """Apply the fixed P0 Standard/global/function-only price basis."""
    model = start["policy"]["model_name"]
    usage = result.usage
    if (start["context"]["budget_currency"] != _PRICE["currency"]
            or model not in _PRICE["models"] or result.response_model != model
            or result.service_tier not in ("default", _PRICE["service_tier"])
            or usage is None or usage.input_tokens is None):
        return None, None
    spec = _PRICE["models"][model]
    if (usage.input_tokens > spec["context_window_tokens"]
            or (usage.output_tokens is not None and (
                usage.output_tokens > spec["maximum_output_tokens"]
                or usage.input_tokens + usage.output_tokens > spec["context_window_tokens"]))):
        return None, None
    context = "long" if usage.input_tokens > spec["long_context_threshold_tokens"] else "short"
    rates = spec["rates_usd_per_million_tokens"][context]
    uncached = None
    if usage.cached_input_tokens is not None and usage.cache_write_tokens is not None:
        uncached = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    token_counts = {"uncached_input": uncached, "cached_input": usage.cached_input_tokens,
                    "cache_write": usage.cache_write_tokens, "output": usage.output_tokens}
    amounts = {name: (Decimal(count) * Decimal(rates[name]) / Decimal(_PRICE["token_unit"])
                      if count is not None else None) for name, count in token_counts.items()}
    details = {"currency": _PRICE["currency"], "context_class": context,
               "service_tier": _PRICE["service_tier"], "processing_mode": "global",
               "other_charges_usd": "0", "other_charges_basis": "custom_function_tools_only",
               "amounts": {name: str(amount) if amount is not None else None
                           for name, amount in amounts.items()}}
    total = sum(amounts.values(), Decimal(0)) if all(value is not None for value in amounts.values()) else None
    return details, total


class RuntimeBilling:
    def __init__(self, engine):
        self.engine = engine

    async def record(self, request_record_id: str, result: ModelUsageResult | dict) -> None:
        """Record a response to an already admitted HTTP attempt; never send a request."""
        self._store(request_record_id, ModelUsageResult.model_validate(result))

    async def reconcile(self, request_record_id: str, result: ModelUsageResult | dict, *,
                        actor, scope: ModelUsageScope | dict, evidence_ref: str) -> None:
        """Add late evidence under current authorization, including after cancellation."""
        self._store(_EVIDENCE_REF.validate_python(request_record_id), ModelUsageResult.model_validate(result), actor=actor,
                    scope=ModelUsageScope.model_validate(scope),
                    evidence_ref=_EVIDENCE_REF.validate_python(evidence_ref))

    def _store(self, request_record_id, incoming, *, actor=None, scope=None, evidence_ref=None):
        with UnitOfWork(self.engine) as uow:
            connection = uow.connection
            source = connection.execute(select(
                agent_sessions.c.task_id, agent_sessions.c.session_id, agent_runs.c.run_id,
                agent_runs.c.start_json, agent_model_requests.c.body_bytes,
                agent_model_requests.c.reserved_cost,
            ).select_from(agent_model_requests.join(agent_runs).join(agent_sessions)).where(
                agent_model_requests.c.request_record_id == request_record_id)).mappings().one_or_none()
            if source is None:
                raise TaskBoundaryError("model_request_not_found")
            if scope is None:
                connection.execute(select(tasks.c.task_id).where(
                    tasks.c.task_id == source["task_id"]).with_for_update()).scalar_one()
            else:
                if (scope.task_id != source["task_id"] or scope.session_id != source["session_id"]
                        or scope.run_id != source["run_id"]):
                    raise TaskBoundaryError("model_reconciliation_scope_mismatch")
                task, authorization = lock_task_access(uow, actor, scope.task_id, "task.command")
                if (scope.control_revision != task["control_revision"]
                        or scope.input_validity_revision != task["input_validity_revision"]
                        or scope.permission_revision != authorization.envelope.permission_revision):
                    raise TaskBoundaryError("model_reconciliation_scope_stale")
            previous = connection.execute(select(agent_model_request_results).where(
                agent_model_request_results.c.request_record_id == request_record_id,
            ).order_by(agent_model_request_results.c.revision.desc()).limit(1)).mappings().one_or_none()
            if previous and previous["price_revision"] != _PRICE["revision"]:
                raise TaskBoundaryError("model_price_revision_mismatch")
            if (previous and evidence_ref is not None and previous["reconciliation_evidence_ref"] is not None
                    and previous["reconciliation_evidence_ref"] != evidence_ref):
                raise TaskBoundaryError("model_reconciliation_evidence_conflict")
            old = ModelUsageResult.model_validate(previous["result_json"]) if previous else None
            merged = _merge(old, incoming)
            if previous and scope is None and merged != old:
                raise TaskBoundaryError("model_reconciliation_required")
            if (previous and merged == old and
                    (evidence_ref is None or evidence_ref == previous["reconciliation_evidence_ref"])):
                return
            details, calculated = _calculate(merged, source["start_json"])
            if previous and previous["calculated_cost"] is not None and previous["calculated_cost"] != calculated:
                raise TaskBoundaryError("model_result_conflict")
            usage = merged.usage
            exceeded = bool(previous and previous["reservation_bound_exceeded"])
            exceeded |= bool(usage and ((usage.input_tokens is not None
                and usage.input_tokens > source["body_bytes"] + 8192)
                or (usage.output_tokens is not None
                    and usage.output_tokens > source["start_json"]["policy"]["max_output_tokens"])))
            exceeded |= bool(calculated is not None and calculated > source["reserved_cost"])
            exceeded |= bool(merged.billed_currency == "USD" and merged.billed_amount is not None
                             and merged.billed_amount > source["reserved_cost"])
            connection.execute(insert(agent_model_request_results).values(
                request_record_id=request_record_id, revision=previous["revision"] + 1 if previous else 1,
                result_json=merged.model_dump(mode="json"), price_revision=_PRICE["revision"],
                calculation_json=details, calculated_cost=calculated, billed_amount=merged.billed_amount,
                billed_currency=merged.billed_currency, reservation_bound_exceeded=exceeded,
                reconciliation_evidence_ref=evidence_ref or (previous["reconciliation_evidence_ref"] if previous else None),
            ))
