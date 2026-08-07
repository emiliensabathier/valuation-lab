"""Regenerate the regression fixture: the raw inputs and the numbers they produce.

Run manually after a deliberate methodology change, never in CI. Regenerating this in an
automated job would silently re-baseline whatever the code currently produces, which is
precisely the guarantee the fixture exists to provide.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from vlab.data.loader import Statements, load_prices, load_statements
from vlab.pipeline import run
from vlab.universe import MARKET_INDEX, PEERS, needs_conversion, tickers

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CACHE = Path("cache")


def main() -> None:
    statements_dir = FIXTURES / "statements"
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
    # Two different windows of the same pair, merged into one column. The 1mo/1d window feeds
    # load_fx_rate's point-in-time conversion (the freshest close available); the 5y/1wk window
    # -- the same period and cadence as the equity prices above -- feeds levered_beta's
    # currency conversion, which needs a rate for every date in the regression, not just the
    # latest one. combine_first prefers the daily window's more recent closes and falls back to
    # the weekly window for the rest of the history.
    #
    # An outer join onto ``series`` on each series' own dates, with no fill: forward-filling
    # the combined FX column onto the equity grid would silently drop its true latest
    # observation whenever the grids' last dates don't coincide. FrozenPriceFetcher recovers
    # each column's native rows by dropping the ones the other columns padded with NaN, so a
    # request for the FX pair alone still ends on its own most recent date instead of a stale,
    # equity-grid-aligned one.
    for pair in pairs:
        long_history = load_prices([pair], cache_dir=CACHE)[pair]
        latest = load_prices([pair], cache_dir=CACHE, period="1mo", interval="1d")[pair]
        combined = latest.combine_first(long_history).rename(pair)
        series = series.join(combined, how="outer")
    series.to_csv(FIXTURES / "prices.csv")

    # Then the outputs, computed from exactly those frozen inputs -- not from a second,
    # independent read of the live cache. Richemont's beta reads the EURCHF pair through two
    # separate calls at two different cadences (the point-in-time rate and the full history);
    # replaying against ``series`` itself, the same combined frame just written to
    # ``prices.csv``, is what guarantees expected_valuations.json matches what
    # tests/fixtures/frozen.py's FrozenPriceFetcher will hand back later.
    #
    # A disposable, empty cache_dir is required here, not CACHE: load_prices and
    # load_statements check their on-disk cache *before* calling an injected fetcher, so
    # pointing this run at the real, already-populated cache/ would silently skip both
    # fetchers below and read the live per-cadence cache files instead -- the exact
    # inconsistency this replay exists to prevent (see build_frozen_report.py's identical
    # reasoning for the same pattern).
    def _frozen_price_fetcher(requested: list[str], _period: str, _interval: str):
        selected = series.loc[:, [t for t in requested if t in series.columns]]
        return selected.dropna()

    def _frozen_statement_fetcher(ticker: str) -> Statements:
        return statements_by_ticker[ticker]

    with tempfile.TemporaryDirectory() as disposable_cache:
        results, failures = run(
            cache_dir=Path(disposable_cache),
            statement_fetcher=_frozen_statement_fetcher,
            price_fetcher=_frozen_price_fetcher,
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
