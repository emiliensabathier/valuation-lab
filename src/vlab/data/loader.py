"""Financial statement loading with an on-disk parquet cache.

The fetcher is injected so the whole module is testable without network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

from vlab.errors import DataError

# Statements are annual and revised at most a few times a year, so a week-old cache is
# still current. The staleness check exists so a cache is refreshed rather than trusted
# indefinitely, which is what happens when nothing ever reads the fetch timestamp.
CACHE_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class Statements:
    """The three annual statements plus the ticker's summary info, as reported."""

    income: pd.DataFrame
    cashflow: pd.DataFrame
    balance: pd.DataFrame
    info: dict[str, object]


class StatementFetcher(Protocol):
    """Retrieves the annual statements for one ticker."""

    def __call__(self, ticker: str) -> Statements: ...


def yfinance_fetcher(ticker: str) -> Statements:
    """Default fetcher."""
    import yfinance as yf

    handle = yf.Ticker(ticker)
    return Statements(
        income=handle.financials,
        cashflow=handle.cashflow,
        balance=handle.balance_sheet,
        info=dict(handle.info),
    )


def require(frame: pd.DataFrame, line: str, ticker: str) -> pd.Series:
    """Return one statement line, or raise naming both the ticker and the missing line.

    Statement layouts differ between issuers and change between yfinance releases, so a
    missing line is routine — and silently treating it as zero would quietly change the
    valuation rather than stopping.
    """
    if line not in frame.index:
        raise DataError(f"{ticker}: statement line {line!r} is not reported")
    return frame.loc[line]


def _paths(cache_dir: Path, ticker: str) -> tuple[Path, Path]:
    safe = ticker.replace(".", "_").replace("^", "idx_")
    return cache_dir / f"{safe}.parquet", cache_dir / f"{safe}.json"


def _read_cached(cache_dir: Path, ticker: str) -> Statements | None:
    data_path, meta_path = _paths(cache_dir, ticker)
    if not (data_path.exists() and meta_path.exists()):
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    fetched_at = datetime.fromisoformat(str(meta["fetched_at"]))
    if datetime.now(UTC) - fetched_at > CACHE_MAX_AGE:
        return None

    stacked = pd.read_parquet(data_path)
    frames = {
        name: stacked.loc[name].dropna(axis=1, how="all")
        for name in ("income", "cashflow", "balance")
    }
    # Parquet cannot carry timestamp column labels, so _write_cache stringified them.
    # Restoring them here is what keeps the two return paths interchangeable: without it a
    # cache hit hands later tasks string columns where a fresh fetch hands them timestamps,
    # and the difference surfaces far from its cause.
    for frame in frames.values():
        frame.columns = pd.DatetimeIndex(frame.columns)

    return Statements(
        income=frames["income"],
        cashflow=frames["cashflow"],
        balance=frames["balance"],
        info=dict(meta["info"]),
    )


def _write_cache(cache_dir: Path, ticker: str, statements: Statements) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _paths(cache_dir, ticker)

    stacked = pd.concat(
        {
            "income": statements.income,
            "cashflow": statements.cashflow,
            "balance": statements.balance,
        }
    )
    stacked.columns = [str(column) for column in stacked.columns]
    stacked.to_parquet(data_path)

    meta_path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "info": {str(k): v for k, v in statements.info.items() if _is_jsonable(v)},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _is_jsonable(value: object) -> bool:
    return isinstance(value, str | int | float | bool | type(None))


def load_statements(
    ticker: str,
    *,
    cache_dir: Path,
    refresh: bool = False,
    fetcher: StatementFetcher | None = None,
) -> Statements:
    """Load the annual statements for ``ticker``, from cache when it is fresh."""
    fetch = fetcher if fetcher is not None else yfinance_fetcher
    cache_dir = Path(cache_dir)

    if not refresh:
        cached = _read_cached(cache_dir, ticker)
        if cached is not None:
            return cached

    statements = fetch(ticker)
    if statements.income.empty or statements.cashflow.empty or statements.balance.empty:
        raise DataError(f"{ticker}: no financial statements returned")

    _write_cache(cache_dir, ticker, statements)
    return statements


class PriceFetcher(Protocol):
    """Retrieves close prices for the given tickers."""

    def __call__(self, tickers: list[str], period: str, interval: str) -> pd.DataFrame: ...


def yfinance_price_fetcher(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    """Default price fetcher. Returns close prices, one column per ticker."""
    import yfinance as yf

    raw = yf.download(
        tickers, period=period, interval=interval, auto_adjust=True, progress=False
    )
    if raw.empty:
        raise DataError(f"no prices returned for {tickers}")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    return close


def load_prices(
    tickers: list[str],
    *,
    cache_dir: Path,
    period: str = "5y",
    interval: str = "1wk",
    refresh: bool = False,
    fetcher: PriceFetcher | None = None,
) -> pd.DataFrame:
    """Load close prices. Raises on a missing ticker or a gap; never fills."""
    fetch = fetcher if fetcher is not None else yfinance_price_fetcher
    cache_dir = Path(cache_dir)
    key = "prices_" + "_".join(sorted(tickers)) + f"_{period}_{interval}"

    if not refresh:
        cached = _read_cached_frame(cache_dir, key)
        if cached is not None:
            # The cache key sorts the tickers, so the same set requested in a different
            # order hits the same entry. Restore the caller's order before returning:
            # otherwise a cache hit hands back columns that are positionally mislabelled
            # against what was asked for.
            return cached.loc[:, list(tickers)]

    fetched = fetch(list(tickers), period, interval)
    missing = [ticker for ticker in tickers if ticker not in fetched.columns]
    if missing:
        raise DataError(f"no price series returned for {missing}")

    prices = fetched.loc[:, list(tickers)].sort_index()
    incomplete = prices.columns[prices.isna().any()].tolist()
    if incomplete:
        raise DataError(f"missing price observations for {incomplete}; refusing to fill gaps")

    _write_cache_frame(cache_dir, key, prices)
    return prices


def load_fx_rate(
    pair: str,
    *,
    cache_dir: Path,
    refresh: bool = False,
    fetcher: PriceFetcher | None = None,
) -> float:
    """Latest close for an exchange-rate pair such as ``EURCHF=X``."""
    prices = load_prices(
        [pair], cache_dir=cache_dir, period="1mo", interval="1d", refresh=refresh, fetcher=fetcher
    )
    return float(prices[pair].iloc[-1])


def _read_cached_frame(cache_dir: Path, key: str) -> pd.DataFrame | None:
    data_path, meta_path = _paths(cache_dir, key)
    if not (data_path.exists() and meta_path.exists()):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    fetched_at = datetime.fromisoformat(str(meta["fetched_at"]))
    if datetime.now(UTC) - fetched_at > CACHE_MAX_AGE:
        return None
    return pd.read_parquet(data_path)


def _write_cache_frame(cache_dir: Path, key: str, frame: pd.DataFrame) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_path, meta_path = _paths(cache_dir, key)
    frame.to_parquet(data_path)
    meta_path.write_text(
        json.dumps({"fetched_at": datetime.now(UTC).isoformat()}, indent=2), encoding="utf-8"
    )
