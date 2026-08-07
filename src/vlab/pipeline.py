"""End-to-end pipeline: tickers in, valuations out."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from vlab.data.loader import (
    PriceFetcher,
    StatementFetcher,
    load_fx_rate,
    load_prices,
    load_statements,
)
from vlab.dcf import assumptions_from, terminal_exit_multiple, value
from vlab.errors import DataError, ValuationError
from vlab.fundamentals import Drivers, drivers_from
from vlab.report.build import build_report
from vlab.reverse import implied_revenue_growth
from vlab.sensitivity import default_margin_growth_grid, default_wacc_terminal_grid
from vlab.universe import MARKET_INDEX, PEERS, Company, needs_conversion, tickers
from vlab.wacc import compute_wacc

TERMINAL_GROWTH = 0.02


@dataclass(frozen=True)
class CompanyResult:
    """Everything the report needs about one company.

    ``drivers`` is the normalized ``Drivers`` this valuation was built from, in
    ``reporting_currency`` -- carried through so the report can show a reader what the model
    is actually pricing (revenue, margin, tax rate, capex ratio, net debt, fiscal years), not
    only what it concludes.
    """

    name: str
    ticker: str
    reporting_currency: str
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
    drivers: Drivers


@dataclass(frozen=True)
class CompanyFailure:
    """A company whose valuation could not be produced, and why.

    Recorded rather than raised past ``run``, so that one company's infeasible valuation
    does not remove the other three from the report -- and recorded rather than silently
    dropped, which is the failure mode this repository forbids just as firmly as a crash.
    """

    name: str
    ticker: str
    reason: str


def _fx_pair(company: Company) -> str:
    return f"{company.reporting_currency}{company.trading_currency}=X"


def _rate_for(company: Company, rates: dict[str, float]) -> float:
    """Look up the fetched rate for a company that needs conversion, or raise.

    Shared by every conversion below so a missing rate is one error message, not several
    slightly different ones, and so nothing re-fetches what the pre-loop already fetched.
    """
    pair = _fx_pair(company)
    if pair not in rates:
        raise DataError(
            f"{company.ticker} reports in {company.reporting_currency} and trades in "
            f"{company.trading_currency}, but no {pair} rate was supplied"
        )
    return rates[pair]


def convert_to_trading_currency(
    amount: float, company: Company, rates: dict[str, float]
) -> float:
    """Convert a per-share value from the reporting currency into the traded one.

    Richemont publishes in euros and trades in francs. Comparing the two without converting
    produces a plausible number and a wrong conclusion, so a missing rate is an error rather
    than an assumption of parity.
    """
    if not needs_conversion(company):
        return amount
    return amount * _rate_for(company, rates)


def _convert_grid_to_trading_currency(
    table: pd.DataFrame, company: Company, rates: dict[str, float]
) -> pd.DataFrame:
    """Convert a value-per-share sensitivity grid into the trading currency.

    The grid is computed in the reporting currency, exactly like ``dcf.value``. Converting it
    here — with the same rate already fetched for the summary row, not a fresh fetch — keeps
    every number on the report page in one currency. NaN cells (infeasible combinations) stay
    NaN under multiplication, so the "no meaning here" marker survives the conversion.
    """
    if not needs_conversion(company):
        return table
    return table * _rate_for(company, rates)


def _value_company(
    company: Company,
    prices: pd.DataFrame,
    market_prices: pd.Series,
    *,
    cache_dir: Path,
    refresh: bool,
    statement_fetcher: StatementFetcher | None,
    price_fetcher: PriceFetcher | None,
) -> CompanyResult:
    """Value one company end to end. Raises DataError or ValuationError on failure.

    The FX rate for a cross-currency company is fetched here, inside the per-company try in
    ``run``, rather than in a shared pre-loop -- so a rate that fails to fetch fails only the
    one company that needed it, not the three that did not.
    """
    statements = load_statements(
        company.ticker, cache_dir=cache_dir, refresh=refresh, fetcher=statement_fetcher
    )
    drivers = drivers_from(statements, company.ticker)

    price = float(prices[company.ticker].iloc[-1])
    # The balance-sheet count (drivers.shares, "Ordinary Shares Number"), not
    # info["sharesOutstanding"]: fundamentals.py already divides equity value by the
    # balance-sheet count, and the two sources can disagree by several percent (Richemont:
    # 534.2M reported vs 587.9M on the balance sheet). Using two different counts for the
    # same company's market cap and its equity bridge is an unreconciled, undocumented
    # discrepancy; a single source keeps both consistent with each other.
    shares = drivers.shares

    rates: dict[str, float] = {}
    if needs_conversion(company):
        rates[_fx_pair(company)] = load_fx_rate(
            _fx_pair(company), cache_dir=cache_dir, refresh=refresh, fetcher=price_fetcher
        )

    # market_cap must be in the reporting currency, the same currency gross debt is reported
    # in on the balance sheet. Multiplying the trading-currency price by shares here would
    # blend, say, a Swiss-franc market cap with euro debt inside compute_wacc — a unit error
    # that looks like a plausible number and is not one.
    price_in_reporting = price / _rate_for(company, rates) if needs_conversion(company) else price
    market_cap = price_in_reporting * shares

    cost_of_capital = compute_wacc(
        statements, company.ticker, drivers, market_cap,
        prices[company.ticker], market_prices,
    )
    assumptions = assumptions_from(drivers, cost_of_capital.value, TERMINAL_GROWTH)
    valuation = value(drivers, assumptions)

    # The model works in the reporting currency; the price is quoted in the trading one. The
    # sensitivity grids get the same conversion, with this same fetched rate, so every number
    # on the report page for this company sits in one currency.
    value_per_share = convert_to_trading_currency(valuation.value_per_share, company, rates)
    sensitivity = _convert_grid_to_trading_currency(
        default_wacc_terminal_grid(drivers, assumptions), company, rates
    )
    margin_sensitivity = _convert_grid_to_trading_currency(
        default_margin_growth_grid(drivers, assumptions), company, rates
    )

    return CompanyResult(
        name=company.name,
        ticker=company.ticker,
        reporting_currency=company.reporting_currency,
        trading_currency=company.trading_currency,
        price=price,
        value_per_share=value_per_share,
        implied_growth=implied_revenue_growth(drivers, assumptions, price_in_reporting),
        normalized_growth=drivers.revenue_growth,
        wacc=cost_of_capital.value,
        beta=cost_of_capital.beta,
        terminal_share=valuation.terminal_share,
        exit_multiple=terminal_exit_multiple(drivers, assumptions),
        sensitivity=sensitivity,
        margin_sensitivity=margin_sensitivity,
        drivers=drivers,
    )


def run(
    *,
    cache_dir: Path,
    refresh: bool = False,
    statement_fetcher: StatementFetcher | None = None,
    price_fetcher: PriceFetcher | None = None,
) -> tuple[dict[str, CompanyResult], list[CompanyFailure]]:
    """Value every peer and invert the model against its market price.

    The two fetchers are injectable so the whole pipeline can be replayed offline against
    frozen inputs. That is what lets the regression fixture recompute the published numbers
    and compare them, rather than merely restating them.

    Each company is valued independently. One company's data being unusable, or its price
    implying a growth rate outside the reverse DCF's plausibility bracket, is recorded as a
    CompanyFailure instead of aborting the other three -- a real refusal for that one company,
    reported on the page, rather than either a crash that loses every valuation or a silent
    drop that loses just the one.
    """
    all_tickers = tickers() + [MARKET_INDEX]
    prices = load_prices(all_tickers, cache_dir=cache_dir, refresh=refresh, fetcher=price_fetcher)
    market_prices = prices[MARKET_INDEX]

    results: dict[str, CompanyResult] = {}
    failures: list[CompanyFailure] = []
    for company in PEERS:
        try:
            results[company.name] = _value_company(
                company, prices, market_prices,
                cache_dir=cache_dir, refresh=refresh,
                statement_fetcher=statement_fetcher, price_fetcher=price_fetcher,
            )
        except (DataError, ValuationError) as exc:
            failures.append(CompanyFailure(company.name, company.ticker, str(exc)))

    return results, failures


def render(
    results: dict[str, CompanyResult], failures: list[CompanyFailure], generated_on: str
) -> str:
    """Render the pipeline output as HTML."""
    return build_report(results, failures, generated_on=generated_on)
