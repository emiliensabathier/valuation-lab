# valuation-lab

Discounted cash flow valuation of four European luxury houses, then inverted: what growth
does each share price already imply?

![ci](https://github.com/emiliensabathier/valuation-lab/actions/workflows/ci.yml/badge.svg)

## Results

Unlevered free cash flow, five explicit years with growth fading linearly to the terminal
rate, Gordon terminal value. Betas recomputed from five years of weekly returns against the
Euro Stoxx 50.

| Company | Price | Modelled value | Implied growth, yr 1 | Implied growth, 5y avg | Normalized growth | WACC | Implied exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LVMH | 481.45 EUR | 342.03 EUR | 11.75% | 6.87% | -1.71% | 8.56% | 10.8x |
| Hermes | 1626.00 EUR | 877.95 EUR | 47.58% | 24.79% | 12.98% | 9.13% | 9.4x |
| Kering | 289.75 EUR | 98.36 EUR | 13.59% | 7.79% | -13.03% | 7.31% | 14.5x |
| Richemont | 196.15 CHF | 105.29 CHF | 35.31% | 18.65% | 3.80% | 9.15% | 11.2x |

Read the two implied-growth columns together. The first is the front of a fading path, so it
is not a rate anyone expects to be sustained; the second is what that path averages, and it
is the number worth arguing with. Hermes at 24.79% average against its own 12.98% normalized
history is the sharpest reading here: the price assumes the last four years repeat and then
some, for five more.

![Implied revenue growth against normalized historical growth, for each of the four houses](docs/implied-growth.png)

Every blue bar sits above its orange one, which is the finding: at these prices the market
is paying for more growth than any of the four has delivered. Kering is the extreme — the
price assumes +7.8% a year from a business whose reported revenue has been shrinking at 13%.

Full report, with per-company drivers, charts and sensitivity grids:
[`reports/valuation.html`](reports/valuation.html). Kering's value sitting roughly 66% below
its market price is the most striking number on that page; it is explained there, in the
report itself, and again below under Known limitations — not softened, because the explanation
is what makes the rest of the analysis worth trusting.

These figures were generated on 2026-08-07 from a cached data pull, not fetched live while you
are reading this. A committed fixture (`tests/fixtures/frozen.py`, `CAPTURED = "2026-08-07"`)
freezes that same pull, and the regression suite replays the whole pipeline against it offline,
checking every figure — including both sensitivity grids, roughly 200 cells across the four
companies (two 5x5 grids each) — to a tight relative tolerance (1e-9 for arithmetic, looser
for the root-found implied growth). The committed `reports/valuation.html` is rendered from
this same frozen fixture
(`scripts/build_frozen_report.py`), and a test checks the two stay byte-identical, so the page
above is the artefact the test suite verifies, not a separate live pull that happens to agree
with it. Replaying these exact frozen inputs is exact, to the last digit shown, for all four
companies — including Richemont, whose beta and modelled value depend on the EURCHF history
(see Currencies kept apart, below); nothing about that conversion introduces approximation on
its own. Re-running `python -m vlab --refresh`, by contrast, reproduces the method, not the
exact cents: it pulls today's prices and today's exchange rate, not 2026-08-07's, so Richemont's
modelled value and implied growth — both of which move with a fresh EURCHF quote — will differ
by a few cents to a few tenths of a percent from the figures above. The other three companies
have no currency conversion in their pipeline and reproduce exactly across both pulls.

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
  model converts before comparing — including the beta regression, which first converts
  Richemont's CHF price history into euros so it is regressed against the euro-denominated
  Euro Stoxx 50 in one currency, not two — and refuses to run if the rate is missing.

## What this does not say

A reverse DCF does not say a share is expensive. It says what the market assumes. Judging
whether the implied growth is plausible for a given house is an analyst's work, not a model's.

## Known limitations

Stated because they matter more than the headline figures, and because an interviewer who
checks the data will find every one of them.

- **Four usable years of revenue, three growth observations, and a median of three is a
  single observation wearing a statistic's name.** The data source returns five fiscal-year
  columns per statement, but the oldest is empty for all four companies, leaving four usable
  revenue figures and three year-on-year growth rates. The median of three numbers is the
  middle one when sorted by value — not a blend, not an average. Concretely: LVMH's published
  "normalized growth" of -1.71% is not a smoothed trend across several years, it is literally
  its FY2023-to-FY2024 revenue change, selected only because it happens to sit between the
  other two. EBIT margin, tax rate and the capex/D&A/NWC ratios are medians of four values
  each (a genuine, if small, central tendency); revenue growth alone is a median of three, and
  is the fragile one.
- **Kering's valuation sits about 66% below its market price because the normalization window
  is a company mid-collapse, not because of a modelling error.** Over FY2022-FY2025 its EBIT
  margin fell from 26.1% to 7.3% and revenue fell from EUR 20.35bn to EUR 14.68bn. The model's
  medians over that window — an 18.22% EBIT margin, a -13.03% revenue growth — are an honest
  reading of a business still in its trough, projected forward from there rather than from the
  scale it held three years ago. It used to be 87%: the growth fade below stops that -13.03%
  compounding for five straight years, which was the single largest contributor to the old
  figure. See `reports/valuation.html` for the same explanation next to the number it explains,
  and the Drivers table for the inputs behind every company, not only Kering's.
- **The growth fade is linear, and linear is a choice.** The explicit period used to hold
  each company's normalized growth flat for five years and then jump to the 2% terminal rate
  overnight — Kering compounding its own -13.03% five times, Hermes its +12.98%. No business
  reverses a five-year trend in a single year, so growth now steps linearly from the
  normalized rate in year one to the terminal rate in year five and the switch into Gordon is
  continuous. What replaced a cliff is still an assumption: nothing here argues that the path
  is straight rather than convex, and a company defending a premium would argue for convex.
  One reassuring sign, and it is only that: the fade barely moves the *average* growth the
  market price implies (Hermes 24.85% flat against 24.79% averaged over the fading path), so
  it redistributes the implied growth rather than inventing or destroying it. What it does
  move is the forward value, because that runs on the company's own normalized rate.
- **Working capital is still scaled to the revenue level, and two attempts to fix it failed
  on this data.** Scaling the investment to the *change* in revenue is the textbook treatment,
  and it is not estimable here: LVMH and Kering both had revenue fall inside the four-year
  window, so the denominator changes sign and the median of three ratios comes out positive
  for both — working capital releasing cash as a business grows, which is not a thing. Taking
  the stock ratio off the balance sheet instead fails differently: the reported Working
  Capital line is current assets minus current liabilities, so it carries the cash pile, and
  Hermes and Richemont price at 0.79 and 0.89 of revenue on it. Building operating working
  capital from inventory, receivables and payables separately would be the real fix and is not
  attempted here. The quantified effect of the current treatment is in the bullet below; it
  stays disclosed rather than half-fixed.
- **The exit-multiple cross-check inverts the ranking an analyst would expect.** It reduces to
  `(FCFF / EBIT in the final year) × 1.02 / (WACC − 2%)` — a formula that rewards a low WACC
  and a high FCFF/EBIT conversion, neither of which tracks the underlying quality of the
  business. Kering combines the lowest WACC of the four (7.31%) with a high FCFF/EBIT
  conversion (0.75) and gets the highest exit multiple (~14.5x); Hermes combines the
  second-highest WACC (9.13%) with the lowest FCFF/EBIT conversion of the four (0.66) and gets
  the lowest (~9.4x) — despite being the strongest of the four on margin, growth and net-debt
  position. The multiple is doing arithmetic, not judgment.
- **Kering carries the lowest WACC of the four (7.31%) because its equity collapsed alongside
  its stock price, not because it is safer.** A lower market capitalization shifts the
  capital-structure weights toward book debt — 33.8% debt weight for Kering, against 13.3%
  (LVMH), 9.9% (Richemont) and 1.4% (Hermes) — priced at Kering's 3.43% pre-tax cost of debt.
  A stressed credit ends up looking like cheaper capital because the stock fell, which is the
  opposite of what a rising cost of distress should do to a discount rate.
- **Capex/revenue stays below D&A in perpetuity for three of the four companies, inflating
  their terminal values.** LVMH (-6.49% vs. +8.77%), Kering (-9.50% vs. +10.92%) and Richemont
  (-4.94% vs. +7.23%) all reinvest, on the model's own normalized ratios, less than they
  depreciate while still growing at 2% forever — a terminal state a company cannot actually
  sustain indefinitely. Hermes is the exception (-6.72% vs. +5.77%): its normalized capex ratio
  exceeds D&A, so this particular inflation does not apply to it.
- **Working capital is scaled to each year's revenue level, not to its growth, so it never
  fades even in the terminal year.** `dcf.free_cash_flows` multiplies the normalized
  `nwc_ratio` (a median of `Change In Working Capital / Total Revenue` across the reported
  years) by that year's whole projected revenue -- including the terminal year, where growth
  has already slowed to 2%. A company compounding at only the terminal rate still consumes
  working capital in proportion to its entire revenue base forever, rather than in proportion
  to the small incremental revenue that 2% growth is actually adding. Recomputing each
  valuation with this term removed shows how much of it is riding on that assumption: value
  per share rises 20.7% for LVMH, 16.1% for Richemont, 12.5% for Kering and 4.8% for Hermes.
  This is not a modelling error: the treatment is internally consistent with how `nwc_ratio`
  itself is normalized. Scaling the investment to the *change* in revenue instead is the
  textbook fix and it is not estimable on this data — see the growth-fade bullet above for
  what was tried and why both alternatives failed.
- **IFRS 16 lease liabilities are not adjusted.** Debt is taken as reported on the balance
  sheet, with lease obligations included exactly as the company classifies them there — no
  restatement to a pre-IFRS-16 basis and no separate capitalization of off-balance-sheet
  leases. Luxury retail runs on flagship stores in city centres, and lease treatment moves net
  debt non-trivially. The approximation is acceptable here because the same convention is
  applied to all four houses, so a comparison between them is not distorted even though any
  single WACC or net-debt figure is not lease-adjusted in isolation.
- **Hermes' first-year implied growth (47.58%) sits close to the reverse DCF's 50% ceiling**
  (`GROWTH_BRACKET = (-0.20, 0.50)` in `reverse.py`). A modest further rise in its share price
  would push the root-finder past that bracket, and the model would refuse to publish a growth
  figure rather than extrapolate past a limit chosen for plausibility, not derived from
  anything structural. That refusal is the intended behaviour, not a bug: see `pipeline.py`'s
  per-company failure isolation, which is exactly what a bracket miss triggers. The bracket
  was (-0.05, 0.25) while growth was held flat and had to be widened for the fade, because the
  solver now moves the *front* of a decaying path rather than a rate sustained for five years;
  47.58% at the front averages 24.79%. Widening it to fit the arithmetic is exactly the kind of
  move that quietly turns a plausibility limit into a formality, which is why the numbers on
  both sides of the change are written down here rather than only the new ones.
- **The equity risk premium is an assumption**, fixed at 5.0%, alongside a 3.0% risk-free
  rate. Neither is measured; the sensitivity grid shows what they are worth.
- **Terminal growth is fixed at 2%** over five explicit forecast years, not fitted or varied
  by company.
- **No segment build, no sum-of-the-parts.** These are conglomerate-ish businesses valued as
  single entities.
- **The published figures are a frozen pull, not a live guarantee.** See the note under
  Results: a live `--refresh` reproduces the method exactly for three of the four companies,
  and Richemont's figures to within a few cents to a few tenths of a percent.

## Running it

```bash
python -m venv .venv
# Linux / macOS
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m vlab
# Windows
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m vlab
```

This always performs a live fetch (subject to the on-disk cache below), so it writes to
`reports/valuation.local.html` by default rather than the committed `reports/valuation.html` —
the committed page is what the regression suite verifies against the frozen fixture
(`tests/fixtures/`), and a live run overwriting it would silently break that guarantee for
anyone who ran this command. Pass `--output reports/valuation.html` only if you deliberately
want to replace the committed page with fresh, unfrozen numbers (this will also make
`tests/test_report_matches_fixture.py` fail against the pre-refresh fixture until you re-freeze
it — see Tests, below). To reproduce the committed page itself, byte for byte, from the frozen
fixture instead of a live pull, run:

```bash
.venv/bin/python scripts/build_frozen_report.py   # Linux / macOS
.venv\Scripts\python scripts/build_frozen_report.py   # Windows
```

Statements and prices are cached under `cache/` for a week; pass `--refresh` to force a fetch.

## Tests

```bash
.venv/bin/python -m pytest --cov=src/vlab   # Linux / macOS
.venv\Scripts\python -m pytest --cov=src/vlab   # Windows
```

The suite runs offline against injected fetchers, with 98% coverage overall and every module
at 100% except `data/loader.py` (89%, the live-`yfinance`-only branches) and `wacc.py` (98%,
the zero-market-variance guard in `levered_beta`). Nothing in the default run touches the
network — the regression suite replays the frozen fixture above instead of calling the data
provider, for both the scalar figures and both sensitivity grids.

## Related

Four companion studies, same method: a frozen capture, a rendered report, and a
limitations section longer than the results.

- [rates-lab](https://github.com/emiliensabathier/rates-lab) — what the yield curve prices: policy path, inflation, term premium
- [credit-lab](https://github.com/emiliensabathier/credit-lab) — which default score flags first, against real credit events
- [portfolio-lab](https://github.com/emiliensabathier/portfolio-lab) — whether any allocation rule beats a static 60/40
- [options-lab](https://github.com/emiliensabathier/options-lab) — what S&P 500 implied volatility prices: an arbitrage-free surface and the variance premium

## License

MIT.
