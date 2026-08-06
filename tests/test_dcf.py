import pytest

from vlab.dcf import Assumptions, free_cash_flows, value
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers


def _drivers(**overrides) -> Drivers:
    base = dict(
        revenue=1000.0,
        revenue_growth=0.0,
        ebit_margin=0.20,
        tax_rate=0.25,
        capex_ratio=0.0,
        da_ratio=0.0,
        nwc_ratio=0.0,
        net_debt=0.0,
        minority_interest=0.0,
        shares=100.0,
    )
    base.update(overrides)
    return Drivers(**base)


def _assumptions(**overrides) -> Assumptions:
    base = dict(revenue_growth=0.0, ebit_margin=0.20, terminal_growth=0.02, wacc=0.10, years=5)
    base.update(overrides)
    return Assumptions(**base)


def test_a_flat_business_produces_a_flat_cash_flow_stream() -> None:
    flows = free_cash_flows(_drivers(), _assumptions())

    # Revenue 1000, EBIT margin 20%, tax 25% -> 150 every year, no capex, no D&A, no NWC.
    assert flows == [pytest.approx(150.0)] * 5


def test_growth_compounds_into_the_cash_flows() -> None:
    flows = free_cash_flows(_drivers(), _assumptions(revenue_growth=0.10))

    assert flows[0] == pytest.approx(1000.0 * 1.10 * 0.20 * 0.75)
    assert flows[4] == pytest.approx(1000.0 * 1.10**5 * 0.20 * 0.75)


def test_cash_consuming_ratios_reduce_the_flow_without_a_sign_flip() -> None:
    # capex_ratio and nwc_ratio arrive negative, as reported. The formula is additive.
    drivers = _drivers(capex_ratio=-0.05, da_ratio=0.03, nwc_ratio=-0.01)
    flows = free_cash_flows(drivers, _assumptions())

    assert flows[0] == pytest.approx(150.0 + 30.0 - 50.0 - 10.0)


def test_the_valuation_matches_the_closed_form_on_a_flat_perpetuity() -> None:
    # Five flows of 150 discounted at 10%, then a terminal value of 150 * 1.02 / 0.08,
    # itself discounted five years. Every term is computable by hand.
    drivers, assumptions = _drivers(), _assumptions()

    explicit = sum(150.0 / 1.10**year for year in range(1, 6))
    terminal = (150.0 * 1.02 / (0.10 - 0.02)) / 1.10**5

    result = value(drivers, assumptions)

    assert result.pv_explicit == pytest.approx(explicit)
    assert result.pv_terminal == pytest.approx(terminal)
    assert result.enterprise_value == pytest.approx(explicit + terminal)


def test_net_debt_and_minorities_bridge_to_the_equity_value() -> None:
    result = value(_drivers(net_debt=200.0, minority_interest=50.0), _assumptions())

    assert result.equity_value == pytest.approx(result.enterprise_value - 250.0)
    assert result.value_per_share == pytest.approx(result.equity_value / 100.0)


def test_the_terminal_share_reports_how_much_of_the_value_is_beyond_the_forecast() -> None:
    result = value(_drivers(), _assumptions())

    assert result.terminal_share == pytest.approx(result.pv_terminal / result.enterprise_value)
    assert 0.0 < result.terminal_share < 1.0


def test_a_wacc_at_or_below_the_terminal_growth_raises() -> None:
    # Gordon divides by (wacc - g). At or below zero the formula returns a negative or
    # infinite value; publishing either would be worse than refusing.
    with pytest.raises(ValuationError, match="terminal growth"):
        value(_drivers(), _assumptions(wacc=0.02, terminal_growth=0.02))

    with pytest.raises(ValuationError, match="terminal growth"):
        value(_drivers(), _assumptions(wacc=0.01, terminal_growth=0.03))


def test_zero_shares_raises_rather_than_dividing() -> None:
    with pytest.raises(ValuationError, match="shares"):
        value(_drivers(shares=0.0), _assumptions())
