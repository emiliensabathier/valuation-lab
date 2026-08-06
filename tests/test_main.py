from pathlib import Path

import pandas as pd

import vlab.__main__ as entry
from vlab.pipeline import CompanyResult


def test_the_cli_writes_a_report(tmp_path: Path, monkeypatch) -> None:
    table = pd.DataFrame([[100.0]], index=[0.09], columns=[0.02])
    fake = {
        "LVMH": CompanyResult(
            name="LVMH", ticker="MC.PA", trading_currency="EUR", price=481.45,
            value_per_share=520.0, implied_growth=0.041, normalized_growth=0.062,
            wacc=0.083, beta=0.84, terminal_share=0.71, exit_multiple=14.2,
            sensitivity=table, margin_sensitivity=table,
        )
    }
    monkeypatch.setattr(entry, "run", lambda **kwargs: (fake, []))
    output = tmp_path / "valuation.html"
    monkeypatch.setattr("sys.argv", ["vlab", "--output", str(output)])

    entry.main()

    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
