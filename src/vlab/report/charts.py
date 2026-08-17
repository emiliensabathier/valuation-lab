"""Chart rendering to inline SVG.

Charts are embedded directly in the HTML: the report must open offline, with no CDN and no
external asset of any kind, because it gets opened in an interview room.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
# Matplotlib's SVG backend salts every clip-path id with a random string by default, so two
# renders of the same figure are never byte-identical. A fixed salt makes them so -- which is
# what lets a test compare the committed report against a fresh render from the frozen
# fixture without tripping on ids that changed for no reason connected to the data.
matplotlib.rcParams["svg.hashsalt"] = "vlab-valuation-lab"
from matplotlib.figure import Figure  # noqa: E402

FIGSIZE = (9.0, 4.0)
DPI = 110


def figure_to_svg(fig: Figure) -> str:
    """Serialize a figure as inline SVG markup, stripped of its XML preamble.

    ``metadata={"Date": None}`` suppresses the embedded creation timestamp, for the same
    reason as the fixed hash salt above: without it, the SVG carries the wall-clock time it
    was rendered, and the report would never reproduce byte-for-byte even from unchanged data.
    """
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", metadata={"Date": None})
    markup = buffer.getvalue()
    return markup[markup.index("<svg") :]


def implied_growth_figure(implied: dict[str, float], normalized: dict[str, float]) -> Figure:
    """Implied growth against the company's own normalized history, side by side.

    This is the chart the report exists for. The gap between the two bars is the question:
    the market is paying for growth above or below what this business has actually delivered.

    ``implied`` is the average over the fading explicit period, not its first year, so both
    bars are the same kind of number.

    Returned as a figure rather than as markup, because the README needs the same chart as a
    raster: GitHub shows a committed HTML report as source.
    """
    names = list(implied)
    positions = range(len(names))
    width = 0.38

    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    axes = fig.add_subplot(111)
    axes.bar([p - width / 2 for p in positions], [implied[n] for n in names], width,
             label="Implied by the market price")
    axes.bar([p + width / 2 for p in positions], [normalized[n] for n in names], width,
             label="Normalized historical growth")
    axes.set_xticks(list(positions))
    axes.set_xticklabels(names)
    axes.set_ylabel("Annual revenue growth")
    axes.set_title("What the market prices in, against what the business has delivered")
    axes.axhline(0.0, linewidth=0.8, color="#444")
    axes.legend(frameon=False)
    axes.grid(True, axis="y", alpha=0.25)
    return fig


def implied_growth_chart(implied: dict[str, float], normalized: dict[str, float]) -> str:
    """The implied-growth chart as inline SVG, for the report."""
    return figure_to_svg(implied_growth_figure(implied, normalized))


def value_bridge_chart(results: dict[str, tuple[float, float]]) -> str:
    """Market price against modelled value per share, in the trading currency."""
    names = list(results)
    positions = range(len(names))
    width = 0.38

    fig = Figure(figsize=FIGSIZE, dpi=DPI)
    axes = fig.add_subplot(111)
    axes.bar([p - width / 2 for p in positions], [results[n][0] for n in names], width,
             label="Market price")
    axes.bar([p + width / 2 for p in positions], [results[n][1] for n in names], width,
             label="Modelled value per share")
    axes.set_xticks(list(positions))
    axes.set_xticklabels(names)
    axes.set_ylabel("Per share, trading currency")
    axes.set_title("Price against model, at the normalized assumptions")
    axes.legend(frameon=False)
    axes.grid(True, axis="y", alpha=0.25)
    return figure_to_svg(fig)
