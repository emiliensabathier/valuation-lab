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
        [revenue, ebit, default_pretax, default_tax, [2.0] * n],
        index=["Total Revenue", "EBIT", "Pretax Income", "Tax Provision", "Interest Expense"],
        columns=periods,
    )
    cashflow = pd.DataFrame(
        [[-0.06 * value for value in revenue],
         [0.10 * value for value in revenue],
         [-0.01 * value for value in revenue],
         [0.0] * n],
        index=["Capital Expenditure", "Depreciation And Amortization", "Change In Working Capital",
               "Sale Of PPE"],
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
            [30.0 - 3.0 * offset for offset in range(n)],
            [6.0 - 0.5 * offset for offset in range(n)],
            [0.20 * value for value in revenue],
            [0.05 * value for value in revenue],
            [0.10 * value for value in revenue],
        ],
        index=["Total Debt", "Cash Cash Equivalents And Short Term Investments",
               "Minority Interest", "Ordinary Shares Number",
               "Capital Lease Obligations", "Current Capital Lease Obligation",
               "Inventory", "Accounts Receivable", "Accounts Payable"],
        columns=periods,
    )
    return Statements(income, cashflow, balance, {"financialCurrency": "EUR"})


def test_revenue_is_the_latest_reported_year() -> None:
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [20.0, 18.0, 16.0]), "TEST")

    assert drivers.revenue == 100.0


def test_fiscal_years_records_the_reported_window_oldest_first() -> None:
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [20.0, 18.0, 16.0]), "TEST")

    assert drivers.fiscal_years == ("2023-12-31", "2024-12-31", "2025-12-31")


def test_fiscal_years_excludes_a_column_with_no_reported_revenue() -> None:
    # Real statements can carry a column with no revenue reported in it at all (an unusable
    # oldest year) alongside populated ones -- exactly the shape of the four real companies'
    # frozen fixtures, which report five columns but only four with revenue. fiscal_years must
    # reflect the years actually usable for the normalization, not the full width of the frame.
    periods = pd.DatetimeIndex(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    income = pd.DataFrame(
        [[100.0, 90.0, 80.0, float("nan")],
         [20.0, 18.0, 16.0, 14.0],
         [18.0, 16.2, 14.4, 12.6],
         [4.86, 4.374, 3.888, 3.402],
         [2.0, 2.0, 2.0, 2.0]],
        index=["Total Revenue", "EBIT", "Pretax Income", "Tax Provision", "Interest Expense"],
        columns=periods,
    )
    cashflow = pd.DataFrame(
        [[-6.0, -5.4, -4.8, -4.2], [10.0, 9.0, 8.0, 7.0], [-1.0, -0.9, -0.8, -0.7],
         [0.0, 0.0, 0.0, 0.0]],
        index=["Capital Expenditure", "Depreciation And Amortization", "Change In Working Capital",
               "Sale Of PPE"],
        columns=periods,
    )
    balance = pd.DataFrame(
        [[40.0, 45.0, 50.0, 55.0], [15.0, 17.0, 19.0, 21.0], [2.0, 3.0, 4.0, 5.0],
         [500.0, 510.0, 520.0, 530.0], [30.0, 27.0, 24.0, 21.0], [6.0, 5.5, 5.0, 4.5],
         [20.0, 18.0, 16.0, 14.0], [5.0, 4.5, 4.0, 3.5], [10.0, 9.0, 8.0, 7.0]],
        index=["Total Debt", "Cash Cash Equivalents And Short Term Investments",
               "Minority Interest", "Ordinary Shares Number",
               "Capital Lease Obligations", "Current Capital Lease Obligation",
               "Inventory", "Accounts Receivable", "Accounts Payable"],
        columns=periods,
    )
    statements = Statements(income, cashflow, balance, {"financialCurrency": "EUR"})

    drivers = drivers_from(statements, "TEST")

    assert drivers.fiscal_years == ("2023-12-31", "2024-12-31", "2025-12-31")


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
    assert drivers.da_ratio == pytest.approx(0.10)


def test_working_capital_intensity_is_inventory_plus_receivables_less_payables() -> None:
    # 20% + 5% - 10% of revenue in every year of the helper.
    drivers = drivers_from(_statements([100.0, 90.0], [20.0, 18.0]), "TEST")

    assert drivers.nwc_intensity == pytest.approx(0.15)


def test_working_capital_intensity_is_the_median_of_the_yearly_ratios() -> None:
    statements = _statements([100.0, 100.0, 100.0], [20.0, 20.0, 20.0])
    statements.balance.loc["Inventory"] = [10.0, 40.0, 20.0]
    statements.balance.loc["Accounts Receivable"] = [0.0, 0.0, 0.0]
    statements.balance.loc["Accounts Payable"] = [0.0, 0.0, 0.0]

    drivers = drivers_from(statements, "TEST")

    assert drivers.nwc_intensity == pytest.approx(0.20)


def test_a_missing_inventory_line_is_refused_rather_than_read_as_zero() -> None:
    statements = _statements([100.0, 90.0], [20.0, 18.0])
    statements = Statements(
        statements.income, statements.cashflow, statements.balance.drop(index="Inventory"),
        statements.info,
    )

    with pytest.raises(DataError):
        drivers_from(statements, "TEST")


def test_capex_is_pooled_over_the_window_net_of_property_disposals() -> None:
    # Kering's shape: property bought in two years and largely sold back in the last one. A
    # median of yearly gross ratios keeps the purchases and ignores the sale; pooling capex net
    # of disposals over the window charges only what the company kept.
    statements = _statements([100.0, 100.0, 100.0, 100.0], [20.0, 20.0, 20.0, 20.0])
    statements.cashflow.loc["Capital Expenditure"] = [-5.0, -20.0, -15.0, -5.0]
    statements.cashflow.loc["Sale Of PPE"] = [15.0, 0.0, 0.0, 0.0]

    drivers = drivers_from(statements, "KER.PA")

    assert drivers.capex_ratio == pytest.approx((-45.0 + 15.0) / 400.0)
    # The yearly history stays gross, so the report can still show the purchases.
    assert drivers.capex_ratios == pytest.approx((-0.05, -0.15, -0.20, -0.05))


def test_a_missing_disposals_line_raises_rather_than_counting_as_zero() -> None:
    statements = _statements([100.0, 90.0], [20.0, 18.0])
    statements.cashflow.drop(index="Sale Of PPE", inplace=True)

    with pytest.raises(DataError, match="Sale Of PPE"):
        drivers_from(statements, "MC.PA")


def test_the_balance_sheet_is_read_from_the_latest_reported_period() -> None:
    # The fixture's balance rows change with age, so the oldest period would give
    # net debt 45 - 27 - 17 = 1, minorities 3.0 and 510 shares. Asserting the latest values
    # is what pins the period selection rather than merely the arithmetic.
    drivers = drivers_from(_statements([100.0, 90.0], [20.0, 18.0]), "TEST")

    # Total debt 40, less 30 of lease liabilities (paid through the lease charge in the cash
    # flow instead), less 15 of cash.
    assert drivers.net_debt == pytest.approx(-5.0)
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


def test_lease_payments_are_charged_as_principal_plus_after_tax_interest_over_revenue() -> None:
    # Lease liabilities are taken out of net debt, so the cash a company pays its landlords
    # has to come out of the free cash flow instead. The data source reports no lease-payment
    # line; it is rebuilt from the balance sheet and the income statement:
    #   principal: last year's current portion of the lease liability (due within the year)
    #   interest:  reported interest x lease liability / total debt, after tax at 30%
    #   latest year: 5.5 + 2.0 x 30/40 x 0.7 = 6.55 on revenue 100
    #   prior year:  5.0 + 2.0 x 27/45 x 0.7 = 5.84 on revenue 90
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [20.0, 18.0, 16.0]), "TEST")

    expected = -(6.55 / 100.0 + 5.84 / 90.0) / 2
    assert drivers.lease_ratio == pytest.approx(expected)


def test_a_missing_lease_line_raises_rather_than_treating_leases_as_free() -> None:
    statements = _statements([100.0, 90.0], [20.0, 18.0])
    statements.balance.drop(index="Current Capital Lease Obligation", inplace=True)

    with pytest.raises(DataError, match="Current Capital Lease Obligation"):
        drivers_from(statements, "MC.PA")


def test_the_yearly_history_behind_each_median_is_kept_oldest_first() -> None:
    drivers = drivers_from(_statements([100.0, 90.0, 80.0], [10.0, 18.0, 24.0]), "TEST")

    assert drivers.ebit_margins == pytest.approx((0.30, 0.20, 0.10))
    assert drivers.revenue_growths == pytest.approx((90.0 / 80.0 - 1.0, 100.0 / 90.0 - 1.0))
    assert drivers.capex_ratios == pytest.approx((-0.06, -0.06, -0.06))


def test_a_single_lease_balance_raises_because_no_payment_can_be_inferred() -> None:
    statements = _statements([100.0, 90.0], [20.0, 18.0])
    balance = statements.balance.copy()
    balance.loc["Current Capital Lease Obligation"] = [6.0, float("nan")]

    with pytest.raises(ValuationError, match="lease payments"):
        drivers_from(Statements(statements.income, statements.cashflow, balance, {}), "TEST")
