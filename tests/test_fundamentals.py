import pandas as pd
import pytest

from vlab.data.loader import Statements
from vlab.errors import DataError, ValuationError
from vlab.fundamentals import drivers_from


def _statements(
    revenue: list[float],
    ebit: list[float],
    *,
    tax: list[float] | None = None,
    pretax: list[float] | None = None,
) -> Statements:
    periods = pd.DatetimeIndex([f"{year}-12-31" for year in range(2025, 2025 - len(revenue), -1)])
    n = len(revenue)
    default_pretax = pretax or [value * 0.9 for value in ebit]
    default_tax = tax or [value * 0.27 for value in ebit]
    income = pd.DataFrame(
        [revenue, ebit, default_pretax, default_tax],
        index=["Total Revenue", "EBIT", "Pretax Income", "Tax Provision"],
        columns=periods,
    )
    cashflow = pd.DataFrame(
        [[-0.06 * value for value in revenue],
         [0.10 * value for value in revenue],
         [-0.01 * value for value in revenue]],
        index=["Capital Expenditure", "Depreciation And Amortization", "Change In Working Capital"],
        columns=periods,
    )
    # Balance-sheet rows deliberately vary across periods. Constant rows would make the
    # net-debt test unable to tell the latest year from the oldest, leaving the same
    # period-selection bug the revenue tests exist to catch entirely uncovered here.
    balance = pd.DataFrame(
        [
            [40.0 + 5.0 * offset for offset in range(n)],
            [15.0 + 2.0 * offset for offset in range(n)],
            [2.0 + 1.0 * offset for offset in range(n)],
            [500.0 + 10.0 * offset for offset in range(n)],
        ],
        index=["Total Debt", "Cash Cash Equivalents And Short Term Investments",
               "Minority Interest", "Ordinary Shares Number"],
        columns=periods,
    )
    return Statements(income, cashflow, balance, {"financialCurrency": "EUR"})


def test_revenue_is_the_latest_reported_year() -> None:
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [20.0, 18.0, 16.0]), "TEST")

    assert drivers.revenue == 100.0


def test_growth_uses_the_median_of_the_year_on_year_rates() -> None:
    # Three fiscal years give exactly two growth observations: 100/90 and 90/80.
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [20.0, 18.0, 16.0]), "TEST")

    expected = ((100.0 / 90.0 - 1.0) + (90.0 / 80.0 - 1.0)) / 2
    assert drivers.revenue_growth == pytest.approx(expected)


def test_a_depressed_final_year_does_not_drive_the_margin() -> None:
    # Kering's shape: four healthy years and a collapse. The median must ignore the outlier,
    # which is the whole reason the drivers are normalized rather than taken from the last year.
    healthy = [100.0, 100.0, 100.0, 100.0, 100.0]
    ebit = [5.0, 25.0, 25.0, 25.0, 25.0]

    drivers = drivers_from(_statements(healthy, ebit), "KER.PA")

    assert drivers.ebit_margin == pytest.approx(0.25)


def test_cash_consuming_ratios_keep_their_reported_negative_sign() -> None:
    drivers = drivers_from(_statements([100.0, 90.0], [20.0, 18.0]), "TEST")

    assert drivers.capex_ratio == pytest.approx(-0.06)
    assert drivers.nwc_ratio == pytest.approx(-0.01)
    assert drivers.da_ratio == pytest.approx(0.10)


def test_the_balance_sheet_is_read_from_the_latest_reported_period() -> None:
    # The fixture's balance rows increase with age, so the oldest period would give
    # net debt 45 - 17 = 28, minorities 3.0 and 510 shares. Asserting the latest values
    # is what pins the period selection rather than merely the arithmetic.
    drivers = drivers_from(_statements([100.0, 90.0], [20.0, 18.0]), "TEST")

    assert drivers.net_debt == pytest.approx(25.0)
    assert drivers.minority_interest == pytest.approx(2.0)
    assert drivers.shares == pytest.approx(500.0)


def test_a_single_reported_year_raises_because_growth_cannot_be_measured() -> None:
    # One fiscal year gives zero year-on-year observations. Returning a zero growth rate
    # would be an invention; the model refuses instead.
    with pytest.raises(ValuationError, match="fewer than two"):
        drivers_from(_statements([100.0], [20.0]), "TEST")


def test_the_effective_tax_rate_is_the_median_of_provision_over_pretax() -> None:
    drivers = drivers_from(
        _statements([100.0, 90.0], [20.0, 18.0], tax=[3.0, 3.0], pretax=[10.0, 10.0]), "TEST"
    )

    assert drivers.tax_rate == pytest.approx(0.30)


def test_a_missing_statement_line_raises_naming_the_ticker() -> None:
    statements = _statements([100.0, 90.0], [20.0, 18.0])
    statements.income.drop(index="EBIT", inplace=True)

    with pytest.raises(DataError, match="MC.PA"):
        drivers_from(statements, "MC.PA")


def test_a_negative_normalized_margin_raises_rather_than_valuing_a_loss_maker() -> None:
    statements = _statements([100.0, 100.0, 100.0], [-5.0, -6.0, -4.0])

    with pytest.raises(ValuationError, match="not positive"):
        drivers_from(statements, "TEST")
