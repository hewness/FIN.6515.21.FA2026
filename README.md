# NVIDIA DCF Valuation

An interactive discounted cash flow model for NVIDIA (NVDA), built with
[Gradio](https://gradio.app). Move a slider and the valuation recomputes — no submit
button, no spreadsheet.

## Setup

Requires Python 3.10+ (developed on 3.14).

```
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:7860**.

The server runs in the foreground; stop it with Ctrl+C.

## Tests

```
.venv\Scripts\python.exe -m pytest
```

126 tests. `test_dcf.py` covers the valuation math — including a case simple enough to
verify by hand, the cash/debt bridge, both growth/margin schedules, the free cash flow
drivers, the terminal-value guardrail, and the full discounting chain: that terminal
value really is Gordon Growth, that each year's present value is its cash flow times its
discount factor, and that the parts sum to the reported totals. It also pins the
scenario weighting and the two tiers of input validation.

`test_app_wiring.py` covers the UI. Two failure modes get specific guards, because both
would leave an app that still runs and still prints a plausible number:

- **Positional binding.** `gr.on` binds sliders to the handler by position, so the test
  asserts the component list and the handler signature stay in lockstep by label.
- **A table that disagrees with the engine.** The projection table's rendered cells are
  parsed back out of the HTML and compared, exactly, against a direct `run_dcf()` call.
- **Layout that quietly regresses.** The app opens on a visible tab, the mode toggle hides
  a whole column rather than its contents, and no tab relies on individual visibility —
  each of those was a real bug found only by opening the app, so each now has a guard.

`test_viz.py` does the same for the two charts, which are harder to check than a table because
it renders and looks plausible whatever it draws. The tests invert the plotted SVG
coordinates back into dollars and reconcile them against the model, pin the series colors
to their documented palette slots, and sweep 500 slider combinations asserting the
endpoint labels never collide — a bug that sweep actually caught, and the closest
substitute available for looking at the thing.

## Layout

| File | Contains |
|---|---|
| `dcf.py` | The valuation math. Pure functions, no UI imports, independently testable. |
| `viz.py` | Color scales (computed in OKLab), the heatmap, the projection chart and the waterfall. |
| `app.py` | Gradio UI — the assumption panels, the result panels, and the tabs. |
| `test_dcf.py` | Valuation math tests. |
| `test_app_wiring.py` | Guards on the UI-to-model binding. |
| `test_viz.py` | Guards on chart geometry, palettes, labels and the waterfall's arithmetic. |

## Controls

| Section | Controls |
|---|---|
| **Forecast detail** | Taper Y1→Y5, or set each year |
| **Revenue growth** | *Taper:* Year 1 and Year 5 growth · *Per-year:* Years 1–5 individually |
| **Operating margin** | *Taper:* Year 1 and Year 5 margin · *Per-year:* Years 1–5 individually |
| **Cash flow** | Net capex (% of revenue), Working capital (% of revenue growth), Tax rate |
| **Discount rate** | WACC, Terminal growth, Forecast years |

One toggle governs both growth and margin, so the two stay at matching levels of detail.
The per-year sliders open on the taper's own schedule, so switching modes at the default
settings does not move the valuation — the two modes are the same forecast expressed two
ways, which the test suite asserts.

## Scenario analysis

Ticking **Scenario analysis** splits the app into three complete, independent cases. Each
of Base, Bear and Bull gets its own tab holding a full assumption panel and the full set of
views, so a bear case can differ on horizon, tax rate or capex — not just on the headline
drivers. The probability split sits in the mode's own box: two cut points on a 0–100 axis,
so the three probabilities sum to 100 by construction rather than by validation.

The **Scenarios** tab then reports:

- a **buy/hold/sell recommendation** with an explicit conviction level;
- the three case values and the probability-weighted average;
- **what the market price requires** — each driver reverse-solved to the value that would
  justify today's price, with a verdict on whether that is defensible.

Two things about how that is calculated are worth knowing, because both are easy to get
wrong and neither is visible in the output:

**The weighting applies to the values, not the assumptions.** The model is non-linear —
`1/(WACC − g)` is convex — so `Σ pᵢ·V(caseᵢ)` and `V(Σ pᵢ·caseᵢ)` are different numbers. At
a plausible spread they differ by about 47% and disagree about whether the stock is cheap.

**The recommendation reports two readings rather than blending them.** The weighted mean
and the probability mass can disagree — a mean sitting near the price because one fat tail
drags it there is not the same as a balanced view. When they conflict the panel takes the
more cautious verdict, drops to low conviction, and names the case responsible.

## Validation

Inputs are checked in two tiers, because not everything questionable is wrong.

**Refused outright**, with a red card on every panel:

- WACC at or below terminal growth — the perpetuity is infinite or negative;
- a terminal multiple above **100×** — `(1+g)/(WACC−g)` past that point is arithmetic
  rather than valuation. The guard is on the multiple, not the raw spread, because a 1pp
  spread is harmless at a 20% WACC and ruinous at 4%.

**Valued, with an amber notice** naming the issue: a terminal multiple above 40×, a negative
final-year cash flow (so the terminal value is a negative perpetuity), terminal growth above
long-run GDP, an operating margin above the gross margin, or a WACC below a credible floor.
The last three reuse the same constants that drive the break-even verdicts, so there is one
definition of implausible rather than two that can drift.

The opening settings trip none of this, deliberately — a validation layer that fires on the
first screen only teaches people to ignore it.

## What the model does

1. **Projects revenue.** Years 1–5 either glide from a Year-1 rate to a Year-5 rate or
   are set individually. Beyond Year 5 growth tapers toward the long-run terminal rate,
   so hypergrowth fades rather than stopping abruptly.
2. **Applies an operating margin** per year — tapering or per-year to match growth. Past
   Year 5 the margin holds flat at its Year-5 level; unlike growth, a margin has no
   natural long-run anchor to converge on.
3. **Builds free cash flow** from its drivers:

   ```
   FCF = NOPAT − net capex − ΔWorking capital
   ```

   Working capital is charged against **revenue growth**, not the revenue level. This is
   the only treatment that behaves in perpetuity: tied to the level, working capital
   would consume a fixed share of revenue forever and corrupt the terminal value; tied to
   the delta, it fades as growth approaches the terminal rate, which is what the Gordon
   Growth formula assumes. Flat revenue correctly consumes none.

   Net capex is capex *net of depreciation*, so one slider covers both.
4. **Discounts** each year at the WACC.
5. **Adds a terminal value** via Gordon Growth. The model refuses to value a scenario
   where WACC does not exceed terminal growth, rather than returning a confident wrong
   number.
6. **Bridges to per-share value**: enterprise value less net debt (cash minus debt),
   divided by shares outstanding.

With scenario analysis off, the app shows one model through five tabs. With it on, those
are replaced by Scenarios plus one tab per case, each carrying the same five views of its
own forecast.

The **Valuation** tab shows KPI cards, then a year-by-year forecast table — revenue,
operating margin, EBIT, NOPAT, free cash flow, discount factor and present value for
every projected year — and then the equity bridge from enterprise value down to intrinsic
value per share. Beneath the table the Gordon Growth arithmetic is printed with the
current scenario's own numbers, so the terminal value can be checked rather than taken on
trust.

The **Projection** tab plots revenue, free cash flow and the present value of free cash
flow against the forecast years — three lines on one shared axis, since all three are in
$B. Hovering any year gives a crosshair and a read-out of all three series. The third
line is the one worth watching: free cash flow climbs every year, but its present value
**peaks mid-forecast and then falls**, because past that point discounting outruns
growth. That is the mechanism behind terminal value dominating the valuation, and it is
invisible in the table.

The **Valuation Waterfall** tab shows the same bridge as a chart: five columns carrying
the running total from discounted forecast cash flows, through the terminal value, to
enterprise value, then net debt, then equity value. Where the table lists the figures, the
waterfall makes their relative size structural — the terminal value bar reaches further
than every projected year combined.

Two details worth knowing. The net-debt bar's **label follows its sign**: NVIDIA holds
more cash than debt, so it reads "Net cash" and adds value; a bar labelled "Net debt" that
pushed the total up would be a lie. And that bar is only ~1% of equity value, so it is a
sliver — deliberately, because that thinness is true information. No broken axis, no
second scale; the value label carries it.

The **Sensitivity - WACC vs. Terminal Growth** tab revalues the company across a grid of
WACC (8–14%) and terminal
growth (1–5%) rates, holding your other slider settings fixed. Blue cells are worth more
than the market price, red less, with a neutral midpoint at fair value.

The **Sensitivity - Operating Margin vs. Terminal Growth** tab is the same grid against
margin instead of discount rate. Its column axis is the **Year-5 operating margin** —
the level that holds flat from Year 5 into perpetuity — so both of its axes govern the
terminal economics. Year-1 margin stays wherever you set it, and the rows match the
other sensitivity tab so the two grids can be read against each other.

Note that the sensitivity grids **do not** blank out when the current scenario is
unvaluable. Each cell is its own scenario, so the grid stays useful and simply dashes
out the combinations where WACC fails to exceed terminal growth.

The waterfall and both heatmaps use the **same diverging pair to mean the same thing**:
blue is worth more, red is worth less.

## On the assumptions — read this before quoting a number

The starting figures are NVIDIA's FY2025 actuals: revenue $130.5B, cash $43.2B, debt
$8.5B, 24.5B shares, reference price $180.

Slider defaults, and what each is grounded in:

| Input | Default | Basis |
|---|---|---|
| Year 1 operating margin | 62.4% | FY2025 actual |
| Year 5 operating margin | 55% | **Judgment** — assumes margin compression as competition arrives |
| Net capex | 1.5% of revenue | FY2025 actual was 1.2% (capex $3.4B less D&A $1.86B on $130.5B revenue); nudged up because NVIDIA guided FY2026 capex higher. Low because NVIDIA is fabless — TSMC carries the fab spend. |
| Working capital | 10% of revenue growth | ⚠️ **Unverified placeholder** — the one default not tied to a filing |
| Year 1 / Year 5 revenue growth | 50% / 15% | **Judgment** |
| Tax rate | 15% | Close to NVIDIA's ~13% effective rate |
| WACC / terminal growth | 10% / 3% | **Judgment** — generic large-cap assumptions |

At these defaults the app opens near **$133.70/share, −25.7%, SELL**.

Three things worth knowing before you read anything into that:

- **Terminal value is ~60% of enterprise value.** Most of the answer comes from one
  formula about a year you cannot see.
- **WACC and terminal growth dominate.** One percentage point on either moves value
  ~13%; one point on Year-1 revenue growth moves it ~1.7%. The inputs that matter most
  are the two nobody can observe.
- **Margin compression does most of the rest.** Tapering the margin from 62.4% to 55% is
  worth about $17/share on its own — far more than net capex and working capital
  combined, which together cost about $6.

Treat the output as a tool for testing which assumptions a price implies, not as a price
target.

## Coursework

FIN 6515.21 — Fall 2026.
