import pytest

from vlab.dcf import Assumptions, assumptions_from, free_cash_flows, growth_path, value
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
        nwc_intensity=0.0,
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


def test_a_business_already_at_its_terminal_rate_produces_a_flat_cash_flow_stream() -> None:
    """The one case the fade leaves alone: nothing to fade towards."""
    flows = free_cash_flows(_drivers(), _assumptions(terminal_growth=0.0))

    # Revenue 1000, EBIT margin 20%, tax 25% -> 150 every year, no capex, no D&A, no NWC.
    assert flows == [pytest.approx(150.0)] * 5


def test_growth_fades_linearly_from_the_first_year_to_the_terminal_rate() -> None:
    path = growth_path(_assumptions(revenue_growth=0.10, terminal_growth=0.02))

    assert path[0] == pytest.approx(0.10)
    assert path[-1] == pytest.approx(0.02)
    assert path == pytest.approx([0.10, 0.08, 0.06, 0.04, 0.02])


def test_a_single_explicit_year_grows_at_the_terminal_rate_rather_than_dividing_by_zero() -> None:
    assert growth_path(_assumptions(revenue_growth=0.30, years=1)) == pytest.approx([0.02])


def test_growth_compounds_into_the_cash_flows_along_the_faded_path() -> None:
    """The trend is not held for five years, which is the whole point of the fade."""
    flows = free_cash_flows(_drivers(), _assumptions(revenue_growth=0.10))

    assert flows[0] == pytest.approx(1000.0 * 1.10 * 0.20 * 0.75)

    compounded = 1000.0
    for growth in (0.10, 0.08, 0.06, 0.04, 0.02):
        compounded *= 1.0 + growth
    assert flows[4] == pytest.approx(compounded * 0.20 * 0.75)
    # Held flat at 10% the final flow would be a fifth larger; that gap is the fade.
    assert flows[4] < 1000.0 * 1.10**5 * 0.20 * 0.75


def test_cash_consuming_ratios_reduce_the_flow_without_a_sign_flip() -> None:
    # capex_ratio arrives negative, as reported. The formula is additive.
    drivers = _drivers(capex_ratio=-0.05, da_ratio=0.03)
    flows = free_cash_flows(drivers, _assumptions())

    assert flows[0] == pytest.approx(150.0 + 30.0 - 50.0)


def test_working_capital_costs_nothing_when_revenue_does_not_grow() -> None:
    # The old level-based charge drained cash every year even at zero growth.
    flows = free_cash_flows(_drivers(nwc_intensity=0.25), _assumptions(terminal_growth=0.0))

    assert flows == pytest.approx([150.0] * 5)


def test_working_capital_is_charged_on_the_change_in_revenue() -> None:
    # 1000 -> 1100: the extra 100 of revenue ties up 25 of working capital.
    drivers = _drivers(nwc_intensity=0.25)
    assumptions = _assumptions(revenue_growth=0.10, terminal_growth=0.10)

    flows = free_cash_flows(drivers, assumptions)

    assert flows[0] == pytest.approx(1100.0 * 0.20 * 0.75 - 25.0)
    assert flows[1] == pytest.approx(1210.0 * 0.20 * 0.75 - 27.5)


def test_shrinking_revenue_releases_working_capital() -> None:
    drivers = _drivers(nwc_intensity=0.25)
    assumptions = _assumptions(revenue_growth=-0.10, terminal_growth=-0.10)

    flows = free_cash_flows(drivers, assumptions)

    assert flows[0] == pytest.approx(900.0 * 0.20 * 0.75 + 25.0)


def test_the_valuation_matches_the_closed_form_on_a_flat_perpetuity() -> None:
    # Five flows of 150 discounted at 10%, then a terminal value of 150 * 1.02 / 0.08,
    # itself discounted five years. Every term is computable by hand.
    #
    # Terminal growth is set to the normalized growth so the fade has nowhere to go and the
    # stream stays flat. With any other pair the flows are no longer hand-computable in one
    # line, which would make this test check the arithmetic against a copy of itself.
    drivers = _drivers()
    assumptions = _assumptions(terminal_growth=0.0)

    explicit = sum(150.0 / 1.10**year for year in range(1, 6))
    terminal = (150.0 / (0.10 - 0.0)) / 1.10**5

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


def test_assumptions_from_maps_fields_correctly_with_distinct_values() -> None:
    # Use mutually distinct values so any transposition is caught.
    drivers = _drivers(revenue_growth=0.05, ebit_margin=0.15)
    assumptions = assumptions_from(drivers, wacc=0.12, terminal_growth=0.03)

    # Fields from drivers
    assert assumptions.revenue_growth == 0.05
    assert assumptions.ebit_margin == 0.15
    # Fields from arguments
    assert assumptions.wacc == 0.12
    assert assumptions.terminal_growth == 0.03
    # Default
    assert assumptions.years == 5


def test_new_leases_reduce_the_flow_like_capex() -> None:
    # lease_ratio arrives negative, like capex: new right-of-use additions consume cash.
    flows = free_cash_flows(_drivers(lease_ratio=-0.04), _assumptions(terminal_growth=0.0))

    assert flows[0] == pytest.approx(150.0 - 40.0)


def test_a_valuation_lag_rolls_the_enterprise_value_forward_to_the_price_date() -> None:
    # Cash flows are dated from the fiscal year-end; the price is observed later. Moving the
    # valuation date forward by a fraction of a year brings every flow that much closer.
    base = value(_drivers(), _assumptions())
    rolled = value(_drivers(), _assumptions(valuation_lag=0.5))

    assert rolled.enterprise_value == pytest.approx(base.enterprise_value * 1.10**0.5)
    assert rolled.pv_terminal == pytest.approx(base.pv_terminal * 1.10**0.5)
    assert rolled.terminal_share == pytest.approx(base.terminal_share)


def test_a_negative_or_year_long_valuation_lag_raises() -> None:
    with pytest.raises(ValuationError, match="lag"):
        value(_drivers(), _assumptions(valuation_lag=-0.1))

    with pytest.raises(ValuationError, match="lag"):
        value(_drivers(), _assumptions(valuation_lag=1.0))


def test_assumptions_from_carries_the_valuation_lag() -> None:
    assumptions = assumptions_from(_drivers(), wacc=0.10, terminal_growth=0.02, valuation_lag=0.4)

    assert assumptions.valuation_lag == 0.4
