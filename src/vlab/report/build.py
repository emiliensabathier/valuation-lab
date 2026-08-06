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
            _pct(result.normalized_growth),
            _pct(result.wacc),
            _num(result.beta),
            _pct(result.terminal_share),
            f"{result.exit_multiple:.1f}x",
        ])
    return _table(
        ["Company", "Price", "Modelled value", "Implied growth", "Normalized growth",
         "WACC", "Beta", "Terminal share", "Implied exit"],
        rows,
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

    implied = {result.name: result.implied_growth for result in results.values()}
    normalized = {result.name: result.normalized_growth for result in results.values()}
    prices = {
        result.name: (result.price, result.value_per_share) for result in results.values()
    }

    sections += [
        "<h2>Summary</h2>",
        _summary_table(results),
    ]
    if failures:
        sections.append(_failures_section(failures))
    sections += [
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
    ]

    body = "\n".join(sections)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>What the market is paying for growth</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
