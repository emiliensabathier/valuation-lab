"""Assembly of the final HTML report.

Computes nothing: every number shown here is produced by the valuation modules.
"""

from __future__ import annotations

import html as html_escape

import pandas as pd

from vlab.report.charts import implied_growth_chart, value_bridge_chart
from vlab.wacc import EQUITY_RISK_PREMIUM, RISK_FREE

STYLE = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0 auto;
       max-width: 980px; padding: 2rem 1.25rem; color: #16181d; line-height: 1.5; }
h1 { font-size: 1.9rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.25rem; margin-top: 2.5rem; border-bottom: 1px solid #e3e5ea;
     padding-bottom: 0.35rem; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 0.45rem 0.6rem; border-bottom: 1px solid #eceef2; }
th:first-child, td:first-child { text-align: left; }
thead th { border-bottom: 2px solid #c9ccd4; }
.note { color: #5b6070; font-size: 0.9rem; }
.caveat { background: #f6f7f9; border-left: 3px solid #c9ccd4; padding: 0.75rem 1rem;
          margin: 1rem 0; }
svg { max-width: 100%; height: auto; }
"""


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _num(value: float) -> str:
    return f"{value:.2f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html_escape.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html_escape.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _summary_table(results) -> str:
    rows = []
    for result in results.values():
        rows.append([
            result.name,
            f"{result.price:.2f} {result.trading_currency}",
            f"{result.value_per_share:.2f} {result.trading_currency}",
            _pct(result.implied_growth),
            _pct(result.implied_average_growth),
            _pct(result.normalized_growth),
            _pct(result.wacc),
            _num(result.beta),
            _pct(result.terminal_share),
            f"{result.exit_multiple:.1f}x",
        ])
    return _table(
        ["Company", "Price", "Modelled value", "Implied growth, year 1",
         "Implied growth, 5y average", "Normalized growth",
         "WACC", "Beta", "Terminal share", "Implied exit"],
        rows,
    )


def _bn(value: float) -> str:
    """Format a large reporting-currency amount in billions, keeping the sign."""
    return f"{value / 1e9:.2f}bn"


def _year_range(fiscal_years: tuple[str, ...]) -> str:
    """The reported window as ``2022-2025``, from full period-end dates."""
    if not fiscal_years:
        return "n/a"
    return f"{fiscal_years[0][:4]}–{fiscal_years[-1][:4]}"


def _drivers_table(results) -> str:
    """The normalized inputs behind every valuation, not only its conclusion.

    A reader who cannot see revenue, margin, tax rate, the capex, D&A, lease-payment and
    working-capital ratios, and net debt -- plus the fiscal years they were normalized over --
    has no way to check a single figure in the summary table, only to trust it. Free cash flow
    is the plain sum of these ratios applied to revenue and EBIT:
    ``EBIT x (1 - tax) + D&A + capex + lease payments + change in working capital`` (see
    ``dcf.py``); the cash-consuming ratios are negative here, so a reader can reproduce a value
    per share from this row alone.
    """
    rows = []
    for result in results.values():
        drivers = result.drivers
        currency = result.reporting_currency
        rows.append([
            result.name,
            _year_range(drivers.fiscal_years),
            f"{_bn(drivers.revenue)} {currency}",
            _pct(drivers.ebit_margin),
            _pct(drivers.tax_rate),
            _pct(drivers.capex_ratio),
            _pct(drivers.da_ratio),
            _pct(drivers.lease_ratio),
            _pct(drivers.nwc_ratio),
            f"{_bn(drivers.net_debt)} {currency}",
        ])
    return _table(
        ["Company", "Fiscal years", "Revenue (latest)", "EBIT margin (normalized)",
         "Tax rate (normalized)", "Capex / revenue (normalized)",
         "D&A / revenue (normalized)", "Lease payments / revenue (normalized)",
         "Change in WC / revenue (normalized)",
         "Net debt (latest)"],
        rows,
    )


def _wacc_table(results) -> str:
    """The cost-of-capital bridge behind the WACC column in the Summary table.

    ``cost_of_debt`` is published **pre-tax**, exactly as ``wacc.Wacc`` carries it, alongside
    the after-tax figure actually blended into WACC -- so a reader applying the tax shield a
    second time is a choice they would have to make deliberately, not a trap the table sets for
    them. Weighting the two costs by ``equity_weight`` and ``debt_weight`` reproduces the WACC
    column above.
    """
    rows = []
    for result in results.values():
        after_tax_cost_of_debt = result.cost_of_debt * (1.0 - result.drivers.tax_rate)
        rows.append([
            result.name,
            _num(result.beta),
            _pct(result.cost_of_equity),
            _pct(result.cost_of_debt),
            _pct(after_tax_cost_of_debt),
            _pct(result.equity_weight),
            _pct(result.debt_weight),
            _pct(result.wacc),
        ])
    return _table(
        ["Company", "Beta", "Cost of equity", "Cost of debt (pre-tax)",
         "Cost of debt (after-tax)", "Equity weight", "Debt weight", "WACC"],
        rows,
    )


def _kering_collapse_note(results) -> str:
    """Explain Kering's valuation sitting far below its market price.

    Named specifically rather than phrased as a general warning, because it is a fact about
    one company's reported history, not a property of the method that would recur for any
    company shaped differently. The percentages are read off ``results`` here, the same
    values the summary table renders, so this explanation cannot drift from the figure it is
    explaining if the underlying data changes.
    """
    kering = results.get("Kering")
    if kering is None:
        return ""
    discount = 1.0 - kering.value_per_share / kering.price
    drivers = kering.drivers
    parts = [
        '<div class="caveat"><strong>Why Kering values so far below its price.</strong> '
        f"The model's {kering.value_per_share:.2f} {kering.trading_currency} sits about "
        f"{discount * 100:.0f}% below its {kering.price:.2f} {kering.trading_currency} market "
        f"price. Normalized over {_year_range(drivers.fiscal_years)}, Kering is valued at an "
        f"EBIT margin of {_pct(drivers.ebit_margin)} and a starting revenue growth of "
        f"{_pct(drivers.revenue_growth)}, both medians."
    ]
    if drivers.ebit_margins:
        latest = drivers.ebit_margins[-1]
        side = "above" if drivers.ebit_margin > latest else "below"
        parts.append(
            f" The yearly EBIT margin ran {_series(drivers.ebit_margins)}, so the median sits "
            f"{side} the latest year's {_pct(latest)}."
        )
    if drivers.revenue_growths:
        parts.append(f" Yearly revenue growth ran {_series(drivers.revenue_growths)}.")
    if drivers.capex_ratios:
        parts.append(
            f" Gross capex over revenue ran {_series(drivers.capex_ratios)}, years that "
            "include property purchases; pooled over the window net of property disposals, "
            f"the model charges {_pct(drivers.capex_ratio)}."
        )
    parts.append(
        " The modelled value is what those medians are worth if they persist; the market "
        "price is a bet that they do not.</div>"
    )
    return "".join(parts)


def _series(values: tuple[float, ...]) -> str:
    return ", ".join(_pct(value) for value in values)


def _lower_wacc_table(results) -> str:
    """The implied five-year average growth re-solved at a discount rate one and two points lower.

    The computed WACCs rest on raw betas and a 5% equity risk premium; a reader who thinks
    either is too high reads the implied growth at a lower rate here, rather than trusting the
    single discount rate the conclusion would otherwise lean on.
    """
    steps = sorted(
        {
            step
            for result in results.values()
            for step in result.implied_average_growth_at_lower_wacc
        }
    )
    rows = [
        [result.name, _pct(result.wacc), _pct(result.implied_average_growth)]
        + [
            _pct(result.implied_average_growth_at_lower_wacc[step])
            if step in result.implied_average_growth_at_lower_wacc
            else "—"
            for step in steps
        ]
        for result in results.values()
    ]
    headers = ["Company", "WACC", "Implied growth, 5y average"] + [
        f"At WACC − {step * 100:.0f}pt" for step in steps
    ]
    return _table(headers, rows)


def _bias_caveat() -> str:
    """The ways the modelled value leans low, so the gap to price overstates itself."""
    return (
        '<div class="caveat"><strong>Read the gap with the model&#39;s biases.</strong> The '
        "modelled value leans low on several counts, so the gap to price overstates what the "
        "market pays for beyond this model: "
        "working capital is projected as a share of the revenue <em>level</em>, not of its "
        "change, so it drains cash every year even at zero growth; cash flows are discounted "
        "at year-end, not mid-year; betas are raw regression betas, not shrunk toward one, "
        "which raises the cost of equity of any beta above one, and they are priced at a "
        f"{_pct(EQUITY_RISK_PREMIUM)} equity risk premium; capex, even net of disposals, still "
        "carries property the houses kept, not only replacement spending; and four-year "
        "medians anchor margins to a window that is a downturn for some houses. The table "
        "below re-solves the implied growth at a lower discount rate. Read together, the "
        "market prices more growth than this model credits &mdash; which is not the same as "
        "saying a share is mispriced.</div>"
    )


def _grid_table(table, corner: str) -> str:
    """One sensitivity grid. Infeasible cells render as a dash, never as a number."""
    headers = [corner] + [_pct(column) for column in table.columns]
    rows = [
        [_pct(index)]
        + [
            "—" if pd.isna(cell) else f"{cell:.0f}"
            for cell in table.loc[index]
        ]
        for index in table.index
    ]
    return _table(headers, rows)


def _sensitivity_section(results) -> str:
    blocks = []
    for result in results.values():
        currency = html_escape.escape(result.trading_currency)
        blocks.append(f"<h3>{html_escape.escape(result.name)}</h3>")
        blocks.append('<p class="note">Against the model:</p>')
        blocks.append(_grid_table(result.sensitivity, f"WACC \\ terminal growth ({currency})"))
        blocks.append('<p class="note">Against the business:</p>')
        blocks.append(
            _grid_table(
                result.margin_sensitivity, f"EBIT margin \\ revenue growth ({currency})"
            )
        )
    return "".join(blocks)


def _failures_section(failures) -> str:
    """A visible refusal for each company the model could not value.

    A company that fails is named here, with the reason, rather than being silently absent
    from the summary table -- three valuations and a stated refusal, not three valuations and
    a silence that looks like completeness.
    """
    items = "".join(
        f"<li><strong>{html_escape.escape(failure.name)}</strong> "
        f"({html_escape.escape(failure.ticker)}): {html_escape.escape(failure.reason)}</li>"
        for failure in failures
    )
    return (
        "<h2>Valuations that could not be produced</h2>"
        '<div class="caveat"><p class="note">The model refuses to publish a number it could '
        f"not defend, rather than guessing. Refused for {len(failures)} "
        f'{"company" if len(failures) == 1 else "companies"}:</p><ul>{items}</ul></div>'
    )


def build_report(results, failures=(), *, generated_on: str) -> str:
    """Render the whole report as one self-contained HTML document.

    ``failures`` lists the companies the pipeline could not value (see
    ``pipeline.CompanyFailure``); they are rendered as a visible, named refusal rather than
    a silent absence from the summary table.
    """
    if not results and not failures:
        raise ValueError("the report needs at least one company, valued or failed")

    sections = [
        "<h1>What the market is paying for growth</h1>",
        f'<p class="note">Four European luxury houses, valued on unlevered free cash flow '
        f"and then inverted against their own share prices. Generated on "
        f"{html_escape.escape(generated_on)}.</p>",
        '<div class="caveat"><strong>What this does not say.</strong> A reverse discounted '
        "cash flow does not say a share is expensive. It says what the market assumes. "
        "Judging whether the implied growth is plausible for a given house is an analyst's "
        "work, not a model's.</div>",
    ]

    if not results:
        sections.append(_failures_section(failures))
        body = "\n".join(sections)
        return (
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            "<title>What the market is paying for growth</title>\n"
            f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
        )

    # The averaged path, not the first year of it. Normalized growth is a single rate
    # across four reported years; putting a decaying path's opening rate next to it in a
    # bar chart would compare two different quantities and flatter every gap.
    implied = {result.name: result.implied_average_growth for result in results.values()}
    normalized = {result.name: result.normalized_growth for result in results.values()}
    prices = {
        result.name: (result.price, result.value_per_share) for result in results.values()
    }

    sections += [
        "<h2>Summary</h2>",
        _summary_table(results),
    ]
    sections += [
        _bias_caveat(),
        '<p class="note">Implied five-year average growth re-solved at a lower discount '
        "rate, everything else held:</p>",
        _lower_wacc_table(results),
    ]
    kering_note = _kering_collapse_note(results)
    if kering_note:
        sections.append(kering_note)
    if failures:
        sections.append(_failures_section(failures))
    sections += [
        "<h2>Drivers</h2>",
        '<p class="note">What each valuation is actually built from. Revenue and net debt '
        "are the latest reported fiscal year; EBIT margin, tax rate, and the D&amp;A, "
        "lease-payment and change-in-working-capital ratios are medians across the fiscal "
        "years listed. Capex is pooled over the same years net of property disposals, "
        "because property bought one year and sold back the next would otherwise be charged "
        "and never credited. "
        "Revenue growth is normalized the same way and shown in the Summary table above, not "
        "repeated here. Capex, lease payments and the change in working capital are negative "
        "exactly when they consume cash; D&amp;A is positive, added back as a non-cash "
        "expense. Free cash flow is the plain sum: EBIT &times; (1 &minus; tax) + D&amp;A + "
        "capex + lease payments + change in working capital. Leases are treated pre-IFRS 16: "
        "the lease payment (last year's current lease liability plus after-tax lease "
        "interest) is charged in free cash flow, and lease liabilities are excluded from net "
        "debt and from the WACC debt weight.</p>",
        _drivers_table(results),
        "<h2>WACC bridge</h2>",
        '<p class="note">The cost of equity and the cost of debt behind the WACC column in '
        "the Summary table, at the market-equity and book-debt weights they are blended at. "
        "Cost of debt is published pre-tax, as reported, alongside the after-tax figure "
        "actually used in the blend, so the tax shield is not counted twice.</p>",
        _wacc_table(results),
        "<h2>Implied against delivered growth</h2>",
        implied_growth_chart(implied, normalized),
        "<h2>Price against model</h2>",
        value_bridge_chart(prices),
        "<h2>Sensitivity</h2>",
        '<p class="note">Value per share across two pairs of assumptions. The first grid '
        "moves the model — the discount rate and the perpetual growth rate. The second moves "
        "the business — the operating margin and revenue growth. A valuation fragile to the "
        "first is an argument about the cost of capital; one fragile to the second is an "
        "argument about the company. A dash marks a combination with no meaning, where the "
        "discount rate sits at or below the growth rate; it is left blank rather than filled "
        "with a number that would look like an answer.</p>",
        _sensitivity_section(results),
        "<h2>Stated assumptions</h2>",
        f'<p class="note">Risk-free rate {_pct(RISK_FREE)}, equity risk premium '
        f"{_pct(EQUITY_RISK_PREMIUM)}. These are assumptions, not measurements; the "
        "sensitivity grid above shows what they are worth. Betas are recomputed from five "
        "years of weekly returns against the Euro Stoxx 50 rather than taken from a data "
        "provider's undocumented field.</p>",
        '<p class="note">Cash flows are dated from the latest fiscal year-end and rolled '
        "forward to the price date, so the first one is discounted over less than a year: "
        + "; ".join(
            f"{html_escape.escape(result.name)} {result.valuation_lag:.2f} years"
            for result in results.values()
        )
        + ".</p>",
    ]

    body = "\n".join(sections)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>What the market is paying for growth</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
