"""Command-line entry point: ``python -m vlab``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from vlab.pipeline import render, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the valuation report")
    parser.add_argument("--output", default="reports/valuation.html")
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached data")
    args = parser.parse_args()

    results = run(cache_dir=Path(args.cache_dir), refresh=args.refresh)
    html = render(results, generated_on=datetime.now(UTC).date().isoformat())

    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    print(f"wrote {destination} ({len(html):,} bytes)")


if __name__ == "__main__":  # pragma: no cover
    main()
