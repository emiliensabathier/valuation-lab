import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vlab.data.loader import Statements
from vlab.dcf import assumptions_from, value
from vlab.errors import DataError, ValuationError
from vlab.fundamentals import drivers_from
from vlab.pipeline import (
    LOWER_WACC_STEPS,
    TERMINAL_GROWTH,
    convert_to_trading_currency,
    run,
    valuation_lag,
)
from vlab.reverse import implied_average_growth
from vlab.sensitivity import default_wacc_terminal_grid
from vlab.universe import MARKET_INDEX, Company
from vlab.wacc import compute_wacc, levered_beta


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
# Kering's was scaled up when working capital moved onto the change in revenue: its falling
# revenue now releases cash, which lifted every value in the bracket above the fixed price.
_SHARES_BY_TICKER: dict[str, float] = {
    "MC.PA": 632.937667,
    "RMS.PA": 65.814553,
    "KER.PA": 323.370297,
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
        [[-0.06 * r for r in revenue], [0.10 * r for r in revenue], [-0.01 * r for r in revenue],
         [0.0] * 3],
        index=["Capital Expenditure", "Depreciation And Amortization", "Change In Working Capital",
               "Sale Of PPE"],
        columns=periods,
    )
    balance = pd.DataFrame(
        [
            [revenue[0] * 0.30] * 3,
            [revenue[0] * 0.05] * 3,
            [revenue[0] * 0.01] * 3,
            [shares] * 3,
            # No leases: the synthetic peers' share counts were tuned without them, and the
            # lease arithmetic has its own tests in test_fundamentals.py and test_dcf.py.
            [0.0] * 3,
            [0.0] * 3,
            [r * 0.10 for r in revenue],
            [0.0] * 3,
            [r * 0.10 for r in revenue],
        ],
        index=["Total Debt", "Cash Cash Equivalents And Short Term Investments",
               "Minority Interest", "Ordinary Shares Number",
               "Capital Lease Obligations", "Current Capital Lease Obligation",
               "Inventory", "Accounts Receivable", "Accounts Payable"],
        columns=periods,
    )
    return Statements(income, cashflow, balance, {"sharesOutstanding": shares})


def _fake_statement_fetcher(ticker: str) -> Statements:
    return _pipeline_statements(ticker)


EQUITY_MARKET_WEIGHT = 0.7
# EURCHF=X gets its own, deliberately different exposure to the shared market factor rather
# than reusing the equities' 0.7 -- a real FX pair's co-movement with an equity index has
# nothing to do with a stock's own beta. A distinct, negative weight is also what makes
# converting CFR.SW's price series into EUR before the beta regression a genuine change of
# currency instead of a no-op: dividing two series built from the *same* market exposure would
# cancel most of it out and leave a beta near zero, which would prove the conversion runs but
# not that it produces a sane, economically plausible number.
FX_MARKET_WEIGHT = -0.1


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
    # The series ends on the synthetic fiscal year-end, so the valuation lag is zero and the
    # tests below can recompute a value without rolling it forward. The lag has its own test.
    dates = pd.date_range(end="2025-12-31", periods=n, freq="7D")
    market_returns = np.random.default_rng(1234).normal(0.0, 0.02, n)
    data = {}
    for ticker in tickers:
        seed = zlib.crc32(ticker.encode())
        idiosyncratic = np.random.default_rng(seed).normal(0.0, 0.01, n)
        level = _PRICE_BY_TICKER[ticker]
        weight = FX_MARKET_WEIGHT if ticker == "EURCHF=X" else EQUITY_MARKET_WEIGHT
        series = level * np.cumprod(1 + weight * market_returns + idiosyncratic)
        series[-1] = level
        data[ticker] = series
    return pd.DataFrame(data, index=dates)


def _cfr_stock_prices_in_eur() -> pd.Series:
    """Richemont's CHF price series, converted into EUR the same way pipeline.py's
    ``_stock_prices_for_beta`` does: divided, date by date, by the full EURCHF history, keeping
    only the dates the two series share.
    """
    stock_chf = _fake_price_fetcher(["CFR.SW"], "5y", "1wk")["CFR.SW"]
    fx_history = _fake_price_fetcher(["EURCHF=X"], "5y", "1wk")["EURCHF=X"]
    aligned = pd.concat([stock_chf, fx_history], axis=1, join="inner").dropna()
    return aligned.iloc[:, 0] / aligned.iloc[:, 1]


def test_run_associates_each_company_with_its_own_figures(tmp_path: Path) -> None:
    results, failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    # All four peers come back — a dropped company is not silently absent from the report.
    assert set(results) == {"LVMH", "Hermes", "Kering", "Richemont"}
    assert failures == []

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
    stock_prices = _cfr_stock_prices_in_eur()
    # market_cap must be in the reporting currency (EUR), same as gross debt on the balance
    # sheet — the price quoted in CHF is converted back before it feeds WACC. The beta
    # regression also needs both sides in one currency, so the stock series is converted here
    # too, the same way pipeline.py converts it before calling compute_wacc.
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
    results, _failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    fx_rate = _PRICE_BY_TICKER["EURCHF=X"]
    richemont_statements = _pipeline_statements("CFR.SW")
    richemont_drivers = drivers_from(richemont_statements, "CFR.SW")
    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices = _cfr_stock_prices_in_eur()

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

    results, _failures = run(
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


def test_a_single_companys_valuation_failure_does_not_abort_the_others(tmp_path: Path) -> None:
    """IMPORTANT bug: run() had no per-company error isolation. Hermes' implied growth sits
    close enough to the reverse DCF's plausibility ceiling that a modest price move pushes it
    past the bracket and implied_revenue_growth raises ValuationError -- which used to
    propagate straight out of run() and abort the other three companies too. The failure
    must be recorded and the other three must still come back.
    """

    def _extreme_price_fetcher(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
        frame = _fake_price_fetcher(tickers, period, interval)
        if "RMS.PA" in frame.columns:
            frame = frame.copy()
            frame.loc[frame.index[-1], "RMS.PA"] = frame["RMS.PA"].iloc[-1] * 50.0
        return frame

    results, failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_extreme_price_fetcher,
    )

    assert set(results) == {"LVMH", "Kering", "Richemont"}
    assert len(failures) == 1
    assert failures[0].name == "Hermes"
    assert failures[0].ticker == "RMS.PA"
    assert "growth" in failures[0].reason.lower()


def test_richemonts_sensitivity_grids_are_converted_to_the_trading_currency(
    tmp_path: Path,
) -> None:
    """IMPORTANT bug: the sensitivity grids are computed in the reporting currency (EUR),
    same as dcf.value, but were never converted. Left as EUR, Richemont's grid cells sit next
    to a CHF summary row -- a ~7% gap on the same page with nothing to explain it. They must
    carry the same conversion as the summary row, using the same fetched rate.
    """
    results, _failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    fx_rate = _PRICE_BY_TICKER["EURCHF=X"]
    richemont_statements = _pipeline_statements("CFR.SW")
    richemont_drivers = drivers_from(richemont_statements, "CFR.SW")
    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices = _cfr_stock_prices_in_eur()
    price_eur = _PRICE_BY_TICKER["CFR.SW"] / fx_rate
    market_cap_eur = price_eur * richemont_drivers.shares
    cost_of_capital = compute_wacc(
        richemont_statements, "CFR.SW", richemont_drivers,
        market_cap_eur, stock_prices, market_prices,
    )
    assumptions = assumptions_from(richemont_drivers, cost_of_capital.value, TERMINAL_GROWTH)
    raw_grid_eur = default_wacc_terminal_grid(richemont_drivers, assumptions)

    pd.testing.assert_frame_equal(
        results["Richemont"].sensitivity, raw_grid_eur * fx_rate, check_exact=False, rtol=1e-6
    )


def test_richemonts_beta_is_computed_in_a_single_currency_not_two(tmp_path: Path) -> None:
    """IMPORTANT bug: levered_beta regressed Richemont's CHF-denominated returns against the
    EUR-denominated Euro Stoxx 50 -- measuring Richemont's co-movement with the index blended
    with the franc's co-movement with it, not Richemont's alone. The stock's own price series
    must be converted into its reporting currency (EUR, matching the index) before the
    regression, using the full EURCHF history -- not just the single latest rate used to
    convert the final value per share.
    """
    results, _failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    market_prices = _fake_price_fetcher([MARKET_INDEX], "5y", "1wk")[MARKET_INDEX]
    stock_prices_chf = _fake_price_fetcher(["CFR.SW"], "5y", "1wk")["CFR.SW"]
    stock_prices_eur = _cfr_stock_prices_in_eur()

    correct_beta = levered_beta(stock_prices_eur, market_prices)
    currency_mixed_beta = levered_beta(stock_prices_chf, market_prices)

    # Proof the FX series has a genuine effect: converting first changes the number. If this
    # assertion ever fails, the synthetic fixture's FX series stopped varying and no longer
    # exercises the bug.
    assert correct_beta != pytest.approx(currency_mixed_beta)

    assert results["Richemont"].beta == pytest.approx(correct_beta, rel=1e-9)


def test_a_non_overlapping_fx_history_for_the_beta_raises_rather_than_falling_back(
    tmp_path: Path,
) -> None:
    """No silent fallback: if a cross-currency company's FX history shares no date with its
    own price series, the conversion must raise -- not silently fall back to regressing the
    unconverted, currency-mixed series, which would reintroduce the exact bug this guards
    against.
    """

    def _disjoint_fx_price_fetcher(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
        frame = _fake_price_fetcher(tickers, period, interval)
        if "EURCHF=X" in frame.columns:
            frame = frame.copy()
            frame.index = frame.index - pd.Timedelta(days=3650)
        return frame

    results, failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_disjoint_fx_price_fetcher,
    )

    assert "Richemont" not in results
    richemont_failure = next(f for f in failures if f.name == "Richemont")
    assert "EURCHF=X" in richemont_failure.reason
    assert "overlap" in richemont_failure.reason.lower()


def test_the_valuation_lag_is_the_time_from_the_fiscal_year_end_to_the_price_date() -> None:
    lag = valuation_lag("2025-12-31", pd.Timestamp("2026-08-07"))

    assert lag == pytest.approx(219 / 365.25)


def test_a_price_dated_before_the_fiscal_year_end_raises() -> None:
    with pytest.raises(ValuationError, match="before"):
        valuation_lag("2025-12-31", pd.Timestamp("2025-06-30"))


def test_run_rolls_each_valuation_forward_to_its_price_date(tmp_path: Path) -> None:
    def _later_price_fetcher(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
        frame = _fake_price_fetcher(tickers, period, interval)
        return frame.set_index(frame.index + pd.Timedelta(days=146))

    results, failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_later_price_fetcher,
    )
    assert failures == []

    lvmh = results["LVMH"]
    assert lvmh.valuation_lag == pytest.approx(146 / 365.25)
    assumptions = assumptions_from(
        lvmh.drivers, lvmh.wacc, TERMINAL_GROWTH, valuation_lag=146 / 365.25
    )
    assert lvmh.value_per_share == pytest.approx(
        value(lvmh.drivers, assumptions).value_per_share, rel=1e-12
    )


def test_run_reports_the_implied_growth_at_lower_discount_rates(tmp_path: Path) -> None:
    # The headline gap between implied and delivered growth is conditional on the WACC; the
    # same price restated at a lower discount rate is what lets a reader see by how much.
    results, _failures = run(
        cache_dir=tmp_path,
        statement_fetcher=_fake_statement_fetcher,
        price_fetcher=_fake_price_fetcher,
    )

    lvmh = results["LVMH"]
    assert set(lvmh.implied_average_growth_at_lower_wacc) == set(LOWER_WACC_STEPS)
    for step, implied in lvmh.implied_average_growth_at_lower_wacc.items():
        assumptions = assumptions_from(lvmh.drivers, lvmh.wacc - step, TERMINAL_GROWTH)
        assert implied == pytest.approx(
            implied_average_growth(lvmh.drivers, assumptions, lvmh.price), rel=1e-6
        )
        assert implied < lvmh.implied_average_growth
