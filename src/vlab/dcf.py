"""The discounted cash flow engine.

``value`` is the only place in this package where a valuation is computed. The forward DCF
calls it once, the reverse DCF root-finds over it, and the sensitivity grid sweeps it. There
is therefore no second model that could drift out of agreement with the first, and the
round-trip test in tests/test_reverse.py turns that from a claim into a check.

Free cash flow to the firm, so that four companies with different leverage stay comparable:

    FCFF = EBIT x (1 - tax) + D&A + capex + change in working capital

The last two terms arrive negative when they consume cash, exactly as reported, so the sum is
additive and there is no sign to flip.
"""

from __future__ import annotations

from dataclasses import dataclass

from vlab.errors import ValuationError
from vlab.fundamentals import Drivers


@dataclass(frozen=True)
class Assumptions:
    """What the analyst supplies. Everything else comes from the reported statements."""

    revenue_growth: float
    ebit_margin: float
    terminal_growth: float
    wacc: float
    years: int = 5


@dataclass(frozen=True)
class Valuation:
    """A valuation and the pieces a reader needs to judge it."""

    enterprise_value: float
    equity_value: float
    value_per_share: float
    pv_explicit: float
    pv_terminal: float
    terminal_share: float


def assumptions_from(drivers: Drivers, wacc: float, terminal_growth: float) -> Assumptions:
    """Start from the company's own normalized history, then let the caller vary it."""
    return Assumptions(
        revenue_growth=drivers.revenue_growth,
        ebit_margin=drivers.ebit_margin,
        terminal_growth=terminal_growth,
        wacc=wacc,
    )


def growth_path(assumptions: Assumptions) -> list[float]:
    """Growth for each explicit year, fading linearly to the terminal rate.

    The first year grows at the company's normalized rate and the last explicit year
    grows at the terminal rate, so the switch into the Gordon formula is continuous.

    Without the fade the model asked a business to reverse a five-year trend in a single
    year: Kering compounded its own -13.03% five times and then jumped to +2% overnight,
    Hermes did the same at +12.98%. Neither is a forecast anyone would defend out loud,
    and the discontinuity did most of its damage in the terminal value, which is where
    most of the valuation sits.

    Linear is a choice, not a result. A fade is one more assumption; what it is not is a
    cliff.
    """
    if assumptions.years < 2:
        return [assumptions.terminal_growth] * assumptions.years
    step = (assumptions.terminal_growth - assumptions.revenue_growth) / (
        assumptions.years - 1
    )
    return [assumptions.revenue_growth + step * year for year in range(assumptions.years)]


def _project(drivers: Drivers, assumptions: Assumptions) -> list[tuple[float, float]]:
    """Project (revenue, EBIT) for each explicit forecast year.

    The one place the growth compounding happens. Both ``free_cash_flows`` and
    ``terminal_exit_multiple`` read the final year off this same list, instead of one of
    them re-deriving the compounding with a second formula that could silently drift from
    the first.
    """
    projected: list[tuple[float, float]] = []
    revenue = drivers.revenue
    for growth in growth_path(assumptions):
        revenue *= 1.0 + growth
        ebit = revenue * assumptions.ebit_margin
        projected.append((revenue, ebit))
    return projected


def free_cash_flows(drivers: Drivers, assumptions: Assumptions) -> list[float]:
    """Project unlevered free cash flow over the explicit forecast period."""
    return [
        ebit * (1.0 - drivers.tax_rate)
        + revenue * drivers.da_ratio
        + revenue * drivers.capex_ratio
        + revenue * drivers.nwc_ratio
        for revenue, ebit in _project(drivers, assumptions)
    ]


def _require_feasible(assumptions: Assumptions) -> None:
    """Refuse a discount rate at or below the perpetual growth rate.

    Gordon divides by (wacc - g). At or below zero the formula returns a negative or
    infinite value, and publishing either would be worse than refusing. Shared by every
    entry point so the rule cannot drift between them.
    """
    if assumptions.wacc <= assumptions.terminal_growth:
        raise ValuationError(
            f"WACC ({assumptions.wacc:.4f}) is at or below the terminal growth rate "
            f"({assumptions.terminal_growth:.4f}); the Gordon formula has no meaning there"
        )


def value(drivers: Drivers, assumptions: Assumptions) -> Valuation:
    """Discount the projected cash flows and bridge to a value per share."""
    _require_feasible(assumptions)
    if drivers.shares <= 0.0:
        raise ValuationError("shares is zero or negative; cannot express a value per share")

    flows = free_cash_flows(drivers, assumptions)
    discount = 1.0 + assumptions.wacc

    pv_explicit = sum(flow / discount ** (year + 1) for year, flow in enumerate(flows))

    terminal_flow = flows[-1] * (1.0 + assumptions.terminal_growth)
    terminal_value = terminal_flow / (assumptions.wacc - assumptions.terminal_growth)
    pv_terminal = terminal_value / discount ** assumptions.years

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - drivers.net_debt - drivers.minority_interest

    return Valuation(
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=equity_value / drivers.shares,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_share=pv_terminal / enterprise_value,
    )


def terminal_exit_multiple(drivers: Drivers, assumptions: Assumptions) -> float:
    """The EV/EBIT multiple in the final forecast year implied by the Gordon terminal value.

    A perpetual growth rate is an assumption wearing a formula: 2% and 3% look equally
    reasonable written down, and value the business very differently. Restating the same
    number as the exit multiple it implies puts it on a scale readers already have intuitions
    about — an implied exit at 40x EBIT announces itself in a way that "3% forever" does not.
    """
    _require_feasible(assumptions)

    val = value(drivers, assumptions)
    undiscounted_terminal = val.pv_terminal * (1.0 + assumptions.wacc) ** assumptions.years

    _final_revenue, final_ebit = _project(drivers, assumptions)[-1]
    if final_ebit <= 0.0:
        raise ValuationError("final-year EBIT is not positive; the exit multiple is undefined")
    return undiscounted_terminal / final_ebit
