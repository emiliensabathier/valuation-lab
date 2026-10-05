"""Render the committed report from the frozen fixture, not a live fetch.

Run manually after regenerating ``tests/fixtures/expected_valuations.json`` (see
``build_fixture.py``), or after any change to ``report/build.py`` or ``report/charts.py``.

The point: ``reports/valuation.html`` is what a reader opens, and ``expected_valuations.json``
is what the regression suite checks. If the committed page came from a live ``vlab`` run
instead, the two could quietly disagree -- exactly the gap ``test_report_matches_fixture.py``
now exists to close. Building the page through the same ``frozen_fetchers()`` the tests use is
what keeps that gap from reopening.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# tests/ has no __init__.py; it is only importable as "tests.fixtures.frozen" when the repo
# root sits on sys.path, which pytest arranges for the test suite but a standalone script
# invocation (``python scripts/build_frozen_report.py``) does not.
sys.path.insert(0, str(ROOT))

from tests.fixtures.frozen import CAPTURED, frozen_fetchers  # noqa: E402

from vlab.pipeline import render, run  # noqa: E402

DESTINATION = ROOT / "reports" / "valuation.html"


def main() -> None:
    statement_fetcher, price_fetcher = frozen_fetchers()
    with tempfile.TemporaryDirectory() as cache_dir:
        # A disposable cache directory, not the project's real cache/: load_statements and
        # load_prices check an on-disk cache *before* calling the injected fetcher, regardless
        # of which fetcher was passed. Pointing this at the real cache/ would risk serving a
        # fresh-enough live pull instead of the frozen fixture -- and, on a cache miss, would
        # overwrite that real cache with frozen data, making the next live `vlab` run silently
        # serve stale frozen (CAPTURED) numbers until the cache expired.
        results, failures = run(
            cache_dir=Path(cache_dir),
            statement_fetcher=statement_fetcher,
            price_fetcher=price_fetcher,
        )
    if failures:
        raise RuntimeError(f"cannot publish a report with unresolved failures: {failures}")

    html = render(results, failures, generated_on=CAPTURED)
    DESTINATION.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {DESTINATION} ({len(html):,} bytes) from the frozen fixture ({CAPTURED})")


if __name__ == "__main__":
    main()
