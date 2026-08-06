import pytest

from vlab.errors import DataError
from vlab.pipeline import convert_to_trading_currency
from vlab.universe import Company


def test_a_same_currency_company_is_returned_unchanged() -> None:
    lvmh = Company("MC.PA", "LVMH", "EUR", "EUR")

    assert convert_to_trading_currency(520.0, lvmh, rates={}) == pytest.approx(520.0)


def test_a_cross_currency_company_is_converted() -> None:
    richemont = Company("CFR.SW", "Richemont", "EUR", "CHF")

    converted = convert_to_trading_currency(120.0, richemont, rates={"EURCHF=X": 0.9359})

    assert converted == pytest.approx(120.0 * 0.9359)


def test_a_missing_rate_raises_rather_than_comparing_across_currencies() -> None:
    richemont = Company("CFR.SW", "Richemont", "EUR", "CHF")

    with pytest.raises(DataError, match="EURCHF"):
        convert_to_trading_currency(120.0, richemont, rates={})
