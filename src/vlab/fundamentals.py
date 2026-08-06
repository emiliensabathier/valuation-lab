"""Normalized operating drivers, derived from the reported statements.

Every ratio is a median across the reported years rather than the latest value. That is what
makes a company in a bad year valuable at all: extrapolating a trough produces an absurd
number, and extrapolating a peak produces a flattering one. The normalization is a stated
assumption, surfaced in the report and pushed through the sensitivity grid — not a quiet
smoothing.
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


def _median_ratio(numerator: pd.Series, denominator: pd.Series) -> float:
    return float(np.median((numerator / denominator).dropna().to_numpy()))


def drivers_from(statements: Statements, ticker: str) -> Drivers:
    """Normalize one company's statements into the drivers the model consumes."""
    income, cashflow, balance = statements.income, statements.cashflow, statements.balance

    revenue = require(income, "Total Revenue", ticker)
    ebit = require(income, "EBIT", ticker)
    pretax = require(income, "Pretax Income", ticker)
    tax = require(income, "Tax Provision", ticker)

    capex = require(cashflow, "Capital Expenditure", ticker)
    depreciation = require(cashflow, "Depreciation And Amortization", ticker)
    working_capital = require(cashflow, "Change In Working Capital", ticker)

    debt = require(balance, "Total Debt", ticker)
    cash = require(balance, "Cash Cash Equivalents And Short Term Investments", ticker)
    minorities = require(balance, "Minority Interest", ticker)
    shares = require(balance, "Ordinary Shares Number", ticker)

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

    return Drivers(
        revenue=float(revenue.iloc[0]),
        revenue_growth=float(np.median(growth.to_numpy())),
        ebit_margin=margin,
        tax_rate=_median_ratio(tax, pretax),
        capex_ratio=_median_ratio(capex, revenue),
        da_ratio=_median_ratio(depreciation, revenue),
        nwc_ratio=_median_ratio(working_capital, revenue),
        net_debt=float(debt.iloc[0] - cash.iloc[0]),
        minority_interest=float(minorities.iloc[0]),
        shares=float(shares.iloc[0]),
    )
