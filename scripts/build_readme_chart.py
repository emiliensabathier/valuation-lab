"""Render the one chart the README carries, from the frozen fixture.

GitHub shows a committed HTML file as source, not as a page, so the report's charts are
invisible to anyone browsing the repository. This writes the single figure that makes the
repository's point as a raster the README can embed directly.

Run it after `scripts/build_frozen_report.py`, from the same frozen inputs, so the picture
and the page cannot disagree.

    python scripts/build_readme_chart.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fixtures.frozen import (  # noqa: E402
    CAPTURED,
    FrozenPriceFetcher,
    FrozenStatementFetcher,
)

from vlab.pipeline import run  # noqa: E402
from vlab.report.charts import implied_growth_figure  # noqa: E402

OUTPUT = ROOT / "docs" / "implied-growth.png"
DPI = 130


def main() -> None:
    with tempfile.TemporaryDirectory() as disposable_cache:
        results, failures = run(
            cache_dir=Path(disposable_cache),
            statement_fetcher=FrozenStatementFetcher(),
            price_fetcher=FrozenPriceFetcher(),
        )
    if failures:
        raise RuntimeError(f"cannot draw a chart with unresolved failures: {failures}")

    # The averaged path, not its first year: the bar beside it is a single historical rate.
    implied = {result.name: result.implied_average_growth for result in results.values()}
    normalized = {result.name: result.normalized_growth for result in results.values()}

    figure = implied_growth_figure(implied, normalized)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT, format="png", dpi=DPI, bbox_inches="tight")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes) from the {CAPTURED} capture")


if __name__ == "__main__":  # pragma: no cover
    main()
