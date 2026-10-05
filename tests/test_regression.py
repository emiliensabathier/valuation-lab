import json
import math
from pathlib import Path

import pandas as pd
import pytest
from tests.fixtures.frozen import FrozenPriceFetcher, frozen_fetchers

from vlab.pipeline import CompanyResult, run

FIXTURES = Path(__file__).parent / "fixtures"

# Deterministic arithmetic reproduces exactly. The implied growth comes out of a Brent root
# find, whose last digits depend on the platform's floating-point library, so it gets a
# looser but still meaningful bound: a real methodology change moves it by percent.
TOLERANCE_EXACT = 1e-9
TOLERANCE_SOLVED = 1e-6
SOLVED_FIELDS = {"implied_growth", "implied_average_growth"}


@pytest.fixture(scope="module")
def expected() -> dict[str, dict[str, float]]:
    return json.loads((FIXTURES / "expected_valuations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_results(tmp_path_factory) -> dict[str, CompanyResult]:
    """Replay the whole pipeline against the frozen inputs, with no network.

    Kept separate from ``recomputed`` below so both the scalar-field comparison and the
    sensitivity-grid comparison read off one pipeline run instead of two.
    """
    statements, prices = frozen_fetchers()
    results, failures = run(
        cache_dir=tmp_path_factory.mktemp("cache"),
        statement_fetcher=statements,
        price_fetcher=prices,
    )
    assert not failures, failures
    return results


@pytest.fixture(scope="module")
def recomputed(raw_results: dict[str, CompanyResult]) -> dict[str, dict[str, float]]:
    return {
        name: {
            field: getattr(result, field)
            for field in (
                "trading_currency", "price", "value_per_share", "implied_growth",
                "normalized_growth", "wacc", "beta", "terminal_share", "exit_multiple",
                "implied_average_growth", "valuation_lag",
            )
        }
        for name, result in raw_results.items()
    }


def _assert_grid_matches_fixture(
    actual: pd.DataFrame, expected: dict[str, dict[str, float | None]]
) -> None:
    """Compare a recomputed sensitivity grid against its frozen ``{row: {column: value}}``.

    Keys round-trip through JSON as strings (``str(0.0656)`` is exact for these values, since
    Python's float-to-str is the shortest round-tripping representation), so both axes are
    restated as strings before comparing rather than trusting key order or count alone.
    """
    assert {str(row) for row in actual.index} == set(expected)
    for row in actual.index:
        expected_row = expected[str(row)]
        assert {str(column) for column in actual.columns} == set(expected_row)
        for column in actual.columns:
            actual_value = actual.loc[row, column]
            reference = expected_row[str(column)]
            if pd.isna(actual_value):
                assert reference is None or math.isnan(reference)
            else:
                assert actual_value == pytest.approx(reference, rel=TOLERANCE_EXACT)


def test_the_fixture_covers_every_peer(expected: dict[str, dict[str, float]]) -> None:
    assert set(expected) == {"LVMH", "Hermes", "Kering", "Richemont"}


def test_frozen_price_fetcher_honours_the_requested_cadence_for_richemonts_fx_pair() -> None:
    """IMPORTANT bug: FrozenPriceFetcher ignored the ``period``/``interval`` it was called
    with and always served the same merged column, regardless of which cadence asked for it.
    Production requests EURCHF=X through two different calls -- 5y/1wk for the beta
    regression, 1mo/1d for the point-in-time conversion -- and 5 of the 262 weekly dates fall
    inside the daily window too. Ignoring the cadence let the daily-cadence close silently
    overwrite the weekly-cadence one on those 5 dates, pairing a Friday-cadence equity close
    with a Monday-cadence rate. The fetcher must return the series actually requested.
    """
    fetcher = FrozenPriceFetcher()
    pair = "EURCHF=X"

    weekly = fetcher([pair], "5y", "1wk")[pair]
    daily = fetcher([pair], "1mo", "1d")[pair]

    overlap = weekly.index.intersection(daily.index)
    assert len(overlap) > 0, "fixture no longer has overlapping dates to distinguish cadences"
    # Genuinely different data per cadence, not a single merged series served twice.
    assert not weekly.loc[overlap].equals(daily.loc[overlap])


def test_the_pipeline_still_produces_the_published_numbers(
    recomputed: dict[str, dict[str, float]], expected: dict[str, dict[str, float]]
) -> None:
    # The point of the fixture. Reading the frozen file and asserting its own values are
    # plausible would pass no matter what the code did; recomputing them from the frozen
    # inputs is what makes a methodology change fail here rather than in a reader's hands.
    assert set(recomputed) == set(expected)

    for name, record in recomputed.items():
        for field, actual in record.items():
            reference = expected[name][field]
            if isinstance(actual, str):
                assert actual == reference, (name, field)
                continue
            tolerance = TOLERANCE_SOLVED if field in SOLVED_FIELDS else TOLERANCE_EXACT
            assert actual == pytest.approx(reference, rel=tolerance), (name, field)


def test_every_company_reports_a_plausible_beta(recomputed: dict[str, dict[str, float]]) -> None:
    # A beta outside this range on a large-cap luxury house means the regression against the
    # index went wrong, not that the business changed.
    for name, record in recomputed.items():
        assert 0.3 < record["beta"] < 2.0, name


def test_the_terminal_value_does_not_swallow_the_whole_valuation(
    recomputed: dict[str, dict[str, float]],
) -> None:
    # A terminal share above 95% would mean the explicit forecast is decoration.
    for name, record in recomputed.items():
        assert 0.4 < record["terminal_share"] < 0.95, name


def test_richemont_is_valued_in_its_trading_currency(
    recomputed: dict[str, dict[str, float]],
) -> None:
    assert recomputed["Richemont"]["trading_currency"] == "CHF"


def test_the_sensitivity_grids_match_the_frozen_fixture(
    raw_results: dict[str, CompanyResult], expected: dict[str, dict[str, float]]
) -> None:
    # The published report shows two five-by-five grids per company -- 200 cells across the
    # four companies -- that used to be checked only by sensitivity.py's own synthetic unit
    # tests, never against these companies' real, frozen inputs. A transposed grid or a wrong
    # axis default would pass every other test in this file and still put a wrong number in
    # front of a reader.
    for name, result in raw_results.items():
        _assert_grid_matches_fixture(result.sensitivity, expected[name]["sensitivity"])
        _assert_grid_matches_fixture(
            result.margin_sensitivity, expected[name]["margin_sensitivity"]
        )


def test_the_implied_growth_at_a_lower_wacc_matches_the_frozen_fixture(
    raw_results: dict[str, CompanyResult], expected: dict[str, dict[str, float]]
) -> None:
    # The report's answer to "what if the discount rate is too high" is a published number
    # too; a change that moved it would otherwise reach a reader unchecked.
    for name, result in raw_results.items():
        frozen = expected[name]["implied_average_growth_at_lower_wacc"]
        assert {str(step) for step in result.implied_average_growth_at_lower_wacc} == set(frozen)
        for step, growth in result.implied_average_growth_at_lower_wacc.items():
            assert growth == pytest.approx(frozen[str(step)], rel=TOLERANCE_SOLVED), (name, step)
