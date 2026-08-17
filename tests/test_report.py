"""Tests for the self-contained HTML report."""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
import pytest

from vlab.fundamentals import Drivers
from vlab.report.build import build_report
from vlab.report.charts import figure_to_svg, implied_growth_chart


@dataclass(frozen=True)
class _Result:
    name: str
    ticker: str
    reporting_currency: str
    trading_currency: str
    price: float
    value_per_share: float
    implied_growth: float
    implied_average_growth: float
    normalized_growth: float
    wacc: float
    beta: float
    cost_of_equity: float
    cost_of_debt: float
    equity_weight: float
    debt_weight: float
    terminal_share: float
    exit_multiple: float
    sensitivity: pd.DataFrame
    margin_sensitivity: pd.DataFrame
    drivers: Drivers


def _drivers(revenue_growth: float, ebit_margin: float, net_debt: float) -> Drivers:
    return Drivers(
        revenue=1_000_000_000.0, revenue_growth=revenue_growth, ebit_margin=ebit_margin,
        tax_rate=0.27, capex_ratio=-0.05, da_ratio=0.06, nwc_ratio=-0.01,
        net_debt=net_debt, minority_interest=0.0, shares=10_000_000.0,
        fiscal_years=("2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"),
    )


def _results() -> dict[str, _Result]:
    table = pd.DataFrame([[100.0, 110.0], [90.0, 95.0]], index=[0.08, 0.09], columns=[0.01, 0.02])
    margins = pd.DataFrame([[80.0, 95.0], [110.0, 130.0]], index=[0.18, 0.22], columns=[0.03, 0.07])
    return {
        "LVMH": _Result(
            "LVMH", "MC.PA", "EUR", "EUR", 481.45, 520.0, 0.041, 0.025, 0.062, 0.083, 0.84,
            cost_of_equity=0.095, cost_of_debt=0.030, equity_weight=0.85, debt_weight=0.15,
            terminal_share=0.71, exit_multiple=14.2, sensitivity=table, margin_sensitivity=margins,
            drivers=_drivers(0.062, 0.24, 5_000_000_000.0),
        ),
        "Hermes": _Result(
            "Hermes", "RMS.PA", "EUR", "EUR", 2100.0, 1600.0, 0.112, 0.066, 0.089, 0.079, 0.71,
            cost_of_equity=0.088, cost_of_debt=0.025, equity_weight=0.95, debt_weight=0.05,
            terminal_share=0.78, exit_multiple=26.9, sensitivity=table, margin_sensitivity=margins,
            drivers=_drivers(0.089, 0.40, -1_000_000_000.0),
        ),
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


def test_the_caveat_does_not_invent_a_growth_figure() -> None:
    # A draft leftover claimed "11% growth" as if it were a fact true of every company. No
    # company in the universe implies 11%, so the caveat must speak generally instead of
    # citing a number that belongs to none of them.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "11%" not in html
    assert "the implied growth" in html.lower()


def test_the_report_names_the_stated_assumptions() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert "equity risk premium" in html.lower()
    # _pct renders two decimals, so the constant 0.05 appears as 5.00%, not 5.0%.
    assert "5.00%" in html


def test_the_drivers_table_shows_what_each_valuation_is_built_from() -> None:
    # A reader cannot verify a single figure in the Summary table without seeing the inputs
    # that produced it: revenue, margin, tax rate, capex ratio, net debt and the fiscal years
    # they were normalized over.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "<h2>Drivers</h2>" in html
    assert "2022–2025" in html  # the fiscal-year window from _drivers()
    assert "1.00bn EUR" in html  # revenue, from _drivers()
    assert "24.00%" in html  # LVMH's EBIT margin
    assert "27.00%" in html  # the shared tax rate
    assert "-5.00%" in html  # the shared capex ratio
    assert "5.00bn EUR" in html  # LVMH's net debt
    assert "-1.00bn EUR" in html  # Hermes's net debt (net cash, sign preserved)


def test_the_drivers_table_shows_da_and_working_capital_ratios() -> None:
    # A reader cannot recompute free cash flow -- EBIT x (1 - tax) + D&A + capex + change in
    # working capital -- from the Drivers table without seeing all four of its non-EBIT
    # components; capex alone left two of the six pieces of the sum invisible.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "D&amp;A" in html
    assert "Change in WC" in html
    assert "6.00%" in html  # the shared D&A ratio from _drivers()
    assert "-1.00%" in html  # the shared change-in-working-capital ratio from _drivers()


def test_the_wacc_bridge_shows_the_cost_of_capital_components() -> None:
    # "WACC computed, not assumed" is a headline claim; a reader could not check it without
    # seeing cost of equity, cost of debt and the weights the WACC column was blended from.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "<h2>WACC bridge</h2>" in html
    assert "Cost of debt (pre-tax)" in html
    assert "Cost of debt (after-tax)" in html
    assert "9.50%" in html  # LVMH's cost of equity
    assert "3.00%" in html  # LVMH's pre-tax cost of debt
    assert "2.19%" in html  # LVMH's after-tax cost of debt: 3.00% x (1 - 27%)
    assert "85.00%" in html  # LVMH's equity weight
    assert "15.00%" in html  # LVMH's debt weight


def test_a_company_with_no_fiscal_years_recorded_shows_not_available() -> None:
    # Drivers.fiscal_years defaults to an empty tuple for every hand-built fixture across the
    # test suite that predates the field. The report must not crash or print an empty range
    # for one of them; it must say plainly that the window is unknown.
    results = _results()
    bare = replace(results["LVMH"].drivers, fiscal_years=())
    results["LVMH"] = replace(results["LVMH"], drivers=bare)

    html = build_report(results, generated_on="2026-08-06")

    lvmh_start = html.index("<h2>Drivers</h2>")
    assert "n/a" in html[lvmh_start:]


def test_kerings_valuation_gap_is_explained_when_kering_is_present() -> None:
    results = _results()
    kering_drivers = _drivers(-0.13, 0.18, 2_000_000_000.0)
    results["Kering"] = _Result(
        "Kering", "KER.PA", "EUR", "EUR", 289.75, 36.54, 0.0798, 0.0499, -0.13, 0.0731, 1.36,
        cost_of_equity=0.075, cost_of_debt=0.0343, equity_weight=0.662, debt_weight=0.338,
        terminal_share=0.71, exit_multiple=14.5, sensitivity=results["LVMH"].sensitivity,
        margin_sensitivity=results["LVMH"].margin_sensitivity, drivers=kering_drivers,
    )

    html = build_report(results, generated_on="2026-08-06")

    assert "Why Kering values so far below its price" in html
    # 1 - 36.54 / 289.75 = 0.8739..., rounded to the nearest percent.
    assert "87%" in html


def test_no_kering_note_when_kering_is_not_in_the_results() -> None:
    html = build_report(_results(), generated_on="2026-08-06")

    assert "Why Kering" not in html


def test_the_sensitivity_grid_corner_is_labeled_with_its_currency() -> None:
    # No grid carried a currency label at all, which is how a EUR grid sitting under a CHF
    # summary row went unnoticed. Both companies here trade in EUR, so the label must say so.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "WACC \\ terminal growth (EUR)" in html
    assert "EBIT margin \\ revenue growth (EUR)" in html


def test_the_report_carries_both_sensitivity_grids() -> None:
    # One grid varies the model, the other varies the business. A reader shown only the
    # first cannot tell which of the two the valuation is fragile to.
    html = build_report(_results(), generated_on="2026-08-06")

    assert "WACC \\ terminal growth" in html
    assert "EBIT margin \\ revenue growth" in html


def test_an_empty_result_set_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_report({}, generated_on="2026-08-06")


def test_a_company_failure_is_rendered_visibly_with_its_reason() -> None:
    # IMPORTANT bug: pipeline.run() had no per-company error isolation, so one company's
    # ValuationError took down the whole report. Once isolated, the failure must not vanish
    # silently either -- a reader has to see three valuations and a named, explained refusal.
    from vlab.pipeline import CompanyFailure

    failures = [
        CompanyFailure(
            "Kering", "KER.PA",
            "no revenue growth in [-0.05, 0.25] reproduces a price of 289.75",
        )
    ]

    html = build_report(_results(), failures, generated_on="2026-08-06")

    assert "Kering" in html
    assert "KER.PA" in html
    assert "no revenue growth" in html


def test_failures_alone_with_no_valued_companies_still_render_a_page() -> None:
    from vlab.pipeline import CompanyFailure

    failures = [CompanyFailure("Kering", "KER.PA", "some reason")]

    html = build_report({}, failures, generated_on="2026-08-06")

    assert html.startswith("<!doctype html>")
    assert "Kering" in html


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
    results["LVMH"] = replace(results["LVMH"], sensitivity=nan_table)

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
