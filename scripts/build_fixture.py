"""Regenerate the regression fixture: the raw inputs and the numbers they produce.

Run manually after a deliberate methodology change, never in CI. Regenerating this in an
automated job would silently re-baseline whatever the code currently produces, which is
precisely the guarantee the fixture exists to provide.

Two modes, and the distinction matters more than it looks:

    python scripts/build_fixture.py --expectations-only   # the usual case
    python scripts/build_fixture.py                       # re-capture the market data too

A methodology change moves the *outputs* while the inputs stay exactly as captured. The
default mode re-reads the live cache and rewrites the captured statements and prices as a
side effect, so running it to pick up a model change silently re-dates the whole fixture
and every published figure moves for two reasons at once -- the change you made, and a
market that moved underneath it. Use --expectations-only unless re-capturing is the point.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# tests/ has no __init__.py; it is only importable as "tests.fixtures.frozen" when the repo
# root sits on sys.path, which pytest arranges for the test suite but a standalone script
# invocation (``python scripts/build_fixture.py``) does not. Same pattern as
# build_frozen_report.py, for the same reason.
sys.path.insert(0, str(ROOT))

from tests.fixtures.frozen import FrozenPriceFetcher, FrozenStatementFetcher  # noqa: E402

from vlab.data.loader import Statements, load_prices, load_statements  # noqa: E402
from vlab.pipeline import run  # noqa: E402
from vlab.universe import MARKET_INDEX, PEERS, needs_conversion, tickers  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
CACHE = Path("cache")


def _capture_inputs(statements_dir: Path) -> None:
    """Re-freeze the raw statements and prices from the live cache."""
    statements_dir.mkdir(parents=True, exist_ok=True)

    # Freeze the inputs first, so the test can rebuild them without a network.
    info: dict[str, dict] = {}
    statements_by_ticker: dict[str, Statements] = {}
    for company in PEERS:
        statements = load_statements(company.ticker, cache_dir=CACHE)
        statements_by_ticker[company.ticker] = statements
        safe = company.ticker.replace(".", "_")
        statements.income.to_csv(statements_dir / f"{safe}_income.csv")
        statements.cashflow.to_csv(statements_dir / f"{safe}_cashflow.csv")
        statements.balance.to_csv(statements_dir / f"{safe}_balance.csv")
        info[company.ticker] = {
            key: value
            for key, value in statements.info.items()
            if key in {"currency", "financialCurrency", "sharesOutstanding"}
        }
    (statements_dir / "info.json").write_text(
        json.dumps(info, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )

    series = load_prices(tickers() + [MARKET_INDEX], cache_dir=CACHE)
    pairs = [
        f"{company.reporting_currency}{company.trading_currency}=X"
        for company in PEERS
        if needs_conversion(company)
    ]
    # Two different windows of the same pair, production requests through two different
    # (period, interval) calls to load_prices: the 1mo/1d window feeds load_fx_rate's
    # point-in-time conversion (the freshest close available); the 5y/1wk window -- the same
    # period and cadence as the equity prices above -- feeds levered_beta's currency
    # conversion, which needs a rate for every date in the regression, not just the latest one.
    #
    # They are kept in two separate files, one per cadence, rather than merged into a single
    # column: merging let the daily window's closes silently overwrite same-dated weekly
    # closes (5 of Richemont's 262 weekly EURCHF observations), pairing a Friday-cadence
    # equity close with a Monday-cadence rate and reproducing production only to the last
    # digit rather than exactly. FrozenPriceFetcher.__call__ picks the file matching the
    # (period, interval) it is asked for, so a beta-regression request only ever sees the
    # weekly-cadence rate and a point-in-time request only ever sees the daily-cadence one.
    daily_pairs = []
    for pair in pairs:
        weekly_history = load_prices([pair], cache_dir=CACHE)[pair]
        series = series.join(weekly_history, how="outer")
        daily_pairs.append(load_prices([pair], cache_dir=CACHE, period="1mo", interval="1d")[pair])
    series.to_csv(FIXTURES / "prices.csv")
    if daily_pairs:
        pd.concat(daily_pairs, axis=1).to_csv(FIXTURES / "fx_rates_daily.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expectations-only",
        action="store_true",
        help="recompute the outputs from the committed inputs, leaving the capture alone",
    )
    args = parser.parse_args()

    statements_dir = FIXTURES / "statements"
    statements_dir.mkdir(parents=True, exist_ok=True)
    if args.expectations_only:
        print("replaying the committed capture; statements and prices left untouched")
    else:
        _capture_inputs(statements_dir)

    # Then the outputs, computed from exactly those frozen inputs -- not from a second,
    # independent read of the live cache. Richemont's beta reads the EURCHF pair through two
    # separate calls at two different cadences (the point-in-time rate and the full history);
    # replaying through the real FrozenPriceFetcher, against the same two files just written to
    # ``prices.csv`` and ``fx_rates_daily.csv``, is what guarantees expected_valuations.json
    # matches what tests/fixtures/frozen.py will hand back later -- including which cadence
    # answers which request, not just which columns are available.
    #
    # A disposable, empty cache_dir is required here, not CACHE: load_prices and
    # load_statements check their on-disk cache *before* calling an injected fetcher, so
    # pointing this run at the real, already-populated cache/ would silently skip both
    # fetchers below and read the live per-cadence cache files instead -- the exact
    # inconsistency this replay exists to prevent (see build_frozen_report.py's identical
    # reasoning for the same pattern).
    # Read the inputs back through the same frozen fetchers the test suite uses, rather
    # than from whatever _capture_inputs happened to hold in memory. Under
    # --expectations-only nothing was held in memory at all, and under a full capture this
    # proves the files just written are the ones that produce these numbers.
    with tempfile.TemporaryDirectory() as disposable_cache:
        results, failures = run(
            cache_dir=Path(disposable_cache),
            statement_fetcher=FrozenStatementFetcher(),
            price_fetcher=FrozenPriceFetcher(),
        )
    if failures:
        raise RuntimeError(f"cannot freeze a fixture with unresolved failures: {failures}")
    frozen = {}
    for name, result in results.items():
        record = asdict(result)
        # DataFrame isn't asdict-JSON-able as-is; to_dict(orient="index") gives
        # {row: {column: value}}, which round-trips through JSON with float keys stringified
        # -- the same shape test_regression.py reads back and compares against a fresh run.
        # These two grids are the ~200 published sensitivity cells that used to be checked
        # only by synthetic unit tests, never against the real, frozen inputs.
        record["sensitivity"] = result.sensitivity.to_dict(orient="index")
        record["margin_sensitivity"] = result.margin_sensitivity.to_dict(orient="index")
        frozen[name] = record

    # newline="" keeps this LF-only on every platform: write_text's default newline
    # translation would otherwise turn every "\n" into "\r\n" on Windows, rewriting a file
    # that is meant to diff cleanly regardless of which OS regenerated it.
    (FIXTURES / "expected_valuations.json").write_text(
        json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline=""
    )
    print(f"fixture written for {len(frozen)} companies")


if __name__ == "__main__":
    main()
