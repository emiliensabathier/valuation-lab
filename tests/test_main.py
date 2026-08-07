from pathlib import Path

import pandas as pd

import vlab.__main__ as entry
from vlab.fundamentals import Drivers
from vlab.pipeline import CompanyFailure, CompanyResult


def test_the_cli_writes_a_report(tmp_path: Path, monkeypatch) -> None:
    table = pd.DataFrame([[100.0]], index=[0.09], columns=[0.02])
    drivers = Drivers(
        revenue=1_000_000_000.0, revenue_growth=0.062, ebit_margin=0.24, tax_rate=0.27,
        capex_ratio=-0.05, da_ratio=0.06, nwc_ratio=-0.01, net_debt=5_000_000_000.0,
        minority_interest=0.0, shares=10_000_000.0,
        fiscal_years=("2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"),
    )
    fake = {
        "LVMH": CompanyResult(
            name="LVMH", ticker="MC.PA", reporting_currency="EUR", trading_currency="EUR",
            price=481.45, value_per_share=520.0, implied_growth=0.041, normalized_growth=0.062,
            wacc=0.083, beta=0.84, terminal_share=0.71, exit_multiple=14.2,
            sensitivity=table, margin_sensitivity=table, drivers=drivers,
        )
    }
    monkeypatch.setattr(entry, "run", lambda **kwargs: (fake, []))
    output = tmp_path / "valuation.html"
    monkeypatch.setattr("sys.argv", ["vlab", "--output", str(output)])

    entry.main()

    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_the_cli_prints_every_failure_it_could_not_value(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    failures = [CompanyFailure("Hermes", "RMS.PA", "no revenue growth reproduces the price")]
    monkeypatch.setattr(entry, "run", lambda **kwargs: ({}, failures))
    output = tmp_path / "valuation.html"
    monkeypatch.setattr("sys.argv", ["vlab", "--output", str(output)])

    entry.main()

    printed = capsys.readouterr().out
    assert "Hermes" in printed
    assert "RMS.PA" in printed
    assert "no revenue growth reproduces the price" in printed
