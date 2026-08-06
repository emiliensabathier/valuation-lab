import numpy as np
import pandas as pd
import pytest

from vlab.errors import ValuationError
from vlab.wacc import EQUITY_RISK_PREMIUM, RISK_FREE, levered_beta


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
