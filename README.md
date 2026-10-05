# valuation-lab

Discounted cash flow valuation of four European luxury houses, then inverted: what growth
does each share price already imply?

![ci](https://github.com/emiliensabathier/valuation-lab/actions/workflows/ci.yml/badge.svg)

## Results

Frozen data pull of 2026-08-07. Full report, with drivers, WACC bridge and sensitivity grids:
[`reports/valuation.html`](reports/valuation.html).

| Company | Price | Modelled value | Implied growth, yr 1 | Implied growth, 5y avg | Normalized growth | WACC | Implied exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LVMH | 481.45 EUR | 275.58 EUR | 22.76% | 12.38% | -1.71% | 8.95% | 7.6x |
| Hermes | 1626.00 EUR | 863.93 EUR | 49.46% | 25.73% | 12.98% | 9.23% | 8.5x |
| Kering | 289.75 EUR | 45.39 EUR | 39.55% | 20.78% | -13.03% | 7.95% | 7.2x |
| Richemont | 196.15 CHF | 92.31 CHF | 45.85% | 23.93% | 3.80% | 9.42% | 8.6x |

The first implied-growth column is the front of a path that fades linearly to 2%; the second
is that path's average, and it is the number to compare with the company's own history.

![Implied five-year average revenue growth against normalized historical growth, for each of the four houses](docs/implied-growth.png)

**How to read it.** Every implied average sits above the normalized history, but the gap
measures the market against *this model*, and the model leans low (see Limitations): working
capital drains cash even at zero growth, cash flows are discounted at year-end, betas are raw
and priced at a 5% equity risk premium, median capex includes property purchases, and
four-year medians catch some houses in a downturn. Re-solved at a WACC two points lower, the
implied average drops to 4.58% (LVMH), 16.89% (Hermes), 10.45% (Kering) and 15.39%
(Richemont). The defensible reading: the market prices more growth than these normalized
inputs credit, most clearly for Hermes and Richemont. It is not a claim that any share is
mispriced.

## Method

- **Free cash flow to the firm**: `EBIT x (1 - tax) + D&A + capex + lease payments + change in
  working capital`, five explicit years, Gordon terminal value at 2%.
- **Normalized drivers**: every ratio is a median across the reported years, not the latest
  value.
- **Leases, pre-IFRS 16, consistently**: the lease payment (last year's current lease
  liability plus after-tax lease interest) is charged in free cash flow; lease liabilities are
  excluded from net debt and from the WACC debt weight. Counting leases as debt *and* as a
  cash cost would count them twice; the companies' own net-debt definitions exclude them too.
- **WACC computed, not assumed**: CAPM on a beta recomputed from five years of weekly returns
  against the Euro Stoxx 50, cost of debt from reported interest, market-equity and book-debt
  weights.
- **Roll-forward to the price date**: cash flows are dated from the last fiscal year-end and
  discounted from the price date (0.59 years for the December filers, 0.34 for Richemont).
- **Reverse DCF**: Brent root-find on first-year growth over `dcf.value` itself; a round-trip
  test values at a known growth and requires the solver to recover it.
- **Terminal value restated as an exit multiple**, so "2% forever" can be judged as an EV/EBIT.
- **Currencies kept apart**: Richemont reports in EUR and trades in CHF; prices and the beta
  regression are converted, and the run refuses a missing rate.

## Limitations

- **Revenue growth is a median of three.** Four usable fiscal years give three growth rates;
  LVMH's -1.71% is literally its FY2023-to-FY2024 change.
- **Working capital scales with the revenue level**, not its change, so it consumes cash even
  in the terminal year. Removing the term lifts value per share by 25.4% (LVMH), 25.3% (Kering),
  18.3% (Richemont) and 5.1% (Hermes). Scaling to the change in revenue is not estimable here
  (revenue fell inside the window for LVMH and Kering), and the reported Working Capital line
  carries the cash pile; an operating build from inventory, receivables and payables is not
  attempted.
- **Capex includes property.** Kering's capex ran 5.26%, 13.34%, 19.61% and 5.66% of revenue
  over FY2022-FY2025; the middle years carry flagship real-estate purchases (land and buildings
  rose by about EUR 2.8bn, partly sold in FY2025). The 9.50% median is kept as reported, not
  adjusted: at its FY2025 ratio of 5.66% Kering's value would be about 102 EUR, not 45.39.
  LVMH's FY2023 capex has the same shape.
- **Kering's 84% gap** is a normalization over a downturn: EBIT margin ran 26.12%, 23.48%,
  12.96%, 7.33%, so the 18.22% median sits above the latest year, while the -13.03% growth
  median is close to the latest rate. The report's Kering note is generated from these figures.
- **Lease payments are estimated.** The data has no lease-payment line; principal is the prior
  year's current lease liability (scheduled, not necessarily paid), and lease interest is
  reported interest split pro rata between leases and borrowings.
- **Discount-rate inputs are assumptions.** Risk-free 3%, ERP 5%, raw betas of 1.25-1.39 with
  no shrinkage toward one, year-end discounting. Kering's WACC is the lowest (7.95%) because its
  fallen market cap raises the book-debt weight to 25.15%, not because it is safer.
- **Hermes sits at the edge of the solver.** Its first-year implied growth (49.46%) is just
  under the 50% ceiling of `GROWTH_BRACKET`; a slightly higher price would make the model
  refuse to publish rather than extrapolate. The ceiling is a plausibility limit, not derived.
- **The growth fade is linear**, a choice; a company defending a premium would argue convex.
- **No segment build, no sum-of-the-parts**, and terminal growth is not varied by company.
- **Frozen, not live.** A `--refresh` run reproduces the method, not these cents.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/python -m vlab               # live fetch, writes reports/valuation.local.html
.venv/bin/python scripts/build_frozen_report.py   # committed page, from the frozen fixture
```

Statements and prices are cached under `cache/` for a week; `--refresh` forces a fetch.
After a methodology change, regenerate in order: `scripts/build_fixture.py
--expectations-only`, `scripts/build_frozen_report.py`, `scripts/build_readme_chart.py`.

## Tests

```bash
.venv/bin/python -m pytest --cov=src/vlab
```

141 tests, offline against injected fetchers, 98% coverage (`data/loader.py` at 89%: the
live-`yfinance` branches). The regression suite replays the frozen fixture and checks every
published figure, both sensitivity grids and the lower-WACC re-solve; a further test requires
the committed report to match a fresh render byte for byte. The full suite runs in under a
minute.

## Related

Companion studies, same approach: a frozen capture, a rendered report, stated limitations.

- [rates-lab](https://github.com/emiliensabathier/rates-lab) — what the yield curve prices: policy path, inflation, term premium
- [credit-lab](https://github.com/emiliensabathier/credit-lab) — which default score flags first, against real credit events
- [portfolio-lab](https://github.com/emiliensabathier/portfolio-lab) — whether any allocation rule beats a static 60/40
- [options-lab](https://github.com/emiliensabathier/options-lab) — what S&P 500 implied volatility prices: an arbitrage-free surface and the variance premium

## License

MIT.
