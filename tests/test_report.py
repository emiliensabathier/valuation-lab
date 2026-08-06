"""Tests for the self-contained HTML report."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from vlab.report.build import build_report
from vlab.report.charts import figure_to_svg, implied_growth_chart


@dataclass(frozen=True)
class _Result:
    name: str
    ticker: str
    trading_currency: str
    price: float
    value_per_share: float
    implied_growth: float
    normalized_growth: float
    wacc: float
    beta: float
    terminal_share: float
    exit_multiple: float
    sensitivity: pd.DataFrame
    margin_sensitivity: pd.DataFrame


def _results() -> dict[str, _Result]:
    table = pd.DataFrame([[100.0, 110.0], [90.0, 95.0]], index=[0.08, 0.09], columns=[0.01, 0.02])
    margins = pd.DataFrame([[80.0, 95.0], [110.0, 130.0]], index=[0.18, 0.22], columns=[0.03, 0.07])
    return {
        "LVMH": _Result("LVMH", "MC.PA", "EUR", 481.45, 520.0, 0.041, 0.062, 0.083, 0.84,
                        0.71, 14.2, table, margins),
        "Hermes": _Result("Hermes", "RMS.PA", "EUR", 2100.0, 1600.0, 0.112, 0.089, 0.079,
                          0.71, 0.78, 26.9, table, margins),
    }


def test_figure_to_svg_produces_inline_markup() -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure()
    fig.add_subplot(111).plot([0, 1], [0, 1])

    svg = figure_to_svg(fig)

    assert svg.lstrip().startswith("<svg")
    assert "<?xml" not in svg


def test_the_implied_growth_chart_renders_for_every_company() -> None:
    svg = implied_growth_chart({"LVMH": 0.041, "Hermes": 0.112}, {"LVMH": 0.062, "Hermes": 0.089})

    assert svg.lstrip().startswith("<svg")


def test_the_report_is_one_document_with_no_external_resources() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert html.startswith("<!doctype html>")
    lowered = html.lower()
    for forbidden in (
        'src="http', "src='http", 'href="http', "href='http", 'src="//', "src='//",
        "url(http", "url('http", 'url("http', "<script", "<link", "@import", "@font-face", "cdn",
    ):
        assert forbidden not in lowered, forbidden


def test_the_report_shows_each_company_and_its_implied_growth() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert "LVMH" in html and "Hermes" in html
    assert "Implied growth" in html
    assert "4.10%" in html and "11.20%" in html


def test_each_companys_summary_row_puts_implied_growth_before_normalized_growth() -> None:
    # The summary table's header order is "Implied growth" then "Normalized growth". A
    # renderer that swapped the two values per row would still contain every percentage
    # somewhere in the document and pass a bare "in html" check; this asserts the two
    # figures land in that order within each company's own row, not just anywhere.
    html = build_report(_results(), generated_on="2026-08-06")

    lvmh_row = html[html.index("<td>LVMH</td>") : html.index("</tr>", html.index("<td>LVMH</td>"))]
    assert lvmh_row.index("4.10%") < lvmh_row.index("6.20%")

    hermes_row = html[
        html.index("<td>Hermes</td>") : html.index("</tr>", html.index("<td>Hermes</td>"))
    ]
    assert hermes_row.index("11.20%") < hermes_row.index("8.90%")


def test_the_report_states_what_a_reverse_dcf_does_not_prove() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert "does not say" in html


def test_the_report_names_the_stated_assumptions() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert "equity risk premium" in html.lower()
    # _pct renders two decimals, so the constant 0.05 appears as 5.00%, not 5.0%.
    assert "5.00%" in html


def test_the_report_carries_both_sensitivity_grids() -> None:
    # One grid varies the model, the other varies the business. A reader shown only the
    # first cannot tell which of the two the valuation is fragile to.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "WACC \\ terminal growth" in html
    assert "EBIT margin \\ revenue growth" in html


def test_an_empty_result_set_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_report({}, generated_on="2026-08-06")


def test_a_nan_cell_in_the_sensitivity_grid_is_shown_as_a_dash_not_a_number() -> None:
    # Task 8's own default WACC x terminal-growth axes never produce an infeasible cell,
    # so a renderer only exercised against that preset could still fill a NaN with "nan"
    # or a silent zero and every other test here would still pass. This grid forces one:
    # the second row's discount rate (0.02) sits at or below the terminal growth column
    # (0.02), which is exactly the infeasible case sensitivity.py encodes as NaN.
    results = _results()
    nan_table = pd.DataFrame(
        [[120.0, 130.0], [np.nan, 140.0]], index=[0.08, 0.02], columns=[0.01, 0.02]
    )
    results["LVMH"] = _Result(
        results["LVMH"].name, results["LVMH"].ticker, results["LVMH"].trading_currency,
        results["LVMH"].price, results["LVMH"].value_per_share, results["LVMH"].implied_growth,
        results["LVMH"].normalized_growth, results["LVMH"].wacc, results["LVMH"].beta,
        results["LVMH"].terminal_share, results["LVMH"].exit_multiple, nan_table,
        results["LVMH"].margin_sensitivity,
    )

    html = build_report(results, generated_on="2026-08-06")

    assert "nan" not in html.lower()
    # The dash for the infeasible cell must sit specifically in LVMH's sensitivity block
    # (between its <h3> heading and Hermes's), not merely anywhere in the document — a
    # renderer that filled the NaN with a dash under the wrong company would still pass a
    # bare substring check.
    lvmh_start = html.index("<h3>LVMH</h3>")
    hermes_start = html.index("<h3>Hermes</h3>")
    lvmh_block = html[lvmh_start:hermes_start]
    assert "—" in lvmh_block
