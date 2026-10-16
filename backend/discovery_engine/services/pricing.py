"""API cost estimation and spend tracking.

Design rule: an unconfigured rate yields a cost of ``None``, never 0.0. Reporting an
unpriced call as free is worse than reporting it as unknown, because a budget guard
built on silent zeros never fires.

Rates are per 1,000 requests, in USD, and are configuration rather than constants.
Provider pricing changes and varies by monthly volume tier; the defaults here are
deliberately set to the highest rate observed so an estimate is an upper bound. Set
the exact rates for your account from your billing console — see MVP_GRAB_VS_GOOGLE.md
section 7.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Provider

# Operation keys used across the cost layer.
GOOGLE_NEARBY = "google_nearby_pro"
GOOGLE_TEXT = "google_text_pro"
GOOGLE_DETAILS = "google_details_enterprise"
GRAB_SEARCH_TEXT = "grab_search_text"
HERE_BROWSE = "here_browse"

UNKNOWN_RATE = -1.0  # sentinel meaning "not configured"


@dataclass(frozen=True)
class CostLine:
    operation: str
    calls: int
    rate_per_1k: float | None
    cost_usd: float | None

    @property
    def priced(self) -> bool:
        return self.cost_usd is not None


def _rate(value: float) -> float | None:
    return None if value is None or value < 0 else value


def rate_for(operation: str, settings) -> float | None:
    """Look up the configured per-1,000 rate for an operation."""
    table = {
        GOOGLE_NEARBY: settings.rate_google_nearby_per_1k,
        GOOGLE_TEXT: settings.rate_google_text_per_1k,
        GOOGLE_DETAILS: settings.rate_google_details_per_1k,
        GRAB_SEARCH_TEXT: settings.rate_grab_search_text_per_1k,
        HERE_BROWSE: settings.rate_here_browse_per_1k,
    }
    return _rate(table.get(operation, UNKNOWN_RATE))


def cost_of(operation: str, calls: int, settings) -> CostLine:
    rate = rate_for(operation, settings)
    cost = None if rate is None else round(calls * rate / 1000.0, 4)
    return CostLine(operation=operation, calls=calls, rate_per_1k=rate, cost_usd=cost)


def summarise(call_counts: dict[str, int], settings) -> dict:
    """Turn {operation: calls} into a costed summary.

    ``cost_usd`` is the total of the priced lines only. ``unpriced_operations``
    lists what was left out, so a partial total can never be mistaken for a
    complete one.
    """
    lines = [cost_of(op, calls, settings) for op, calls in sorted(call_counts.items()) if calls]
    priced = [line for line in lines if line.priced]
    unpriced = [line.operation for line in lines if not line.priced]
    return {
        "total_calls": sum(line.calls for line in lines),
        "cost_usd": round(sum(line.cost_usd for line in priced), 4) if priced else None,
        "cost_is_complete": not unpriced,
        "unpriced_operations": unpriced,
        "lines": [
            {
                "operation": line.operation,
                "calls": line.calls,
                "rate_per_1k_usd": line.rate_per_1k,
                "cost_usd": line.cost_usd,
            }
            for line in lines
        ],
    }


def sweep_operation(provider: Provider) -> str:
    if provider == Provider.GOOGLE:
        return GOOGLE_NEARBY
    if provider == Provider.HERE:
        return HERE_BROWSE
    return GRAB_SEARCH_TEXT


def probe_operation(provider: Provider) -> str:
    if provider == Provider.GOOGLE:
        return GOOGLE_TEXT
    if provider == Provider.HERE:
        return HERE_BROWSE
    return GRAB_SEARCH_TEXT


def estimate_sweep(
    provider: Provider,
    tile_count: int,
    settings,
    saturation_allowance: float = 1.35,
) -> dict:
    """Pre-flight estimate for a sweep, before a single call is spent.

    ``saturation_allowance`` accounts for adaptive subdivision: a saturated tile is
    replaced by four smaller ones, so the real call count exceeds the initial tile
    count. 1.35 is a planning default, not a guarantee — a dense central-Jakarta AOI
    can subdivide considerably further. The hard per-run caps are what actually bound
    the spend.
    """
    if provider == Provider.GOOGLE:
        calls_per_tile = 1
        operation = GOOGLE_NEARBY
    elif provider == Provider.HERE:
        # One /browse call per top-level HERE category root per tile.
        from .taxonomy import HERE_SWEEP_ROOTS

        calls_per_tile = len(HERE_SWEEP_ROOTS)
        operation = HERE_BROWSE
    else:
        # Grab has no nearby search, so every tile is swept once per query term.
        from ..providers.grab import default_query_terms

        calls_per_tile = len(default_query_terms())
        operation = GRAB_SEARCH_TEXT

    base_calls = tile_count * calls_per_tile
    expected_calls = int(round(base_calls * saturation_allowance))

    low = summarise({operation: base_calls}, settings)
    expected = summarise({operation: expected_calls}, settings)
    cap = (
        settings.google_max_calls_per_run if provider == Provider.GOOGLE
        else settings.here_max_calls_per_run if provider == Provider.HERE
        else settings.grab_max_calls_per_run
    )
    at_cap = summarise({operation: cap}, settings)

    return {
        "provider": provider.value,
        "tiles": tile_count,
        "calls_per_tile": calls_per_tile,
        "calls_minimum": base_calls,
        "calls_expected": expected_calls,
        "calls_cap": cap,
        "cost_minimum_usd": low["cost_usd"],
        "cost_expected_usd": expected["cost_usd"],
        "cost_at_cap_usd": at_cap["cost_usd"],
        "cost_is_complete": expected["cost_is_complete"],
        "unpriced_operations": expected["unpriced_operations"],
        "rate_per_1k_usd": rate_for(operation, settings),
        "saturation_allowance": saturation_allowance,
        "note": (
            "Estimates assume the configured rates are correct for your monthly volume "
            "tier. The per-run call cap is the only hard bound on spend."
        ),
    }
