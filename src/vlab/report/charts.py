"""Chart rendering to inline SVG.

Charts are embedded directly in the HTML: the report must open offline, with no CDN and no
external asset of any kind, because it gets opened in an interview room.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

FIGSIZE = (9.0, 4.0)
DPI = 110


def figure_to_svg(fig: Figure) -> str:
    """Serialize a figure as inline SVG markup, stripped of its XML preamble."""
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight")
    markup = buffer.getvalue()
    return markup[markup.index("<svg") :]


def implied_growth_chart(implied: dict[str, float], normalized: dict[str, float]) -> str:
    """Implied growth against the company's own normalized history, side by side.

    This is the chart the report exists for. The gap between the two bars is the question:
    the market is paying for growth above or below what this business has actually delivered.
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
    return figure_to_svg(fig)


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
