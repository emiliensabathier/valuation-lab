import json
from pathlib import Path

import pytest
from tests.fixtures.frozen import frozen_fetchers

from vlab.pipeline import run

FIXTURES = Path(__file__).parent / "fixtures"

# Deterministic arithmetic reproduces exactly. The implied growth comes out of a Brent root
# find, whose last digits depend on the platform's floating-point library, so it gets a
# looser but still meaningful bound: a real methodology change moves it by percent.
TOLERANCE_EXACT = 1e-9
TOLERANCE_SOLVED = 1e-6
SOLVED_FIELDS = {"implied_growth"}


@pytest.fixture(scope="module")
def expected() -> dict[str, dict[str, float]]:
    return json.loads((FIXTURES / "expected_valuations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recomputed(tmp_path_factory) -> dict[str, dict[str, float]]:
    """Replay the whole pipeline against the frozen inputs, with no network."""
    statements, prices = frozen_fetchers()
    results = run(
        cache_dir=tmp_path_factory.mktemp("cache"),
        statement_fetcher=statements,
        price_fetcher=prices,
    )
    return {
        name: {
            field: getattr(result, field)
            for field in (
                "trading_currency", "price", "value_per_share", "implied_growth",
                "normalized_growth", "wacc", "beta", "terminal_share", "exit_multiple",
            )
        }
        for name, result in results.items()
    }


def test_the_fixture_covers_every_peer(expected: dict[str, dict[str, float]]) -> None:
    assert set(expected) == {"LVMH", "Hermes", "Kering", "Richemont"}


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
