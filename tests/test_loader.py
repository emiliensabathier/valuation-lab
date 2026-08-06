from pathlib import Path

import pandas as pd
import pytest

from vlab.data.loader import Statements, load_statements, require
from vlab.errors import DataError


def _statements(revenue: float = 100.0) -> Statements:
    columns = pd.DatetimeIndex(["2025-12-31", "2024-12-31"])
    return Statements(
        income=pd.DataFrame({columns[0]: [revenue], columns[1]: [revenue * 0.9]},
                            index=["Total Revenue"]),
        cashflow=pd.DataFrame({columns[0]: [-5.0], columns[1]: [-4.0]},
                              index=["Capital Expenditure"]),
        balance=pd.DataFrame({columns[0]: [20.0], columns[1]: [18.0]},
                             index=["Total Debt"]),
        info={"currency": "EUR", "financialCurrency": "EUR"},
    )


class RecordingFetcher:
    """Fake fetcher: returns canned statements and counts how often it is called."""

    def __init__(self, statements: Statements) -> None:
        self.statements = statements
        self.calls = 0

    def __call__(self, ticker: str) -> Statements:
        self.calls += 1
        return self.statements


def test_load_statements_returns_the_three_frames(tmp_path: Path) -> None:
    fetcher = RecordingFetcher(_statements())

    loaded = load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)

    assert loaded.income.loc["Total Revenue"].iloc[0] == 100.0
    assert loaded.cashflow.loc["Capital Expenditure"].iloc[0] == -5.0
    assert loaded.balance.loc["Total Debt"].iloc[0] == 20.0
    assert loaded.info["financialCurrency"] == "EUR"


def test_second_call_uses_the_cache(tmp_path: Path) -> None:
    fetcher = RecordingFetcher(_statements())

    load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)
    load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)

    assert fetcher.calls == 1


def test_refresh_bypasses_the_cache(tmp_path: Path) -> None:
    fetcher = RecordingFetcher(_statements())

    load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)
    load_statements("MC.PA", cache_dir=tmp_path, refresh=True, fetcher=fetcher)

    assert fetcher.calls == 2


def test_an_empty_statement_frame_raises(tmp_path: Path) -> None:
    empty = Statements(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {})
    fetcher = RecordingFetcher(empty)

    with pytest.raises(DataError, match="no financial statements"):
        load_statements("GHOST", cache_dir=tmp_path, fetcher=fetcher)


def test_require_returns_the_row_when_present() -> None:
    frame = _statements().income

    row = require(frame, "Total Revenue", "MC.PA")

    assert row.iloc[0] == 100.0


def test_require_names_both_the_ticker_and_the_line_when_absent() -> None:
    frame = _statements().income

    with pytest.raises(DataError) as excinfo:
        require(frame, "Operating Income", "MC.PA")

    assert "MC.PA" in str(excinfo.value)
    assert "Operating Income" in str(excinfo.value)
