from pathlib import Path

import pandas as pd
import pytest

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
            price=481.45, value_per_share=520.0, implied_growth=0.041,
            implied_average_growth=0.031, normalized_growth=0.062,
            wacc=0.083, beta=0.84, cost_of_equity=0.095, cost_of_debt=0.030,
            equity_weight=0.85, debt_weight=0.15, terminal_share=0.71, exit_multiple=14.2,
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

    with pytest.raises(SystemExit):
        entry.main()

    printed = capsys.readouterr().out
    assert "Hermes" in printed
    assert "RMS.PA" in printed
    assert "no revenue growth reproduces the price" in printed


def test_the_cli_exits_non_zero_when_any_company_was_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """MINOR bug: a refusal that still returns exit code 0 is a silent failure to any script
    or CI step that only checks the exit code. The page must still render -- a refusal is not
    a crash -- but the process must not report success.
    """
    failures = [CompanyFailure("Hermes", "RMS.PA", "no revenue growth reproduces the price")]
    monkeypatch.setattr(entry, "run", lambda **kwargs: ({}, failures))
    output = tmp_path / "valuation.html"
    monkeypatch.setattr("sys.argv", ["vlab", "--output", str(output)])

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code != 0
    assert output.exists()


def test_the_default_output_is_not_the_committed_report() -> None:
    """IMPORTANT bug: the README's documented command relies on --output defaulting to
    reports/valuation.html, so following it verbatim performs a live fetch and silently
    overwrites the committed, fixture-matched page -- breaking the guarantee
    test_report_matches_fixture.py exists to enforce. The default must point somewhere else.
    """
    parser_default = entry.build_parser().get_default("output")

    assert parser_default != "reports/valuation.html"
