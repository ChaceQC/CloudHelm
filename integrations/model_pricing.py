"""Official token price calculations for the supported OpenAI model snapshot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any


class PricingInputError(ValueError):
    """Raised when pricing inputs are invalid or outside the frozen scope."""


_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "contracts"
    / "p0"
    / "official-model-prices-r1.json"
)
_SNAPSHOT = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
PRICE_REVISION = _SNAPSHOT["revision"]
_MODEL = "gpt-6-luna"
_MODEL_PRICES = _SNAPSHOT["models"][_MODEL]
_TOKEN_UNIT = Decimal(str(_SNAPSHOT["token_unit"]))


def _require_model(model: str) -> None:
    if not isinstance(model, str) or model != _MODEL:
        raise PricingInputError(f"unsupported model: {model!r}")


def _require_tier(service_tier: str) -> None:
    if not isinstance(service_tier, str) or service_tier != _SNAPSHOT["service_tier"]:
        raise PricingInputError(f"unsupported service tier: {service_tier!r}")


def _require_processing_mode(processing_mode: str) -> Decimal:
    modes = _SNAPSHOT["processing_modes"]
    if not isinstance(processing_mode, str) or processing_mode not in modes:
        raise PricingInputError(
            f"unsupported processing mode: {processing_mode!r}"
        )
    return Decimal(modes[processing_mode]["multiplier"])


def _token_value(value: object, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise PricingInputError(f"{field} must be a non-negative integer or null")
    if value < 0:
        raise PricingInputError(f"{field} must be a non-negative integer or null")
    return value


def _usage_value(
    usage: Mapping[str, object], flat_key: str, detail_key: str | None = None
) -> int | None:
    flat = _token_value(usage.get(flat_key), flat_key)
    details = usage.get("input_tokens_details")
    nested: int | None = None
    if details is not None and not isinstance(details, Mapping):
        raise PricingInputError("input_tokens_details must be a mapping or null")
    nested_present = detail_key is not None and isinstance(details, Mapping)
    if nested_present:
        nested = _token_value(details.get(detail_key), detail_key)
    if flat is not None and nested is not None and flat != nested:
        raise PricingInputError(f"conflicting usage values for {flat_key}")
    return flat if flat is not None else nested


def _read_usage(
    usage: Mapping[str, object] | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    if usage is None:
        return None, None, None, None
    if not isinstance(usage, Mapping):
        raise PricingInputError("usage must be a mapping or null")
    input_tokens = _usage_value(usage, "input_tokens")
    cached_tokens = _usage_value(
        usage, "cached_input_tokens", "cached_tokens"
    )
    write_tokens = _usage_value(usage, "cache_write_tokens", "cache_write_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    if (
        input_tokens is not None
        and cached_tokens is not None
        and write_tokens is not None
        and cached_tokens + write_tokens > input_tokens
    ):
        raise PricingInputError("cached and cache-write tokens exceed input tokens")
    context_window = _MODEL_PRICES["context_window_tokens"]
    maximum_output = _MODEL_PRICES["maximum_output_tokens"]
    if input_tokens is not None and input_tokens > context_window:
        raise PricingInputError("input tokens exceed the model context window")
    if output_tokens is not None and output_tokens > maximum_output:
        raise PricingInputError("output tokens exceed the supported model limit")
    if (
        input_tokens is not None
        and output_tokens is not None
        and input_tokens + output_tokens > context_window
    ):
        raise PricingInputError("input and output tokens exceed the model context window")
    return input_tokens, cached_tokens, write_tokens, output_tokens


def _context_class(input_tokens: int | None) -> str:
    if input_tokens is None:
        return "unknown"
    threshold = _MODEL_PRICES["long_context_threshold_tokens"]
    return "long" if input_tokens > threshold else "short"


def _rate(category: str, context_class: str) -> Decimal:
    rates = _MODEL_PRICES["rates_usd_per_million_tokens"]
    return Decimal(rates[context_class][category])


def _amount(tokens: int, rate: Decimal, multiplier: Decimal) -> Decimal:
    return Decimal(tokens) * rate * multiplier / _TOKEN_UNIT


def _component(
    category: str,
    tokens: int | None,
    context_class: str,
    processing_multiplier: Decimal,
) -> dict[str, object]:
    if tokens is None:
        return {
            "tokens": None,
            "amount_usd": None,
            "amount_usd_range": None,
            "rate_usd_per_million_tokens": None,
            "rate_range_usd_per_million_tokens": None,
        }
    if context_class == "unknown":
        low_rate = _rate(category, "short")
        high_rate = _rate(category, "long")
        return {
            "tokens": tokens,
            "amount_usd": None,
            "amount_usd_range": (
                _amount(tokens, low_rate, processing_multiplier),
                _amount(tokens, high_rate, processing_multiplier),
            ),
            "rate_usd_per_million_tokens": None,
            "rate_range_usd_per_million_tokens": (
                low_rate * processing_multiplier,
                high_rate * processing_multiplier,
            ),
        }
    rate = _rate(category, context_class) * processing_multiplier
    return {
        "tokens": tokens,
        "amount_usd": _amount(tokens, _rate(category, context_class), processing_multiplier),
        "amount_usd_range": None,
        "rate_usd_per_million_tokens": rate,
        "rate_range_usd_per_million_tokens": None,
    }


def _other_charge(value: Decimal | None, basis: str | None) -> None:
    if value is None:
        if basis is not None:
            raise PricingInputError("other charge basis requires an amount")
        return
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise PricingInputError("other charge amount must be a non-negative Decimal")
    if not isinstance(basis, str) or not basis.strip():
        raise PricingInputError("other charge amount requires an evidence basis")


def _cost_components(
    input_tokens: int | None,
    cached_tokens: int | None,
    write_tokens: int | None,
    output_tokens: int | None,
    processing_multiplier: Decimal,
) -> tuple[int | None, dict[str, dict[str, object]]]:
    uncached_tokens = None
    if input_tokens is not None and cached_tokens is not None and write_tokens is not None:
        uncached_tokens = input_tokens - cached_tokens - write_tokens
    context_class = _context_class(input_tokens)
    components = {
        "uncached_input": _component(
            "uncached_input", uncached_tokens, context_class, processing_multiplier
        ),
        "cached_input": _component(
            "cached_input", cached_tokens, context_class, processing_multiplier
        ),
        "cache_write": _component(
            "cache_write", write_tokens, context_class, processing_multiplier
        ),
        "output": _component(
            "output", output_tokens, context_class, processing_multiplier
        ),
    }
    return uncached_tokens, components


def _unknown_reasons(
    usage: Mapping[str, object] | None,
    input_tokens: int | None,
    cached_tokens: int | None,
    write_tokens: int | None,
    output_tokens: int | None,
    other_charges_usd: Decimal | None,
) -> tuple[str, ...]:
    if usage is None:
        missing = ["supplier_usage_missing"]
    else:
        values = (
            ("input_tokens", input_tokens),
            ("cached_input_tokens", cached_tokens),
            ("cache_write_tokens", write_tokens),
            ("output_tokens", output_tokens),
        )
        missing = [f"{field}_missing" for field, value in values if value is None]
    if other_charges_usd is None:
        missing.append("other_applicable_charges_unverified")
    return tuple(missing)


def calculate_official_usage_cost(
    usage: Mapping[str, object] | None,
    *,
    model: str,
    service_tier: str,
    processing_mode: str,
    other_charges_usd: Decimal | None,
    other_charges_basis: str | None,
) -> dict[str, object]:
    """Calculate official token charges from supplier usage; invoice stays separate.

    Flat usage fields use the Responses names `input_tokens`, `output_tokens`,
    `cached_input_tokens`, and `cache_write_tokens`. The raw Responses nested
    input token details are accepted as well. Missing evidence remains unknown.
    """
    _require_model(model)
    _require_tier(service_tier)
    processing_multiplier = _require_processing_mode(processing_mode)
    _other_charge(other_charges_usd, other_charges_basis)
    input_tokens, cached_tokens, write_tokens, output_tokens = _read_usage(usage)
    context_class = _context_class(input_tokens)
    uncached_tokens, components = _cost_components(
        input_tokens, cached_tokens, write_tokens, output_tokens, processing_multiplier
    )
    usage_complete = all(
        value is not None
        for value in (input_tokens, cached_tokens, write_tokens, output_tokens)
    )
    token_total: Decimal | None = None
    if usage_complete:
        token_total = sum(
            (components[name]["amount_usd"] for name in components), Decimal("0")
        )
    total = (
        token_total + other_charges_usd
        if token_total is not None and other_charges_usd is not None
        else None
    )
    return {
        "provider": _SNAPSHOT["provider"],
        "model": model,
        "service_tier": service_tier,
        "processing_mode": processing_mode,
        "currency": _SNAPSHOT["currency"],
        "price_revision": PRICE_REVISION,
        "price_sources": tuple(_SNAPSHOT["source_urls"]),
        "price_retrieved_on": _SNAPSHOT["retrieved_on"],
        "context_class": context_class,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_write_tokens": write_tokens,
        "uncached_input_tokens": uncached_tokens,
        "output_tokens": output_tokens,
        "components": components,
        "official_model_token_amount_usd": token_total,
        "other_charges_usd": other_charges_usd,
        "other_charges_basis": other_charges_basis,
        "official_estimated_total_usd": total,
        "supplier_invoice_amount_usd": None,
        "supplier_invoice_status": "not_provided",
        "unknown_reasons": _unknown_reasons(
            usage,
            input_tokens,
            cached_tokens,
            write_tokens,
            output_tokens,
            other_charges_usd,
        ),
    }


def calculate_reservation_upper_bound(
    *,
    model: str,
    service_tier: str,
    processing_mode: str,
    input_tokens_upper_bound: int,
    max_output_tokens: int,
    other_charges_upper_bound_usd: Decimal | None,
    other_charges_basis: str | None,
) -> dict[str, Any]:
    """Reserve a conservative token-cost upper bound using long/cache-write rates."""
    _require_model(model)
    _require_tier(service_tier)
    processing_multiplier = _require_processing_mode(processing_mode)
    input_bound = _token_value(input_tokens_upper_bound, "input_tokens_upper_bound")
    output_bound = _token_value(max_output_tokens, "max_output_tokens")
    assert input_bound is not None and output_bound is not None
    maximum_output = _MODEL_PRICES["maximum_output_tokens"]
    context_window = _MODEL_PRICES["context_window_tokens"]
    if output_bound > maximum_output:
        raise PricingInputError("max_output_tokens exceeds the supported model limit")
    if input_bound + output_bound > context_window:
        raise PricingInputError("input and output bounds exceed the model context window")
    _other_charge(other_charges_upper_bound_usd, other_charges_basis)
    input_amount = _amount(
        input_bound, _rate("cache_write", "long"), processing_multiplier
    )
    output_amount = _amount(
        output_bound, _rate("output", "long"), processing_multiplier
    )
    token_bound = input_amount + output_amount
    total_bound = (
        token_bound + other_charges_upper_bound_usd
        if other_charges_upper_bound_usd is not None
        else None
    )
    return {
        "provider": _SNAPSHOT["provider"],
        "model": model,
        "service_tier": service_tier,
        "processing_mode": processing_mode,
        "currency": _SNAPSHOT["currency"],
        "price_revision": PRICE_REVISION,
        "price_sources": tuple(_SNAPSHOT["source_urls"]),
        "basis": "long_context_all_input_at_cache_write_rate",
        "input_tokens_upper_bound": input_bound,
        "max_output_tokens": output_bound,
        "input_reservation_usd": input_amount,
        "output_reservation_usd": output_amount,
        "official_model_token_reservation_usd": token_bound,
        "other_charges_upper_bound_usd": other_charges_upper_bound_usd,
        "other_charges_basis": other_charges_basis,
        "reservation_upper_bound_usd": total_bound,
        "supplier_invoice_amount_usd": None,
        "unknown_reasons": (
            ("other_applicable_charges_unverified",)
            if other_charges_upper_bound_usd is None
            else ()
        ),
    }
