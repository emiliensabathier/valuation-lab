from vlab.universe import MARKET_INDEX, PEERS, needs_conversion, tickers


def test_the_universe_is_four_luxury_peers() -> None:
    assert len(PEERS) == 4
    assert tickers() == ["MC.PA", "RMS.PA", "KER.PA", "CFR.SW"]


def test_the_market_index_is_the_euro_stoxx_50() -> None:
    assert MARKET_INDEX == "^STOXX50E"


def test_richemont_reports_in_euros_but_trades_in_francs() -> None:
    richemont = next(company for company in PEERS if company.ticker == "CFR.SW")

    assert richemont.reporting_currency == "EUR"
    assert richemont.trading_currency == "CHF"
    assert needs_conversion(richemont) is True


def test_the_french_peers_need_no_conversion() -> None:
    for company in PEERS:
        if company.ticker != "CFR.SW":
            assert needs_conversion(company) is False
