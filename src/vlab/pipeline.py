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
from vlab.errors import DataError
from vlab.fundamentals import drivers_from
from vlab.report.build import build_report
from vlab.reverse import implied_revenue_growth
from vlab.sensitivity import default_margin_growth_grid, default_wacc_terminal_grid
from vlab.universe import MARKET_INDEX, PEERS, Company, needs_conversion, tickers
from vlab.wacc import compute_wacc

TERMINAL_GROWTH = 0.02


@dataclass(frozen=True)
class CompanyResult:
    """Everything the report needs about one company."""

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

    pair = f"{company.reporting_currency}{company.trading_currency}=X"
    if pair not in rates:
        raise DataError(
            f"{company.ticker} reports in {company.reporting_currency} and trades in "
            f"{company.trading_currency}, but no {pair} rate was supplied"
        )
    return amount * rates[pair]


def run(
    *,
    cache_dir: Path,
    refresh: bool = False,
    statement_fetcher: StatementFetcher | None = None,
    price_fetcher: PriceFetcher | None = None,
) -> dict[str, CompanyResult]:
    """Value every peer and invert the model against its market price.

    The two fetchers are injectable so the whole pipeline can be replayed offline against
    frozen inputs. That is what lets the regression fixture recompute the published numbers
    and compare them, rather than merely restating them.
    """
    all_tickers = tickers() + [MARKET_INDEX]
    prices = load_prices(all_tickers, cache_dir=cache_dir, refresh=refresh, fetcher=price_fetcher)
    market_prices = prices[MARKET_INDEX]

    rates: dict[str, float] = {}
    for company in PEERS:
        if needs_conversion(company):
            pair = f"{company.reporting_currency}{company.trading_currency}=X"
            rates[pair] = load_fx_rate(
                pair, cache_dir=cache_dir, refresh=refresh, fetcher=price_fetcher
            )

    results: dict[str, CompanyResult] = {}
    for company in PEERS:
        statements = load_statements(
            company.ticker, cache_dir=cache_dir, refresh=refresh, fetcher=statement_fetcher
        )
        drivers = drivers_from(statements, company.ticker)

        price = float(prices[company.ticker].iloc[-1])
        shares = float(statements.info.get("sharesOutstanding") or drivers.shares)
        market_cap = price * shares

        cost_of_capital = compute_wacc(
            statements, company.ticker, drivers, market_cap,
            prices[company.ticker], market_prices,
        )
        assumptions = assumptions_from(drivers, cost_of_capital.value, TERMINAL_GROWTH)
        valuation = value(drivers, assumptions)

        # The model works in the reporting currency; the price is quoted in the trading one.
        value_per_share = convert_to_trading_currency(
            valuation.value_per_share, company, rates
        )
        price_in_reporting = price / rates.get(
            f"{company.reporting_currency}{company.trading_currency}=X", 1.0
        )

        results[company.name] = CompanyResult(
            name=company.name,
            ticker=company.ticker,
            trading_currency=company.trading_currency,
            price=price,
            value_per_share=value_per_share,
            implied_growth=implied_revenue_growth(drivers, assumptions, price_in_reporting),
            normalized_growth=drivers.revenue_growth,
            wacc=cost_of_capital.value,
            beta=cost_of_capital.beta,
            terminal_share=valuation.terminal_share,
            exit_multiple=terminal_exit_multiple(drivers, assumptions),
            sensitivity=default_wacc_terminal_grid(drivers, assumptions),
            margin_sensitivity=default_margin_growth_grid(drivers, assumptions),
        )

    return results


def render(results: dict[str, CompanyResult], generated_on: str) -> str:
    """Render the pipeline output as HTML."""
    return build_report(results, generated_on=generated_on)
