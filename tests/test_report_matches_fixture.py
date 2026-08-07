"""The committed report must be exactly what the frozen fixture would produce.

``reports/valuation.html`` is the artefact a reader opens; ``expected_valuations.json`` is the
artefact CI verifies. If the two were built from different inputs -- one from a live fetch, one
from the frozen fixture -- they could quietly disagree, and a reader would be looking at numbers
CI never checked. This test closes that gap: it rebuilds the report through the exact same
``frozen_fetchers()`` the regression suite replays against, and requires the result to match the
committed file byte for byte. See ``scripts/build_frozen_report.py`` for how to regenerate it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.fixtures.frozen import CAPTURED, frozen_fetchers

from vlab.pipeline import render, run

REPORT = Path(__file__).resolve().parents[1] / "reports" / "valuation.html"


def test_the_committed_report_matches_a_fresh_render_of_the_frozen_fixture() -> None:
    statement_fetcher, price_fetcher = frozen_fetchers()
    with tempfile.TemporaryDirectory() as cache_dir:
        results, failures = run(
            cache_dir=Path(cache_dir),
            statement_fetcher=statement_fetcher,
            price_fetcher=price_fetcher,
        )
    assert not failures, failures

    rebuilt = render(results, failures, generated_on=CAPTURED)
    committed = REPORT.read_text(encoding="utf-8")

    assert rebuilt == committed, (
        "reports/valuation.html has drifted from the frozen fixture -- regenerate it with "
        "scripts/build_frozen_report.py"
    )
