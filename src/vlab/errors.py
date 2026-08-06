"""Exception types shared across the package.

Two kinds of failure, deliberately distinct. A DataError means the inputs are missing or
unusable. A ValuationError means the inputs are fine but the model cannot produce a number
it would be honest to publish.
"""


class DataError(Exception):
    """Raised when financial data is missing, incomplete or unusable."""


class ValuationError(Exception):
    """Raised when the model cannot produce a defensible valuation."""
