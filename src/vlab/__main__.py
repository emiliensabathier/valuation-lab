"""Command-line entry point: ``python -m vlab``.

This always performs a live fetch (subject to the on-disk cache in ``--cache-dir``), so its
default output deliberately does *not* point at the committed ``reports/valuation.html``: that
file is the artefact the regression suite verifies against the frozen fixture
(``tests/fixtures/``), and a live run silently overwriting it would break that guarantee for
anyone who ran the documented command. Reproduce the committed page with
``scripts/build_frozen_report.py`` instead; pass ``--output reports/valuation.html`` here only
if you deliberately want to replace it with fresh, unfrozen numbers.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from vlab.pipeline import render, run

DEFAULT_OUTPUT = "reports/valuation.local.html"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the valuation report from live data")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached data")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    results, failures = run(cache_dir=Path(args.cache_dir), refresh=args.refresh)
    html = render(results, failures, generated_on=datetime.now(UTC).date().isoformat())

    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    print(f"wrote {destination} ({len(html):,} bytes)")
    if failures:
        for failure in failures:
            print(f"  refused: {failure.name} ({failure.ticker}): {failure.reason}")
        # A refusal is not a crash -- the page above still renders with the companies that
        # could be valued -- but it is not success either. Exiting 0 here would be a silent
        # failure to any script or CI step that only checks the exit code.
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
