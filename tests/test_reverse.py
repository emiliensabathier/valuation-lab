from dataclasses import replace

import pytest

from vlab.dcf import Assumptions, value
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers
from vlab.reverse import implied_revenue_growth, implied_terminal_growth


def _drivers() -> Drivers:
    return Drivers(
        revenue=1000.0, revenue_growth=0.05, ebit_margin=0.20, tax_rate=0.25,
        capex_ratio=-0.04, da_ratio=0.05, nwc_ratio=-0.01,
        net_debt=200.0, minority_interest=0.0, shares=100.0,
    )


def _assumptions(**overrides) -> Assumptions:
    base = dict(revenue_growth=0.05, ebit_margin=0.20, terminal_growth=0.02, wacc=0.09, years=5)
    base.update(overrides)
    return Assumptions(**base)


@pytest.mark.parametrize("growth", [-0.02, 0.0, 0.03, 0.08, 0.15])
def test_the_reverse_dcf_recovers_the_growth_the_forward_dcf_was_given(growth: float) -> None:
    # THE test of this repository. Value the business at a known growth rate, hand the
    # resulting price back to the reverse model, and require it to return that same rate.
    # It fails the moment anyone reimplements the valuation instead of calling into it.
    drivers = _drivers()
    forward = value(drivers, _assumptions(revenue_growth=growth))

    recovered = implied_revenue_growth(drivers, _assumptions(), forward.value_per_share)

    assert recovered == pytest.approx(growth, abs=1e-6)


@pytest.mark.parametrize("terminal", [0.0, 0.015, 0.03, 0.04])
def test_the_reverse_dcf_recovers_the_terminal_growth_too(terminal: float) -> None:
    drivers = _drivers()
    forward = value(drivers, _assumptions(terminal_growth=terminal))

    recovered = implied_terminal_growth(drivers, _assumptions(), forward.value_per_share)

    assert recovered == pytest.approx(terminal, abs=1e-6)


def test_a_price_beyond_the_bracket_raises_rather_than_clamping() -> None:
    # A price implying growth above the bracket is a finding, not an error to paper over.
    # Clamping to the boundary would return a presentable, wrong number.
    drivers = _drivers()
    absurd = value(drivers, _assumptions(revenue_growth=0.24)).value_per_share * 5

    with pytest.raises(ValuationError, match="no revenue growth"):
        implied_revenue_growth(drivers, _assumptions(), absurd)


def test_the_failure_message_reports_the_bracket_and_what_it_produced() -> None:
    drivers = _drivers()
    absurd = value(drivers, _assumptions(revenue_growth=0.24)).value_per_share * 5

    with pytest.raises(ValuationError) as excinfo:
        implied_revenue_growth(drivers, _assumptions(), absurd)

    message = str(excinfo.value)
    assert "-0.05" in message and "0.25" in message
    # The bracket alone is not enough: a message could name the right bounds while
    # reporting the wrong values reached at each end. Pin those down too.
    assert "14.05" in message and "52.88" in message


def test_the_round_trip_holds_when_held_assumptions_differ_from_drivers_and_defaults() -> None:
    # A solver that quietly rebuilds Assumptions from scratch instead of dataclasses.replace-ing
    # the caller's object would still pass every test above by coincidence: this fixture's
    # ebit_margin/wacc defaults happen to equal both the drivers' own normalized values and
    # any hardcoded fallback a rebuild might use. Move ebit_margin, wacc and terminal_growth
    # away from all of that to close the gap and force the caller's object to actually be held.
    drivers = _drivers()
    held = _assumptions(ebit_margin=0.28, wacc=0.11, terminal_growth=0.025)
    forward = value(drivers, replace(held, revenue_growth=0.07))

    recovered = implied_revenue_growth(drivers, held, forward.value_per_share)

    assert recovered == pytest.approx(0.07, abs=1e-6)


def test_a_higher_price_implies_a_higher_growth_rate() -> None:
    drivers = _drivers()
    low = value(drivers, _assumptions(revenue_growth=0.03)).value_per_share
    high = value(drivers, _assumptions(revenue_growth=0.09)).value_per_share

    assert implied_revenue_growth(drivers, _assumptions(), high) > implied_revenue_growth(
        drivers, _assumptions(), low
    )
