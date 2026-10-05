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

from vlab.dcf import Assumptions, growth_path, value
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers

# Plausibility limits, not safety rails. A price that implies growth outside these bounds is
# telling you something, and the model says so rather than pinning the answer to an edge.
#
# The growth bracket is stated on the *first* explicit year, because that is the parameter
# the solver moves: growth fades linearly from it to the terminal rate, so a first year of
# 50% averages about 26% across the five explicit years. The bracket was (-0.05, 0.25) when
# growth was held flat; keeping that ceiling under a fade would have refused two of the four
# companies for being 25% at the front of a path that averages half of it, which is a limit
# on the arithmetic rather than on the plausibility.
GROWTH_BRACKET = (-0.20, 0.50)

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
    """The first-year revenue growth the market price implies, all else held normal.

    Growth fades from this rate to the terminal rate across the explicit period, so this is
    the front of a path rather than a rate sustained for five years. `implied_average_growth`
    restates it as the average over that path, which is the number worth comparing against a
    company's own history.
    """
    return _solve("revenue_growth", GROWTH_BRACKET, drivers, assumptions, price)


def implied_average_growth(drivers: Drivers, assumptions: Assumptions, price: float) -> float:
    """The implied path restated as its mean, so it is comparable with a historical rate."""
    first_year = implied_revenue_growth(drivers, assumptions, price)
    path = growth_path(replace(assumptions, revenue_growth=first_year))
    return sum(path) / len(path)
