import pytest

from vlab.dcf import Assumptions, terminal_exit_multiple, value
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


def test_the_multiple_is_consistent_with_the_valuation_it_describes() -> None:
    drivers, assumptions = _drivers(), Assumptions(0.0, 0.20, 0.02, 0.10, 5)

    result = value(drivers, assumptions)
    undiscounted_terminal = result.pv_terminal * (1.0 + assumptions.wacc) ** assumptions.years
    final_ebit = 1000.0 * assumptions.ebit_margin

    assert terminal_exit_multiple(drivers, assumptions) == pytest.approx(
        undiscounted_terminal / final_ebit
    )
