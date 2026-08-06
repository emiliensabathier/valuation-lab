"""Regenerate the regression fixture: the raw inputs and the numbers they produce.

Run manually after a deliberate methodology change, never in CI. Regenerating this in an
automated job would silently re-baseline whatever the code currently produces, which is
precisely the guarantee the fixture exists to provide.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from vlab.data.loader import load_prices, load_statements
from vlab.pipeline import run
from vlab.universe import MARKET_INDEX, PEERS, needs_conversion, tickers

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CACHE = Path("cache")


def main() -> None:
    statements_dir = FIXTURES / "statements"
    statements_dir.mkdir(parents=True, exist_ok=True)

    # Freeze the inputs first, so the test can rebuild them without a network.
    info: dict[str, dict] = {}
    for company in PEERS:
        statements = load_statements(company.ticker, cache_dir=CACHE)
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
    # An outer join on each series' own dates, with no fill: the FX pair is fetched at a
    # different cadence (1mo/1d) than the equity prices (5y/1wk), and forward-filling it onto
    # the equity grid silently drops its true latest observation whenever the two grids'
    # last dates don't coincide. FrozenPriceFetcher recovers each column's native rows by
    # dropping the ones the other columns padded with NaN, so a request for the FX pair alone
    # still ends on its own most recent date instead of a stale, equity-grid-aligned one.
    for pair in pairs:
        rate = load_prices([pair], cache_dir=CACHE, period="1mo", interval="1d")
        series = series.join(rate, how="outer")
    series.to_csv(FIXTURES / "prices.csv")

    # Then the outputs, computed from exactly those inputs.
    results, failures = run(cache_dir=CACHE)
    if failures:
        raise RuntimeError(f"cannot freeze a fixture with unresolved failures: {failures}")
    frozen = {}
    for name, result in results.items():
        record = asdict(result)
        record.pop("sensitivity")
        record.pop("margin_sensitivity")
        frozen[name] = record

    (FIXTURES / "expected_valuations.json").write_text(
        json.dumps(frozen, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"fixture written for {len(frozen)} companies")


if __name__ == "__main__":
    main()
