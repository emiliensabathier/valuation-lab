# valuation-lab

Discounted cash flow valuation of four European luxury houses, then inverted: what growth
does each share price already imply?

![ci](https://github.com/emiliensabathier/valuation-lab/actions/workflows/ci.yml/badge.svg)

## Results

Unlevered free cash flow, five explicit years, Gordon terminal value. Betas recomputed from
five years of weekly returns against the Euro Stoxx 50.

| Company | Price | Modelled value | Implied growth | Normalized growth | WACC | Implied exit |
| --- | --- | --- | --- | --- | --- | --- |
| LVMH | 481.45 EUR | 313.51 EUR | 7.08% | -1.71% | 8.55% | 10.8x |
| Hermès | 1626.00 EUR | 1063.80 EUR | 24.85% | 12.98% | 9.13% | 9.4x |
| Kering | 289.75 EUR | 36.54 EUR | 7.98% | -13.03% | 7.31% | 14.5x |
| Richemont | 196.15 CHF | 105.17 CHF | 19.97% | 3.80% | 9.42% | 10.8x |

Full report with charts and sensitivity grids: [`reports/valuation.html`](reports/valuation.html).

These figures come from a specific frozen data pull captured 2026-08-06
(`tests/fixtures/frozen.py`, `CAPTURED`), not a live fetch made while you are reading this. The
regression suite replays the whole pipeline against that frozen pull and checks the numbers
above reproduce exactly. A live `--refresh` does not: it moves Richemont by a few cents from
provider-side rounding noise in the price feed, so "reproducible" describes the frozen replay,
not a fresh run.

## The point

A forward DCF produces a target price, and the argument about it always lands in the same
place: the terminal growth rate. Inverting the model moves the conversation. Fix the observed
price, solve for the growth that reproduces it, and the output stops being a claim about what
a company is worth and becomes a statement about what the market already believes.

Both directions run through one function, `dcf.value`. A round-trip test values the business
at a known growth rate, feeds the resulting price back to the reverse model, and requires it
to return that same rate — so the two cannot drift apart without a test failing.

## Method

- **Free cash flow to the firm**, so four companies with different leverage stay comparable.
- **Normalized drivers**: every ratio is a median across the reported years rather than the
  latest value. Kering's most recent year is a trough, and extrapolating a trough produces an
  absurd valuation.
- **WACC computed, not assumed**: CAPM cost of equity on a recomputed beta, after-tax cost of
  debt from reported interest expense, weights at market equity and book debt.
- **Terminal value restated as an exit multiple**, because "3% forever" and "an exit at 40x
  EBIT" are the same assumption and only one of them is easy to judge.
- **Currencies kept apart**: Richemont publishes in euros and trades in Swiss francs. The
  model converts before comparing, and refuses to run if the rate is missing.

## What this does not say

A reverse DCF does not say a share is expensive. It says what the market assumes. Judging
whether the implied growth is plausible for a given house is an analyst's work, not a model's.

## Limitations

Stated because they matter more than the headline figures.

- **IFRS 16 lease liabilities are not adjusted.** Debt is taken as reported on the balance
  sheet, with lease obligations included exactly as the company classifies them there — no
  restatement to a pre-IFRS-16 basis and no separate capitalization of off-balance-sheet
  leases. Luxury retail runs on flagship stores in city centres, and lease treatment moves net
  debt non-trivially. The approximation is acceptable here because the same convention is
  applied to all four houses, so a comparison between them is not distorted even though any
  single WACC or net-debt figure is not lease-adjusted in isolation.
- **The equity risk premium is an assumption**, fixed at 5.0%, alongside a 3.0% risk-free
  rate. Neither is measured; the sensitivity grid shows what they are worth.
- **Terminal growth is fixed at 2%** over five explicit forecast years, not fitted or varied
  by company.
- **Five years of statements is a short history** for a normalized margin. It is what the data
  source provides, and it is why the normalization is a median rather than a mean.
- **No segment build, no sum-of-the-parts.** These are conglomerate-ish businesses valued as
  single entities.
- **The published figures are a frozen pull, not a live guarantee.** See the note under
  Results: a live `--refresh` reproduces the method, not the exact cents.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m vlab --output reports/valuation.html
```

Statements and prices are cached under `cache/` for a week; pass `--refresh` to force a fetch.

## Tests

```bash
.venv/bin/python -m pytest --cov=src/vlab
```

The suite runs offline against injected fetchers: 94 tests, 97% coverage overall, with
`dcf.py`, `reverse.py`, `sensitivity.py`, `pipeline.py`, `report/build.py` and
`report/charts.py` at 100%. Nothing in the default run touches the network — the regression
suite replays the frozen fixture above instead of calling the data provider.

## License

MIT.
