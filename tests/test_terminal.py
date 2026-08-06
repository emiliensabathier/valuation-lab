import pytest

from vlab.dcf import Assumptions, terminal_exit_multiple
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers


def _drivers() -> Drivers:
    return Drivers(
        revenue=1000.0, revenue_growth=0.0, ebit_margin=0.20, tax_rate=0.25,
        capex_ratio=0.0, da_ratio=0.0, nwc_ratio=0.0,
        net_debt=0.0, minority_interest=0.0, shares=100.0,
    )


def test_the_implied_exit_multiple_is_the_terminal_value_over_final_year_ebit() -> None:
    assumptions = Assumptions(0.0, 0.20, 0.02, 0.10, 5)

    # Flat revenue 1000, margin 20% -> EBIT 200 in the final year.
    # Terminal value = 150 * 1.02 / 0.08 = 1912.5, so the multiple is 1912.5 / 200.
    assert terminal_exit_multiple(_drivers(), assumptions) == pytest.approx(1912.5 / 200.0)


def test_a_more_generous_terminal_growth_implies_a_richer_exit() -> None:
    modest = terminal_exit_multiple(_drivers(), Assumptions(0.0, 0.20, 0.01, 0.10, 5))
    generous = terminal_exit_multiple(_drivers(), Assumptions(0.0, 0.20, 0.03, 0.10, 5))

    assert generous > modest


def test_with_growing_revenue_to_distinguish_year_5() -> None:
    drivers = Drivers(
        revenue=1000.0, revenue_growth=0.05, ebit_margin=0.20, tax_rate=0.25,
        capex_ratio=0.0, da_ratio=0.0, nwc_ratio=0.0,
        net_debt=0.0, minority_interest=0.0, shares=100.0,
    )
    assumptions = Assumptions(0.05, 0.20, 0.02, 0.10, 5)

    # Compute expected multiple from year 5
    year5_revenue = 1000.0 * (1.05 ** 5)
    year5_ebit = year5_revenue * 0.20
    year5_fcff = year5_ebit * (1 - 0.25)
    terminal_value = year5_fcff * 1.02 / (0.10 - 0.02)
    expected_multiple = terminal_value / year5_ebit

    # If flows[0] was used instead, the terminal value would be based on year 1 flows:
    # year1_fcff = 210 * 0.75 = 157.5, giving 157.5 * 1.02 / 0.08 = 2008.125
    # and 2008.125 / 255.26 = 7.87, which would be wrong.

    assert terminal_exit_multiple(drivers, assumptions) == pytest.approx(expected_multiple)


def test_negative_ebit_margin_raises() -> None:
    drivers = Drivers(
        revenue=1000.0, revenue_growth=0.0, ebit_margin=-0.05, tax_rate=0.25,
        capex_ratio=0.0, da_ratio=0.0, nwc_ratio=0.0,
        net_debt=0.0, minority_interest=0.0, shares=100.0,
    )
    assumptions = Assumptions(0.0, -0.05, 0.02, 0.10, 5)

    with pytest.raises(ValuationError, match="final-year EBIT is not positive"):
        terminal_exit_multiple(drivers, assumptions)
