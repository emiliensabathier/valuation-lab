from dataclasses import replace

import pytest

from vlab.dcf import Assumptions, value
from vlab.fundamentals import Drivers
from vlab.sensitivity import default_margin_growth_grid, default_wacc_terminal_grid, grid


def _drivers() -> Drivers:
    return Drivers(
        revenue=1000.0, revenue_growth=0.05, ebit_margin=0.20, tax_rate=0.25,
        capex_ratio=-0.04, da_ratio=0.05, nwc_intensity=0.10,
        net_debt=200.0, minority_interest=0.0, shares=100.0,
    )


def _assumptions() -> Assumptions:
    return Assumptions(0.05, 0.20, 0.02, 0.09, 5)


def test_the_grid_has_the_requested_shape_and_labels() -> None:
    drivers, assumptions = _drivers(), _assumptions()
    table = grid(
        drivers, assumptions,
        row_field="wacc", row_values=[0.08, 0.09, 0.10],
        column_field="terminal_growth", column_values=[0.01, 0.02],
    )

    assert list(table.index) == [0.08, 0.09, 0.10]
    assert list(table.columns) == [0.01, 0.02]
    assert table.shape == (3, 2)
    # Verify an off-diagonal cell's value to detect transposed axes
    expected = value(drivers, replace(assumptions, wacc=0.08, terminal_growth=0.02)).value_per_share
    assert table.loc[0.08, 0.02] == pytest.approx(expected)


def test_each_cell_is_the_valuation_at_that_pair_of_assumptions() -> None:
    drivers, assumptions = _drivers(), _assumptions()

    table = grid(
        drivers, assumptions,
        row_field="wacc", row_values=[0.09],
        column_field="terminal_growth", column_values=[0.02],
    )

    assert table.loc[0.09, 0.02] == pytest.approx(value(drivers, assumptions).value_per_share)


def test_value_falls_as_the_discount_rate_rises() -> None:
    table = grid(
        _drivers(), _assumptions(),
        row_field="wacc", row_values=[0.08, 0.10, 0.12],
        column_field="terminal_growth", column_values=[0.02],
    )

    column = table[0.02]
    assert column.iloc[0] > column.iloc[1] > column.iloc[2]


def test_value_rises_with_the_terminal_growth_rate() -> None:
    table = grid(
        _drivers(), _assumptions(),
        row_field="wacc", row_values=[0.09],
        column_field="terminal_growth", column_values=[0.01, 0.02, 0.03],
    )

    row = table.loc[0.09]
    assert row.iloc[0] < row.iloc[1] < row.iloc[2]


def test_an_infeasible_cell_is_left_empty_rather_than_guessed() -> None:
    # WACC 2% against terminal growth 3% has no meaning; the cell reports nothing rather
    # than a number, and the surrounding cells still compute.
    table = grid(
        _drivers(), _assumptions(),
        row_field="wacc", row_values=[0.02, 0.09],
        column_field="terminal_growth", column_values=[0.03],
    )

    assert table.loc[0.02, 0.03] != table.loc[0.02, 0.03]  # NaN
    assert table.loc[0.09, 0.03] == table.loc[0.09, 0.03]


def test_the_default_grid_straddles_the_supplied_assumptions() -> None:
    table = default_wacc_terminal_grid(_drivers(), _assumptions())

    assert 0.09 in table.index
    assert 0.02 in table.columns


def test_the_margin_grid_varies_the_business_rather_than_the_model() -> None:
    table = default_margin_growth_grid(_drivers(), _assumptions())

    assert 0.20 in table.index
    assert 0.05 in table.columns


def test_a_richer_margin_is_worth_more_at_every_growth_rate() -> None:
    table = default_margin_growth_grid(_drivers(), _assumptions())

    for column in table.columns:
        values = table[column].dropna()
        assert values.is_monotonic_increasing, column


def test_the_centre_cells_equal_the_valuation_at_unrounded_assumptions() -> None:
    # Assumptions off the 4-decimal grid: the centre cell must be valued at the exact rates,
    # not at the rounded labels, or it disagrees with the headline value per share.
    drivers = replace(_drivers(), revenue_growth=0.051234567, ebit_margin=0.201234567)
    assumptions = Assumptions(0.051234567, 0.201234567, 0.02, 0.0912345678, 5)
    expected = value(drivers, assumptions).value_per_share

    wacc_table = default_wacc_terminal_grid(drivers, assumptions)
    margin_table = default_margin_growth_grid(drivers, assumptions)

    assert wacc_table.iloc[2, 2] == pytest.approx(expected, rel=1e-12)
    assert margin_table.iloc[2, 2] == pytest.approx(expected, rel=1e-12)
    assert list(wacc_table.index) == [0.0712, 0.0812, 0.0912, 0.1012, 0.1112]
    assert list(margin_table.columns) == [0.0112, 0.0312, 0.0512, 0.0712, 0.0912]
