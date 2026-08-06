"""The reverse discounted cash flow.

A forward DCF produces a target price that the reader is invited to argue with, and the
argument always lands on the same spot: the terminal growth rate. Inverting the model moves
the conversation. Fix the observed price, solve for the assumption that reproduces it, and
the output is no longer a claim about what a company is worth but a statement about what the
market already believes.

Both functions call ``dcf.value`` unchanged. Nothing here reimplements a valuation, which is
what the round-trip test in tests/test_reverse.py exists to keep true.
"""

from __future__ import annotations

from dataclasses import replace

from scipy.optimize import brentq

from vlab.dcf import Assumptions, value
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers

# Plausibility limits, not safety rails. A price that implies growth outside these bounds is
# telling you something, and the model says so rather than pinning the answer to an edge.
GROWTH_BRACKET = (-0.05, 0.25)
TERMINAL_BRACKET = (-0.01, 0.05)

TOLERANCE = 1e-10


def _solve(field: str, bracket: tuple[float, float], drivers: Drivers,
           assumptions: Assumptions, price: float) -> float:
    low, high = bracket

    def gap(candidate: float) -> float:
        return value(drivers, replace(assumptions, **{field: candidate})).value_per_share - price

    gap_low, gap_high = gap(low), gap(high)
    if gap_low * gap_high > 0.0:
        raise ValuationError(
            f"no {field.replace('_', ' ')} in [{low}, {high}] reproduces a price of "
            f"{price:.2f}: the bracket spans values per share of "
            f"{gap_low + price:.2f} to {gap_high + price:.2f}"
        )

    return float(brentq(gap, low, high, xtol=TOLERANCE))


def implied_revenue_growth(drivers: Drivers, assumptions: Assumptions, price: float) -> float:
    """The explicit-period revenue growth the market price implies, all else held normal."""
    return _solve("revenue_growth", GROWTH_BRACKET, drivers, assumptions, price)


def implied_terminal_growth(drivers: Drivers, assumptions: Assumptions, price: float) -> float:
    """The perpetual growth rate the market price implies, all else held normal."""
    return _solve("terminal_growth", TERMINAL_BRACKET, drivers, assumptions, price)
