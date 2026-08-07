"""Fetchers that replay the frozen inputs, so the pipeline runs with no network."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from vlab.data.loader import Statements
from vlab.errors import DataError

FIXTURES = Path(__file__).parent

# The two cadences production ever requests through ``load_prices``: the five-year weekly
# series (equities, the market index, and the FX history the beta regression needs) and the
# one-month daily series (``load_fx_rate``'s point-in-time conversion). They are captured in
# separate files -- see ``scripts/build_fixture.py`` -- because serving one cadence's data for
# a request asking for the other silently mixes a handful of daily FX closes into the weekly
# beta regression (5 of Richemont's 262 weekly EURCHF closes landed on dates the daily pull
# also covers, and previously overwrote them).
_WEEKLY = ("5y", "1wk")
_DAILY = ("1mo", "1d")

# The date this fixture's statements, prices and FX rates were pulled from the data
# provider. There is no live re-fetch to compare against at test time, so this is the only
# record of provenance: a reader who wants to know how fresh the frozen numbers are has
# nowhere else to look. Update it when scripts/build_fixture.py is re-run deliberately.
CAPTURED = "2026-08-07"


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.columns = pd.DatetimeIndex(frame.columns)
    return frame


class FrozenStatementFetcher:
    """Serves the statements captured when the fixture was built."""

    def __init__(self) -> None:
        self.info = json.loads((FIXTURES / "statements" / "info.json").read_text(encoding="utf-8"))

    def __call__(self, ticker: str) -> Statements:
        safe = ticker.replace(".", "_")
        directory = FIXTURES / "statements"
        return Statements(
            income=_read(directory / f"{safe}_income.csv"),
            cashflow=_read(directory / f"{safe}_cashflow.csv"),
            balance=_read(directory / f"{safe}_balance.csv"),
            info=dict(self.info[ticker]),
        )


class FrozenPriceFetcher:
    """Serves the price and exchange-rate series captured when the fixture was built.

    Two frames, one per cadence (see ``_WEEKLY``/``_DAILY`` above), each holding its columns
    on their own native dates. ``__call__`` picks the frame matching the ``period``/``interval``
    it is asked for -- honouring them, rather than ignoring them and handing back whichever
    cadence happens to be stored, is what keeps a replay from silently reproducing production
    approximately instead of exactly.
    """

    def __init__(self) -> None:
        self.weekly = pd.read_csv(FIXTURES / "prices.csv", index_col=0, parse_dates=True)
        self.daily = pd.read_csv(FIXTURES / "fx_rates_daily.csv", index_col=0, parse_dates=True)

    def __call__(self, tickers: list[str], period: str, interval: str) -> pd.DataFrame:
        if (period, interval) == _DAILY:
            frame = self.daily
        elif (period, interval) == _WEEKLY:
            frame = self.weekly
        else:
            raise DataError(
                f"FrozenPriceFetcher has no frozen series for period={period!r}, "
                f"interval={interval!r}"
            )
        selected = frame.loc[:, [t for t in tickers if t in frame.columns]]
        return selected.dropna()


def frozen_fetchers() -> tuple[FrozenStatementFetcher, FrozenPriceFetcher]:
    return FrozenStatementFetcher(), FrozenPriceFetcher()
