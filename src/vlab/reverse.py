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

import math
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


class GrowthOutOfRange(ValuationError):
    """No growth in the bracket reproduces the price; ``side`` says which way it lies.

    ``side`` is "above" or "below" and ``bound`` is the bracket edge the implied first-year
    growth lies beyond. A caller can then state the finding ("the price implies more than
    ...") instead of only refusing; the message is unchanged for those that just report it.
    """

    def __init__(self, message: str, *, side: str, bound: float) -> None:
        super().__init__(message)
        self.side = side
        self.bound = bound


def _solve(field: str, bracket: tuple[float, float], drivers: Drivers,
           assumptions: Assumptions, price: float) -> float:
    low, high = bracket

    def gap(candidate: float) -> float:
        return value(drivers, replace(assumptions, **{field: candidate})).value_per_share - price

    gap_low, gap_high = gap(low), gap(high)
    if not (math.isfinite(gap_low) and math.isfinite(gap_high)):
        # A NaN passes the same-sign check below (nan * x > 0 is False) and brentq would raise
        # a bare ValueError, which callers mapping ValuationError to "unavailable" miss.
        raise ValuationError(
            f"the model value is not finite at the edges of the {field.replace('_', ' ')} "
            f"bracket [{low}, {high}]; an input to the valuation is missing or degenerate"
        )
    if gap_low * gap_high > 0.0:
        # Both ends sit on the same side of the price. Value normally rises with growth, so a
        # price above both lies beyond the ceiling; if it falls with growth, the reverse.
        price_is_higher = gap_low < 0.0
        beyond_ceiling = price_is_higher == (gap_high >= gap_low)
        raise GrowthOutOfRange(
            f"no {field.replace('_', ' ')} in [{low}, {high}] reproduces a price of "
            f"{price:.2f}: the bracket spans values per share of "
            f"{gap_low + price:.2f} to {gap_high + price:.2f}",
            side="above" if beyond_ceiling else "below",
            bound=high if beyond_ceiling else low,
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
