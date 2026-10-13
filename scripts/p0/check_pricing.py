"""Focused checks for the official model price snapshot and calculator."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.model_pricing import (
    PricingInputError,
    calculate_official_usage_cost,
    calculate_reservation_upper_bound,
)


def _expect_rejected(action: Callable[[], object]) -> None:
    try:
        action()
    except PricingInputError:
        return
    raise AssertionError("invalid pricing input was accepted")


def main() -> int:
    short = calculate_official_usage_cost(
        {
            "input_tokens": 272000,
            "cached_input_tokens": 32000,
            "cache_write_tokens": 50000,
            "output_tokens": 1000,
        },
        model="gpt-6-luna",
        service_tier="standard",
        processing_mode="global",
        other_charges_usd=Decimal("0"),
        other_charges_basis="fixed request has no separately billed provider tools",
    )
    assert short["context_class"] == "short"
    assert short["uncached_input_tokens"] == 190000
    assert short["official_model_token_amount_usd"] == Decimal("0.02607")
    assert short["official_estimated_total_usd"] == Decimal("0.02607")
    assert short["supplier_invoice_amount_usd"] is None

    long = calculate_official_usage_cost(
        {
            "input_tokens": 272001,
            "input_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 0,
            },
            "output_tokens": 1,
        },
        model="gpt-6-luna",
        service_tier="standard",
        processing_mode="global",
        other_charges_usd=Decimal("0"),
        other_charges_basis="fixed request has no separately billed provider tools",
    )
    assert long["context_class"] == "long"
    assert long["official_estimated_total_usd"] == Decimal("0.05440095")

    incomplete = calculate_official_usage_cost(
        {
            "input_tokens": 10,
            "cached_input_tokens": 2,
            "cache_write_tokens": None,
            "output_tokens": 3,
        },
        model="gpt-6-luna",
        service_tier="standard",
        processing_mode="global",
        other_charges_usd=Decimal("0"),
        other_charges_basis="no separately billed provider tools",
    )
    assert incomplete["official_model_token_amount_usd"] is None
    assert incomplete["official_estimated_total_usd"] is None
    assert incomplete["uncached_input_tokens"] is None
    assert incomplete["components"]["cached_input"]["amount_usd"] == Decimal(
        "0.00000002"
    )

    unknown_other_charges = calculate_official_usage_cost(
        {
            "input_tokens": 4,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 2,
        },
        model="gpt-6-luna",
        service_tier="standard",
        processing_mode="global",
        other_charges_usd=None,
        other_charges_basis=None,
    )
    assert unknown_other_charges["official_model_token_amount_usd"] is not None
    assert unknown_other_charges["official_estimated_total_usd"] is None

    reserve = calculate_reservation_upper_bound(
        model="gpt-6-luna",
        service_tier="standard",
        processing_mode="global",
        input_tokens_upper_bound=100000,
        max_output_tokens=800,
        other_charges_upper_bound_usd=Decimal("0"),
        other_charges_basis="no separately billed provider tools",
    )
    assert reserve["basis"] == "long_context_all_input_at_cache_write_rate"
    assert reserve["reservation_upper_bound_usd"] == Decimal("0.0256")

    _expect_rejected(
        lambda: calculate_official_usage_cost(
            {"input_tokens": True},
            model="gpt-6-luna",
            service_tier="standard",
            processing_mode="global",
            other_charges_usd=None,
            other_charges_basis=None,
        )
    )
    _expect_rejected(
        lambda: calculate_official_usage_cost(
            {"input_tokens": -1},
            model="gpt-6-luna",
            service_tier="standard",
            processing_mode="global",
            other_charges_usd=None,
            other_charges_basis=None,
        )
    )
    _expect_rejected(
        lambda: calculate_official_usage_cost(
            {
                "input_tokens": 2,
                "cached_input_tokens": 2,
                "cache_write_tokens": 1,
                "output_tokens": 1,
            },
            model="gpt-6-luna",
            service_tier="standard",
            processing_mode="global",
            other_charges_usd=None,
            other_charges_basis=None,
        )
    )
    _expect_rejected(
        lambda: calculate_official_usage_cost(
            {},
            model="gpt-6-luna",
            service_tier="fast",
            processing_mode="global",
            other_charges_usd=None,
            other_charges_basis=None,
        )
    )
    print("pricing_check=passed cases=5 invalid_inputs=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
