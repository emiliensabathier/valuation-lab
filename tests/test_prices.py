from pathlib import Path

import pandas as pd
import pytest

from vlab.data.loader import load_fx_rate, load_prices
from vlab.errors import DataError


class RecordingPriceFetcher:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = 0

    def __call__(self, tickers, period, interval):
        self.calls += 1
        available = [ticker for ticker in tickers if ticker in self.frame.columns]
        return self.frame.loc[:, available]


def _weekly(columns: dict[str, list[float]]) -> pd.DataFrame:
    index = pd.bdate_range("2021-01-01", periods=len(next(iter(columns.values()))), freq="W-FRI")
    return pd.DataFrame(columns, index=index)


def test_load_prices_returns_the_requested_columns(tmp_path: Path) -> None:
    fetcher = RecordingPriceFetcher(_weekly({"MC.PA": [1.0, 2.0, 3.0], "RMS.PA": [4.0, 5.0, 6.0]}))

    prices = load_prices(["MC.PA", "RMS.PA"], cache_dir=tmp_path, fetcher=fetcher)

    assert list(prices.columns) == ["MC.PA", "RMS.PA"]
    assert prices["RMS.PA"].iloc[-1] == 6.0


def test_a_missing_ticker_raises(tmp_path: Path) -> None:
    fetcher = RecordingPriceFetcher(_weekly({"MC.PA": [1.0, 2.0, 3.0]}))

    with pytest.raises(DataError, match="GHOST"):
        load_prices(["GHOST"], cache_dir=tmp_path, fetcher=fetcher)


def test_a_gap_in_a_price_series_raises(tmp_path: Path) -> None:
    fetcher = RecordingPriceFetcher(_weekly({"MC.PA": [1.0, float("nan"), 3.0]}))

    with pytest.raises(DataError, match="missing"):
        load_prices(["MC.PA"], cache_dir=tmp_path, fetcher=fetcher)


def test_load_fx_rate_returns_the_latest_close(tmp_path: Path) -> None:
    fetcher = RecordingPriceFetcher(_weekly({"EURCHF=X": [0.94, 0.93, 0.9359]}))

    rate = load_fx_rate("EURCHF=X", cache_dir=tmp_path, fetcher=fetcher)

    assert rate == pytest.approx(0.9359)
