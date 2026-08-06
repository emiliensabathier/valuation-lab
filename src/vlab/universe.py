"""The peer universe.

Four European luxury houses. The set is deliberately small and genuinely comparable: the
reverse DCF is only interesting when the companies face the same demand, so that a spread in
implied growth says something about the market's view rather than about their industries.
"""

from __future__ import annotations

from dataclasses import dataclass

MARKET_INDEX = "^STOXX50E"


@dataclass(frozen=True)
class Company:
    """One listed company, with the two currencies that must not be confused."""

    ticker: str
    name: str
    reporting_currency: str
    trading_currency: str


PEERS: tuple[Company, ...] = (
    Company("MC.PA", "LVMH", "EUR", "EUR"),
    Company("RMS.PA", "Hermes", "EUR", "EUR"),
    Company("KER.PA", "Kering", "EUR", "EUR"),
    # Richemont publishes in euros and trades in Swiss francs. Comparing a per-share value
    # in one currency against a price in the other is a silent, plausible-looking error.
    Company("CFR.SW", "Richemont", "EUR", "CHF"),
)


def tickers() -> list[str]:
    """Ticker symbols in declaration order."""
    return [company.ticker for company in PEERS]


def needs_conversion(company: Company) -> bool:
    """Whether a valuation must be converted before it can be compared to the share price."""
    return company.reporting_currency != company.trading_currency
