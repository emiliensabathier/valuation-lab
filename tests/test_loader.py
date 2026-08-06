import json
from datetime import UTC, datetime, timedelta
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


def _statements_unequal_years() -> Statements:
    """Income and cashflow cover three years; the balance sheet covers only two.

    This is the real shape reported for Kering and Richemont: yfinance's balance sheet
    history is one year shorter than its income and cashflow history. All three frames are
    newest-first, matching how a fresh fetch actually arrives.
    """
    columns = pd.DatetimeIndex(["2025-12-31", "2024-12-31", "2023-12-31"])
    return Statements(
        income=pd.DataFrame(
            {columns[0]: [100.0], columns[1]: [90.0], columns[2]: [80.0]},
            index=["Total Revenue"],
        ),
        cashflow=pd.DataFrame(
            {columns[0]: [-5.0], columns[1]: [-4.0], columns[2]: [-3.0]},
            index=["Capital Expenditure"],
        ),
        balance=pd.DataFrame(
            {columns[0]: [20.0], columns[1]: [18.0]},
            index=["Total Debt"],
        ),
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


@pytest.mark.parametrize("blank", ["income", "cashflow", "balance"])
def test_any_empty_statement_frame_raises(tmp_path: Path, blank: str) -> None:
    # Emptying all three at once would pass against an implementation that only checked
    # the income statement. One blank frame at a time is what pins all three.
    complete = _statements()
    frames = {
        "income": complete.income,
        "cashflow": complete.cashflow,
        "balance": complete.balance,
    }
    frames[blank] = pd.DataFrame()
    fetcher = RecordingFetcher(Statements(**frames, info=complete.info))

    with pytest.raises(DataError, match="no financial statements"):
        load_statements("GHOST", cache_dir=tmp_path, fetcher=fetcher)


def test_a_cached_read_returns_the_same_frames_as_a_fresh_one(tmp_path: Path) -> None:
    # The cache round-trips through parquet, which cannot store timestamp column labels.
    # If they are not restored on read, the two paths return quietly different objects.
    fetcher = RecordingFetcher(_statements())

    fresh = load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)
    cached = load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)

    assert fetcher.calls == 1
    pd.testing.assert_index_equal(cached.income.columns, fresh.income.columns)
    pd.testing.assert_frame_equal(cached.income, fresh.income)


def test_a_cached_read_keeps_column_order_when_statement_shapes_differ(tmp_path: Path) -> None:
    # _statements() gives all three frames the same two years, which never reaches the
    # union/sort path in pd.concat. The real Kering and Richemont statements have a balance
    # sheet one year shorter than income and cashflow, which does: pd.concat's column union
    # sorts the mismatched columns ascending unless told not to, so a cached read came back
    # oldest-first while the fresh fetch that produced it was newest-first. Every driver that
    # reads .iloc[0] as "the latest year" then reads the wrong end of the history.
    fetcher = RecordingFetcher(_statements_unequal_years())

    fresh = load_statements("KER.PA", cache_dir=tmp_path, fetcher=fetcher)
    cached = load_statements("KER.PA", cache_dir=tmp_path, fetcher=fetcher)

    assert fetcher.calls == 1
    pd.testing.assert_index_equal(cached.income.columns, fresh.income.columns)
    assert list(cached.income.columns) == list(fresh.income.columns)


def test_a_stale_cache_entry_is_refetched(tmp_path: Path) -> None:
    # The whole point of recording fetched_at. A sibling project wrote that timestamp and
    # never read it, so a months-old snapshot was served indefinitely while the report
    # presented it as current. This test is what stops that regressing here.
    fetcher = RecordingFetcher(_statements())
    load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)

    sidecar = tmp_path / "MC_PA.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["fetched_at"] = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    sidecar.write_text(json.dumps(meta), encoding="utf-8")

    load_statements("MC.PA", cache_dir=tmp_path, fetcher=fetcher)

    assert fetcher.calls == 2


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


def test_require_raises_a_data_error_on_a_duplicated_statement_line() -> None:
    # A duplicated index label makes frame.loc[line] return a DataFrame instead of a Series
    # -- the one place the error contract breaks, handing a caller a TypeError from
    # downstream arithmetic instead of this module's own DataError.
    columns = pd.DatetimeIndex(["2025-12-31", "2024-12-31"])
    frame = pd.DataFrame(
        {columns[0]: [100.0, 105.0], columns[1]: [90.0, 95.0]},
        index=["Total Revenue", "Total Revenue"],
    )

    with pytest.raises(DataError, match="MC.PA") as excinfo:
        require(frame, "Total Revenue", "MC.PA")

    assert "Total Revenue" in str(excinfo.value)
