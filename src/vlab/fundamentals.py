"""Normalized operating drivers, derived from the reported statements.

Every ratio but capex is a median across the reported years rather than the latest value.
That is what makes a company in a bad year valuable at all: extrapolating a trough produces
an absurd number, and extrapolating a peak produces a flattering one. The normalization is a
stated assumption, surfaced in the report and pushed through the sensitivity grid — not a
quiet smoothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from vlab.data.loader import Statements, require
from vlab.errors import ValuationError


@dataclass(frozen=True)
class Drivers:
    """Normalized inputs to the valuation, in the reporting currency.

    ``capex_ratio`` and ``nwc_ratio`` are negative when they consume cash, exactly as
    reported. The free cash flow formula is additive as a result, so there is no sign to flip
    and no opportunity to flip it wrongly.

    ``lease_ratio`` is lease payments over revenue, negative like capex. Under IFRS 16 rent
    disappears from operating costs: the reported EBIT is struck before it, D&A carries the
    depreciation of the leased stores, and the obligation sits in ``Total Debt``. This model
    puts leases back on a pre-IFRS 16 footing in one place, consistently: the lease payment is
    charged in the free cash flow, and the lease liability is excluded from ``net_debt`` and
    from the WACC's debt weight. Counting the liability as debt *and* charging future leases
    would count them twice; doing neither (the old treatment) made every future lease free.
    It defaults to zero only so hand-built test fixtures stay valid; ``drivers_from`` always
    measures it.

    ``fiscal_years`` records the reported period-end dates actually used for revenue, oldest
    first (e.g. ``("2022-12-31", ..., "2025-12-31")``), so the report can show a reader what
    period each driver was normalized over. It defaults to empty so the many hand-built
    ``Drivers(...)`` fixtures across the test suite, which predate this field, stay valid;
    only ``drivers_from`` populates it from real statements.

    ``capex_ratio`` is pooled over the window net of property disposals rather than a median
    (see ``_net_capex_ratio``).

    ``ebit_margins``, ``revenue_growths`` and ``capex_ratios`` are the yearly values behind
    the margin, growth and capex figures, oldest first (``capex_ratios`` gross of disposals),
    so the report can say what the normalization smooths over from the figures themselves
    rather than from prose written against one year's data.
    """

    revenue: float
    revenue_growth: float
    ebit_margin: float
    tax_rate: float
    capex_ratio: float
    da_ratio: float
    nwc_ratio: float
    net_debt: float
    minority_interest: float
    shares: float
    lease_ratio: float = 0.0
    fiscal_years: tuple[str, ...] = ()
    ebit_margins: tuple[float, ...] = ()
    revenue_growths: tuple[float, ...] = ()
    capex_ratios: tuple[float, ...] = ()


def _median_ratio(numerator: pd.Series, denominator: pd.Series) -> float:
    return float(np.median((numerator / denominator).dropna().to_numpy()))


def _lease_payment_ratio(
    leases: pd.Series,
    current_leases: pd.Series,
    debt: pd.Series,
    interest: pd.Series,
    revenue: pd.Series,
    tax_rate: float,
    ticker: str,
) -> float:
    """Median lease payment over revenue, rebuilt from the balance sheet and income statement.

    The data source reports no lease-payment line, and its cash-flow statement does not
    separate lease principal from bond repayments. A year's payment is then estimated as

        principal(t) = current portion of the lease liability at t-1 (due within the year)
        interest(t)  = reported interest(t) x lease liability(t) / total debt(t)

    with the interest taken after tax: the reported EBIT already excludes lease interest, so
    its tax shield is not in the tax charge either. The principal is what was scheduled, not
    necessarily what was paid, and the interest split assumes leases and borrowings cost the
    same rate. Returned negative, like capex, because it consumes cash.
    """
    frame = pd.concat(
        [leases, current_leases, debt, interest, revenue],
        axis=1,
        keys=["lease", "current", "debt", "interest", "revenue"],
        sort=False,
    ).dropna().sort_index()
    lease_interest = frame["interest"] * frame["lease"] / frame["debt"]
    payments = frame["current"].shift(1) + lease_interest * (1.0 - tax_rate)
    ratios = (payments / frame["revenue"]).dropna()
    if ratios.empty:
        raise ValuationError(
            f"{ticker}: fewer than two reported lease balances, cannot infer lease payments"
        )
    return -float(np.median(ratios.to_numpy()))


def _net_capex_ratio(
    capex: pd.Series, disposals: pd.Series, revenue: pd.Series, ticker: str
) -> float:
    """Capex net of property disposals, pooled over the window, as a share of revenue.

    Capex is lumpy where medians of margins are not: a house that buys its flagship buildings
    in one year and sells them back into a sale-and-leaseback the next shows two years of
    inflated gross capex and one disposal that a median of yearly gross ratios never sees.
    Summing capex and disposals over the window before dividing charges only the property the
    company kept. The rent it then pays on the buildings it sold is already in the lease
    payment, so nothing is counted twice.
    """
    frame = pd.concat(
        [capex, disposals, revenue], axis=1, keys=["capex", "disposals", "revenue"], sort=False
    ).dropna()
    if frame.empty:
        raise ValuationError(f"{ticker}: no year reports capex, disposals and revenue together")
    return float((frame["capex"].sum() + frame["disposals"].sum()) / frame["revenue"].sum())


def _history(numerator: pd.Series, denominator: pd.Series) -> tuple[float, ...]:
    """Yearly ratios, oldest first, over the years where both lines are reported."""
    return tuple(float(value) for value in (numerator / denominator).dropna().sort_index())


def drivers_from(statements: Statements, ticker: str) -> Drivers:
    """Normalize one company's statements into the drivers the model consumes."""
    income, cashflow, balance = statements.income, statements.cashflow, statements.balance

    revenue = require(income, "Total Revenue", ticker)
    ebit = require(income, "EBIT", ticker)
    pretax = require(income, "Pretax Income", ticker)
    tax = require(income, "Tax Provision", ticker)
    interest = require(income, "Interest Expense", ticker)

    capex = require(cashflow, "Capital Expenditure", ticker)
    disposals = require(cashflow, "Sale Of PPE", ticker)
    depreciation = require(cashflow, "Depreciation And Amortization", ticker)
    working_capital = require(cashflow, "Change In Working Capital", ticker)

    debt = require(balance, "Total Debt", ticker)
    cash = require(balance, "Cash Cash Equivalents And Short Term Investments", ticker)
    minorities = require(balance, "Minority Interest", ticker)
    shares = require(balance, "Ordinary Shares Number", ticker)
    leases = require(balance, "Capital Lease Obligations", ticker)
    current_leases = require(balance, "Current Capital Lease Obligation", ticker)

    # Statements arrive most-recent-first; reversing puts them in chronological order so a
    # year-on-year growth rate means what its name says.
    chronological = revenue.iloc[::-1]
    growth = chronological.pct_change().dropna()
    if growth.empty:
        raise ValuationError(f"{ticker}: fewer than two reported years, cannot infer growth")

    margin = _median_ratio(ebit, revenue)
    if margin <= 0.0:
        raise ValuationError(
            f"{ticker}: normalized EBIT margin is not positive ({margin:.3f}); this model "
            "does not value a structurally loss-making business"
        )

    # The reported years actually behind the normalization, oldest first -- one company's
    # statements can carry a column with no revenue in it (a fifth, unreported year), so this
    # is the real usable window, not the full width of the source frame.
    fiscal_years = tuple(sorted(str(period.date()) for period in revenue.dropna().index))

    tax_rate = _median_ratio(tax, pretax)

    return Drivers(
        revenue=float(revenue.iloc[0]),
        revenue_growth=float(np.median(growth.to_numpy())),
        ebit_margin=margin,
        tax_rate=tax_rate,
        capex_ratio=_net_capex_ratio(capex, disposals, revenue, ticker),
        da_ratio=_median_ratio(depreciation, revenue),
        nwc_ratio=_median_ratio(working_capital, revenue),
        net_debt=float(debt.iloc[0] - leases.iloc[0] - cash.iloc[0]),
        minority_interest=float(minorities.iloc[0]),
        shares=float(shares.iloc[0]),
        lease_ratio=_lease_payment_ratio(
            leases, current_leases, debt, interest, revenue, tax_rate, ticker
        ),
        fiscal_years=fiscal_years,
        ebit_margins=_history(ebit, revenue),
        revenue_growths=tuple(float(value) for value in growth),
        capex_ratios=_history(capex, revenue),
    )
