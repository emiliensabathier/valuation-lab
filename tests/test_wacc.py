import numpy as np
import pandas as pd
import pytest

from vlab.data.loader import Statements
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers
from vlab.wacc import EQUITY_RISK_PREMIUM, RISK_FREE, compute_wacc, levered_beta


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2021-01-01", periods=len(values), freq="W-FRI"))


def test_a_stock_that_tracks_the_market_has_a_beta_of_one() -> None:
    rng = np.random.default_rng(0)
    market = _series(list(100 * np.cumprod(1 + rng.normal(0.0, 0.02, 260))))

    assert levered_beta(market, market) == pytest.approx(1.0)


def test_a_stock_that_moves_twice_as_hard_has_a_beta_of_two() -> None:
    rng = np.random.default_rng(1)
    market_returns = rng.normal(0.0, 0.02, 260)
    market = _series(list(100 * np.cumprod(1 + market_returns)))
    stock = _series(list(100 * np.cumprod(1 + 2 * market_returns)))

    # Compounding makes the doubled series only approximately twice as sensitive.
    assert levered_beta(stock, market) == pytest.approx(2.0, rel=0.05)


def test_an_uncorrelated_stock_has_a_beta_near_zero() -> None:
    rng = np.random.default_rng(2)
    market = _series(list(100 * np.cumprod(1 + rng.normal(0.0, 0.02, 500))))
    stock = _series(list(100 * np.cumprod(1 + rng.normal(0.0, 0.02, 500))))

    assert abs(levered_beta(stock, market)) < 0.2


def test_beta_requires_overlapping_observations() -> None:
    stock = _series([1.0, 2.0, 3.0])
    market = pd.Series([1.0, 2.0], index=pd.bdate_range("2019-01-01", periods=2, freq="W-FRI"))

    with pytest.raises(ValuationError, match="overlap"):
        levered_beta(stock, market)


def test_the_stated_assumptions_are_the_ones_the_spec_fixed() -> None:
    assert RISK_FREE == 0.03
    assert EQUITY_RISK_PREMIUM == 0.05


def _wacc_statements(interest: float = 100.0, debt: float = 2000.0) -> Statements:
    periods = pd.DatetimeIndex(["2025-12-31", "2024-12-31"])
    return Statements(
        income=pd.DataFrame([[interest, interest]], index=["Interest Expense"], columns=periods),
        cashflow=pd.DataFrame(),
        balance=pd.DataFrame([[debt, debt]], index=["Total Debt"], columns=periods),
        info={},
    )


def _wacc_drivers(tax_rate: float = 0.25) -> Drivers:
    return Drivers(
        revenue=1000.0, revenue_growth=0.05, ebit_margin=0.20, tax_rate=tax_rate,
        capex_ratio=-0.04, da_ratio=0.05, nwc_ratio=-0.01,
        net_debt=0.0, minority_interest=0.0, shares=100.0,
    )


def _market() -> pd.Series:
    rng = np.random.default_rng(7)
    return _series(list(100 * np.cumprod(1 + rng.normal(0.0, 0.02, 260))))


def test_the_wacc_blends_capm_equity_with_after_tax_debt_at_market_and_book_weights() -> None:
    # Passing the market as its own stock fixes beta at 1.0, which makes every downstream
    # number hand-computable: cost of equity 0.03 + 1.0 * 0.05 = 0.08, cost of debt
    # 100 / 2000 = 0.05, weights 8000 and 2000 over 10000.
    market = _market()

    result = compute_wacc(_wacc_statements(), "TEST", _wacc_drivers(), 8000.0, market, market)

    assert result.beta == pytest.approx(1.0)
    assert result.cost_of_equity == pytest.approx(0.08)
    assert result.cost_of_debt == pytest.approx(0.05)
    assert result.equity_weight == pytest.approx(0.8)
    assert result.debt_weight == pytest.approx(0.2)
    assert result.value == pytest.approx(0.8 * 0.08 + 0.2 * 0.05 * 0.75)


def test_an_unlevered_balance_sheet_gives_a_wacc_equal_to_the_cost_of_equity() -> None:
    # This branch builds Wacc positionally, which is exactly where a field mix-up hides.
    # Asserting every field is what pins the mapping rather than trusting the argument order.
    market = _market()

    result = compute_wacc(
        _wacc_statements(debt=0.0), "TEST", _wacc_drivers(), 8000.0, market, market
    )

    assert result.value == pytest.approx(result.cost_of_equity)
    assert result.cost_of_equity == pytest.approx(0.08)
    assert result.cost_of_debt == 0.0
    assert result.beta == pytest.approx(1.0)
    assert result.equity_weight == 1.0
    assert result.debt_weight == 0.0


def test_a_negative_implied_cost_of_debt_raises() -> None:
    # Interest expense is reported positive by this source. A negative one means the sign
    # convention is not what the model assumes, and blending it would quietly lower the
    # WACC and raise every valuation.
    market = _market()

    with pytest.raises(ValuationError, match="negative cost of debt"):
        compute_wacc(
            _wacc_statements(interest=-100.0), "TEST", _wacc_drivers(), 8000.0, market, market
        )
