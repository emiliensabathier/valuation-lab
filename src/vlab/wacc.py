"""Cost of capital.

The beta is recomputed from weekly returns against the Euro Stoxx 50 rather than taken from
the data provider's own field, whose index and estimation window are undocumented. A number
you cannot reproduce is a number you cannot defend.

The risk-free rate and the equity risk premium are assumptions, not measurements. They are
named constants here so the report can display them and the sensitivity grid can move them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from vlab.data.loader import Statements, require
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers

RISK_FREE = 0.03
EQUITY_RISK_PREMIUM = 0.05

MINIMUM_OVERLAP = 30


@dataclass(frozen=True)
class Wacc:
    """A weighted average cost of capital and the parts it was built from."""

    value: float
    cost_of_equity: float
    cost_of_debt: float
    beta: float
    equity_weight: float
    debt_weight: float


def levered_beta(stock: pd.Series, market: pd.Series) -> float:
    """Ordinary least squares beta of the stock against the market, on their common dates."""
    aligned = pd.concat([stock, market], axis=1, join="inner").dropna()
    if len(aligned) < MINIMUM_OVERLAP:
        raise ValuationError(
            f"beta needs at least {MINIMUM_OVERLAP} overlapping observations, got {len(aligned)}"
        )

    returns = aligned.pct_change().dropna()
    market_returns = returns.iloc[:, 1]
    variance = float(market_returns.var(ddof=1))
    if variance <= 0.0:
        raise ValuationError("market returns have zero variance; beta is undefined")
    return float(returns.iloc[:, 0].cov(market_returns) / variance)


def compute_wacc(
    statements: Statements,
    ticker: str,
    drivers: Drivers,
    market_cap: float,
    stock_prices: pd.Series,
    market_prices: pd.Series,
) -> Wacc:
    """Blend the cost of equity and the after-tax cost of debt at market and book weights."""
    beta = levered_beta(stock_prices, market_prices)
    cost_of_equity = RISK_FREE + beta * EQUITY_RISK_PREMIUM

    interest = require(statements.income, "Interest Expense", ticker)
    debt = require(statements.balance, "Total Debt", ticker)
    gross_debt = float(debt.iloc[0])
    if gross_debt <= 0.0:
        # An unlevered balance sheet is legitimate; the WACC is then simply the cost of
        # equity, and pretending to a cost of debt would invent a number.
        return Wacc(cost_of_equity, cost_of_equity, 0.0, beta, 1.0, 0.0)

    cost_of_debt = float(interest.iloc[0]) / gross_debt
    after_tax_debt = cost_of_debt * (1.0 - drivers.tax_rate)

    total = market_cap + gross_debt
    equity_weight = market_cap / total
    debt_weight = gross_debt / total

    return Wacc(
        value=equity_weight * cost_of_equity + debt_weight * after_tax_debt,
        cost_of_equity=cost_of_equity,
        cost_of_debt=cost_of_debt,
        beta=beta,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
    )
