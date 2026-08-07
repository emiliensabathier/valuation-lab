"""Fetchers that replay the frozen inputs, so the pipeline runs with no network."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from vlab.data.loader import Statements

FIXTURES = Path(__file__).parent

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
    """Serves the price and exchange-rate series captured when the fixture was built."""

    def __init__(self) -> None:
        self.frame = pd.read_csv(FIXTURES / "prices.csv", index_col=0, parse_dates=True)

    def __call__(self, tickers: list[str], period: str, interval: str) -> pd.DataFrame:
        # The equity series (5y/1wk) and the FX pairs (1mo/1d) were fetched at different
        # cadences and stored on their own native dates, joined without filling. Selecting
        # the requested columns first and only then dropping incomplete rows restores each
        # column's own grid: an equity-only request keeps the weekly rows, an FX-only request
        # keeps every daily row including its true latest one, unpadded by the other series.
        selected = self.frame.loc[:, [t for t in tickers if t in self.frame.columns]]
        return selected.dropna()


def frozen_fetchers() -> tuple[FrozenStatementFetcher, FrozenPriceFetcher]:
    return FrozenStatementFetcher(), FrozenPriceFetcher()
