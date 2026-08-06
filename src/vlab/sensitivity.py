"""Two-dimensional sensitivity grids.

A single valuation is a point estimate presented with more confidence than it deserves. The
grid shows how far it moves under assumptions a reader might reasonably prefer, which is the
honest way to present a number that depends on them.

Infeasible combinations are left empty rather than filled. A blank cell where WACC sits below
the terminal growth rate says "this pair has no meaning"; a number there would say something
false.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from vlab.dcf import Assumptions, value
from vlab.errors import ValuationError
from vlab.fundamentals import Drivers


def grid(
    drivers: Drivers,
    assumptions: Assumptions,
    *,
    row_field: str,
    row_values: list[float],
    column_field: str,
    column_values: list[float],
) -> pd.DataFrame:
    """Value per share across a mesh of two assumptions, holding everything else fixed."""
    table = pd.DataFrame(index=row_values, columns=column_values, dtype=float)

    for row in row_values:
        for column in column_values:
            candidate = replace(assumptions, **{row_field: row, column_field: column})
            try:
                table.loc[row, column] = value(drivers, candidate).value_per_share
            except ValuationError:
                table.loc[row, column] = np.nan

    return table


def default_wacc_terminal_grid(drivers: Drivers, assumptions: Assumptions) -> pd.DataFrame:
    """The grid an analyst expects: discount rate against perpetual growth.

    This one varies what the analyst assumes about the *market*.
    """
    waccs = [round(assumptions.wacc + step, 4) for step in (-0.02, -0.01, 0.0, 0.01, 0.02)]
    growths = [
        round(assumptions.terminal_growth + step, 4)
        for step in (-0.01, -0.005, 0.0, 0.005, 0.01)
    ]
    return grid(
        drivers, assumptions,
        row_field="wacc", row_values=waccs,
        column_field="terminal_growth", column_values=growths,
    )


def default_margin_growth_grid(drivers: Drivers, assumptions: Assumptions) -> pd.DataFrame:
    """Operating margin against revenue growth.

    This one varies what the analyst assumes about the *business*. Shown next to the grid
    above, it answers a question the first cannot: is this valuation fragile because of the
    discount rate, or because of the company?
    """
    margins = [
        round(assumptions.ebit_margin + step, 4) for step in (-0.04, -0.02, 0.0, 0.02, 0.04)
    ]
    growths = [
        round(assumptions.revenue_growth + step, 4)
        for step in (-0.04, -0.02, 0.0, 0.02, 0.04)
    ]
    return grid(
        drivers, assumptions,
        row_field="ebit_margin", row_values=margins,
        column_field="revenue_growth", column_values=growths,
    )
