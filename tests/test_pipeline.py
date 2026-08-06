import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vlab.data.loader import Statements
from vlab.dcf import assumptions_from, value
from vlab.errors import DataError
from vlab.fundamentals import drivers_from
from vlab.pipeline import TERMINAL_GROWTH, convert_to_trading_currency, run
from vlab.universe import MARKET_INDEX, Company
from vlab.wacc import compute_wacc


def test_a_same_currency_company_is_returned_unchanged() -> None:
    lvmh = Company("MC.PA", "LVMH", "EUR", "EUR")

    assert convert_to_trading_currency(520.0, lvmh, rates={}) == pytest.approx(520.0)


def test_a_cross_currency_company_is_converted() -> None:
    richemont = Company("CFR.SW", "Richemont", "EUR", "CHF")

    converted = convert_to_trading_currency(120.0, richemont, rates={"EURCHF=X": 0.9359})

    assert converted == pytest.approx(120.0 * 0.9359)


def test_a_missing_rate_raises_rather_than_comparing_across_currencies() -> None:
    richemont = Company("CFR.SW", "Richemont", "EUR", "CHF")

    with pytest.raises(DataError, match="EURCHF"):
        convert_to_trading_currency(120.0, richemont, rates={})


# --- run() end to end, with injected fetchers -------------------------------------------
#
# Each ticker gets its own revenue trajectory (not the same shape rescaled) so that a
# per-company figure derived from it — normalized_growth in particular — is tied to that
# company's identity. A mutation that swapped two peers' drivers, or that dropped one
# company from the loop, has to break one of the assertions below; a uniform growth shape
# per ticker would let a swap slip through undetected.
_REVENUE_BY_TICKER: dict[str, list[float]] = {
    "MC.PA": [80_000.0, 76_000.0, 74_000.0],
    "RMS.PA": [16_000.0, 13_500.0, 12_000.0],
    "KER.PA": [20_000.0, 21_000.0, 19_000.0],
    "CFR.SW": [22_000.0, 21_500.0, 20_000.0],
}

# Every ticker's fixed "current price" — the fake price fetcher below forces each series'
# final observation to exactly this value, so the pipeline's reported price is asserted
# exactly rather than approximately.
_PRICE_BY_TICKER: dict[str, float] = {
    "MC.PA": 480.0,
    "RMS.PA": 1600.0,
    "KER.PA": 290.0,
    "CFR.SW": 196.0,
    MARKET_INDEX: 4800.0,
    "EURCHF=X": 0.94,
}

# Share counts chosen so the fixed prices above sit comfortably inside the reverse DCF's
# GROWTH_BRACKET for each company (found by fixed-point iteration: shares = equity_value /
# price, re-solved because market_cap = price * shares feeds back into WACC's equity
# weight, computed against the exact seeding _fake_price_fetcher below uses). Not real share
# counts — internal consistency with that fetcher is all this fixture needs.
_SHARES_BY_TICKER: dict[str, float] = {
    "MC.PA": 632.937667,
    "RMS.PA": 65.814553,
    "KER.PA": 248.746382,
    "CFR.SW": 439.470275,
}


def _pipeline_statements(ticker: str) -> Statements:
    revenue = _REVENUE_BY_TICKER[ticker]
    shares = _SHARES_BY_TICKER[ticker]
    periods = pd.DatetimeIndex(["2025-12-31", "2024-12-31", "2023-12-31"])
    ebit = [r * 0.2 for r in revenue]
    interest = [r * 0.015 for r in revenue]
    income = pd.DataFrame(
        [revenue, ebit, [e * 0.9 for e in ebit], [e * 0.27 for e in ebit], interest],
        index=["Total Revenue", "EBIT", "Pretax Income", "Tax Provision", "Interest Expense"],
        columns=periods,
    )
    cashflow = pd.DataFrame(
        [[-0.06 * r for r in revenue], [0.10 * r for r in revenue], [-0.01 * r for r in revenue]],
        index=["Capital Expenditure", "Depreciation And Amortization", "Change In Working Capital"],
        columns=periods,
    )
    balance = pd.DataFrame(
        [
            [revenue[0] * 0.30] * 3,
            [revenue[0] * 0.05] * 3,
            [revenue[0] * 0.01] * 3,
            [shares] * 3,
        ],
        index=["Total Debt", "Cash Cash Equivalents And Short Term Investments",
               "Minority Interest", "Ordinary Shares Number"],
        columns=periods,
    )
    return Statements(income, cashflow, balance, {"sharesOutstanding": shares})


def _fake_statement_fetcher(ticker: str) -> Statements:
    return _pipeline_statements(ticker)


def _fake_price_fetcher(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    # Real variance and correlation for the beta calculation over most of the series, but
    # the last observation of every column is forced to a known constant so the "current
    # price" the pipeline reads is an exact, assertable number rather than a stochastic one.
    #
    # The market factor and each ticker's idiosyncratic noise are seeded independently of
    # which *other* tickers are in this call's request list. That is what lets the test
    # recompute a single company's series on its own (to verify its WACC and value directly)
    # and get byte-identical numbers to what run() saw when it requested all five at once —
    # a seed derived from the whole requested ticker list would silently break that.
    #
    # zlib.crc32, not the builtin hash(): str hashing is salted per process (PYTHONHASHSEED),
    # so hash(ticker) is stable within one test call but not reproducible across separate
    # pytest invocations — this fixture needs the same seed every run, not just every call.
    n = 60
    dates = pd.bdate_range("2023-01-01", periods=n, freq="W-FRI")
    market_returns = np.random.default_rng(1234).normal(0.0, 0.02, n)
    data = {}
    for ticker in tickers:
        seed = zlib.crc32(ticker.encode())
        idiosyncratic = np.random.default_rng(seed).normal(0.0, 0.01, n)
        level = _PRICE_BY_TICKER[ticker]
        series = level * np.cumprod(1 + 0.7 * market_returns + idiosyncratic)
        series[-1] = level
        data[ticker] = series
    return pd.DataFrame(data, index=dates)


def test_run_associates_each_company_with_its_own_figures(tmp_path: Path) -> None:
    results = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    # All four peers come back — a dropped company is not silently absent from the report.
    assert set(results) == {"LVMH", "Hermes", "Kering", "Richemont"}

    # Each company's price is its own, exactly, not another company's or a repeated figure.
    assert results["LVMH"].price == pytest.approx(480.0)
    assert results["Hermes"].price == pytest.approx(1600.0)
    assert results["Kering"].price == pytest.approx(290.0)
    assert results["Richemont"].price == pytest.approx(196.0)

    # No two companies carry the same modelled value — catches a loop that overwrote one
    # company's result with another's rather than computing each independently.
    values = [r.value_per_share for r in results.values()]
    assert len(set(values)) == 4

    # normalized_growth comes straight from each company's own revenue trajectory. Recomputing
    # it independently here, from the same fixture data keyed by ticker, is what a driver swap
    # between two peers would break: the wrong company would show the wrong growth.
    for name, ticker in [("LVMH", "MC.PA"), ("Kering", "KER.PA")]:
        drivers = drivers_from(_pipeline_statements(ticker), ticker)
        assert results[name].normalized_growth == pytest.approx(drivers.revenue_growth)

    # The one thing this task had to get right: Richemont's reported value per share is its
    # EUR (reporting-currency) DCF value converted to CHF (trading currency) by the fetched
    # EURCHF rate — not the unconverted euro figure sitting next to a franc price. Recomputed
    # independently via the same public functions run() itself calls, on the same fixture.
    fx_rate = _PRICE_BY_TICKER["EURCHF=X"]
    richemont_statements = _pipeline_statements("CFR.SW")
    richemont_drivers = drivers_from(richemont_statements, "CFR.SW")
    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices = _fake_price_fetcher(["CFR.SW"], "5y", "1wk")["CFR.SW"]
    # market_cap must be in the reporting currency (EUR), same as gross debt on the balance
    # sheet — the price quoted in CHF is converted back before it feeds WACC.
    cost_of_capital = compute_wacc(
        richemont_statements, "CFR.SW", richemont_drivers,
        (196.0 / fx_rate) * richemont_drivers.shares, stock_prices, market_prices,
    )
    assumptions = assumptions_from(richemont_drivers, cost_of_capital.value, TERMINAL_GROWTH)
    raw_eur_value_per_share = value(richemont_drivers, assumptions).value_per_share

    assert results["Richemont"].value_per_share == pytest.approx(
        raw_eur_value_per_share * fx_rate, rel=1e-6
    )
    # And that this is a genuine conversion, not a value that happens to match itself: the
    # unconverted euro figure and the reported franc figure must differ by roughly the rate.
    assert results["Richemont"].value_per_share != pytest.approx(raw_eur_value_per_share)


def test_richemonts_wacc_uses_market_cap_in_the_reporting_currency_not_the_trading_one(
    tmp_path: Path,
) -> None:
    """CRITICAL bug: pipeline.run() built market_cap from the CHF share price, then blended
    it with Richemont's EUR gross debt inside compute_wacc — francs added to euros. Market
    cap must be computed in EUR (the reporting currency, same as gross debt) before it ever
    reaches compute_wacc.
    """
    results = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    fx_rate = _PRICE_BY_TICKER["EURCHF=X"]
    richemont_statements = _pipeline_statements("CFR.SW")
    richemont_drivers = drivers_from(richemont_statements, "CFR.SW")
    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices = _fake_price_fetcher(["CFR.SW"], "5y", "1wk")["CFR.SW"]

    price_eur = _PRICE_BY_TICKER["CFR.SW"] / fx_rate
    market_cap_eur = price_eur * richemont_drivers.shares

    expected = compute_wacc(
        richemont_statements, "CFR.SW", richemont_drivers,
        market_cap_eur, stock_prices, market_prices,
    )

    assert results["Richemont"].wacc == pytest.approx(expected.value, rel=1e-9)


def test_market_cap_uses_the_balance_sheet_share_count_not_infos_sharesoutstanding(
    tmp_path: Path,
) -> None:
    """IMPORTANT bug: info['sharesOutstanding'] and the balance sheet's Ordinary Shares
    Number can disagree (Richemont: 534.2M vs 587.9M in the real data). fundamentals.py
    already divides equity value by the balance-sheet count, so pipeline.py must build
    market_cap from that same count — otherwise WACC and the equity bridge run on two
    different share counts for the same company.
    """

    def _mismatched_fetcher(ticker: str) -> Statements:
        statements = _pipeline_statements(ticker)
        if ticker == "MC.PA":
            mismatched_info = dict(statements.info)
            mismatched_info["sharesOutstanding"] = _SHARES_BY_TICKER["MC.PA"] * 1.5
            statements = Statements(
                statements.income, statements.cashflow, statements.balance, mismatched_info
            )
        return statements

    results = run(
        cache_dir=tmp_path,
        statement_fetcher=_mismatched_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    lvmh_drivers = drivers_from(_pipeline_statements("MC.PA"), "MC.PA")
    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices = _fake_price_fetcher(["MC.PA"], "5y", "1wk")["MC.PA"]
    expected_market_cap = _PRICE_BY_TICKER["MC.PA"] * lvmh_drivers.shares
    expected = compute_wacc(
        _pipeline_statements("MC.PA"), "MC.PA", lvmh_drivers,
        expected_market_cap, stock_prices, market_prices,
    )

    assert results["LVMH"].wacc == pytest.approx(expected.value, rel=1e-9)
