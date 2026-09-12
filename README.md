# NVIDIA DCF Valuation

An interactive discounted cash flow model for NVIDIA (NVDA), built with
[Gradio](https://gradio.app). Move a slider and the valuation recomputes — no submit
button, no spreadsheet.

Every opening assumption is sourced from `NVIDIA_Exhibits.xlsx` (compiled 30 July 2026),
valued at the **29 July 2026 close of $190.01**. That workbook is third-party coursework
material and is **not redistributed in this repository** — place your own copy alongside
`app.py` if you want to check a figure against it. Nothing at runtime reads it: the
defaults it justifies are baked into `dcf.py` and `app.py`, each annotated with the
exhibit it came from.

## Setup

Requires Python 3.10+ (developed on 3.14).

```
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:7860**.

The server runs in the foreground; stop it with Ctrl+C.

## Hosted demo

The app runs as a Gradio Space at
**https://huggingface.co/spaces/hewness/nvidia-dcf-valuation** (currently private).

Deploy or redeploy with:

```
.venv\Scripts\python.exe deploy_space.py hewness/nvidia-dcf-valuation
```

`deploy_space.py` stages `app.py`, `dcf.py` and `viz.py` together with `space/README.md`
(which carries the Space's required YAML frontmatter) and `space/requirements.txt` into a
temporary directory, then uploads that. Nothing is copied into the working tree, so the
Space cannot drift from the modules it was built out of, and the Space card cannot collide
with this README.

`space/requirements.txt` is deliberately empty of runtime dependencies: the app imports
only `gradio`, which Spaces preinstalls and manages, plus the standard library. The DCF
math and every chart are hand-rolled, so there is no numpy, pandas or plotly to install.

## Tests

```
.venv\Scripts\python.exe -m pytest
```

135 tests. `test_dcf.py` covers the valuation math — including a case simple enough to
verify by hand, the cash/debt bridge, both growth/margin schedules, the free cash flow
drivers, the terminal-value guardrail, and the full discounting chain: that terminal
value really is Gordon Growth, that each year's present value is its cash flow times its
discount factor, and that the parts sum to the reported totals. It also pins the
scenario weighting, the two tiers of input validation, and that every default still
traces to the exhibit it came from.

`test_app_wiring.py` covers the UI. Two failure modes get specific guards, because both
would leave an app that still runs and still prints a plausible number:

- **Positional binding.** `gr.on` binds sliders to the handler by position, so the test
  asserts the component list and the handler signature stay in lockstep by label.
- **A table that disagrees with the engine.** The projection table's rendered cells are
  parsed back out of the HTML and compared, exactly, against a direct `run_dcf()` call.
- **Text the theme repaints.** Gradio sets `color` on every descendant of a `gr.HTML`
  via `.prose *`, which outranks a single-class rule. Anything of ours that picks ink to
  suit its own background is checked for enough specificity to survive that, in every
  light/dark variant — the neutral heatmap cell is near-white, so losing its ink meant
  white text on a white cell.
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
pushed the total up would be a lie. And that bar is only ~2% of equity value, so it is a
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

Every opening figure traces to **`NVIDIA_Exhibits.xlsx`**, compiled 30 July 2026.
The valuation date is the **29 July 2026 close of $190.01**.

Company figures: revenue **$215.9B** (FY2026), cash and other non-operating assets
**$115.5B**, debt **$8.47B**, **24.22B** shares.

On that cash figure: Exhibit 6 derives enterprise value as market cap *less non-operating
assets of $115.5B*, which bundles cash, marketable debt and equity securities, and
non-marketable stakes at book. This model uses the same $115.5B rather than the narrower
$50.3B of cash and marketable debt, so that **the model's enterprise value and the
market-implied enterprise value are the same construction** and can be compared directly.
The cost is that illiquid stakes sit at book value.

| Input | Default | Basis |
|---|---|---|
| Year 1 operating margin | 65.6% | Ex 2 — Q1 FY2027 **actual**, and Q2 guidance (GM 74.9% ±50bp, opex ~$8.5B on $91.0B) implies 65.6% again. **Not** FY2026's 60.4%, which is depressed by a one-off gross-margin dip to 71.1%; using it would carry that through all ten forecast years. |
| Year 5 operating margin | 55% | **Judgment** — compression as custom silicon and AMD take share |
| Year 1 revenue growth | 82.25% | Ex 6 — consensus FY2027 revenue $393.6B against FY2026's $215.9B |
| Year 5 revenue growth | 0.25% | Lands FY2031 revenue at $1,088B — **78% of Ex 8's $1.4T 2030 accelerator market**, inside the 75–85% share band the exhibit reports |
| Net capex | 1.5% of revenue | Ex 5 — (capex $6,042M less D&A $2,843M) / revenue $215,938M = 1.48% |
| Working capital | 12.8% of revenue growth | **Calibrated**, see below |
| Tax rate | 17% | Ex 2 — guided FY2027 effective rate 16–18% |
| WACC | 11.25% | **CAPM**: 4.7% risk-free + β × 4.23% ERP (both Ex 6) at a bottom-up semiconductor β of 1.55 |
| Terminal growth | 3% | **Judgment**, capped at the 4.7% risk-free rate |

### The working-capital figure is solved for, not quoted

This was the one default previously flagged as unverified. Exhibit 5 reports "working
capital absorption 19.3%", but on a different basis than this model's *% of incremental
revenue*. Solving instead for the value that reproduces FY2026 actual free cash flow:

```
NOPAT   130,387 × (1 − 15.1%)   = 110,699
less net capex (6,042 − 2,843)  =   3,199
=> implied working capital draw  =  10,925   on revenue growth of 85,441  →  12.8%
```

At 12.8% the model returns FY2026 free cash flow of **$96.60B against an actual $96.58B**.
The same reconciliation independently confirms the 1.5% net capex figure.

### Why WACC uses the bottom-up beta

Exhibit 6 gives two. The five-year regression beta of **2.21** is how the stock has
actually traded, but it bakes in a historic run; the bottom-up semiconductor beta of
**1.35–1.75** is estimated from the industry and is the standard choice for that reason.
Bull, Base and Bear take the low, mid and high end — **10.5% / 11.25% / 12.0%**.

## What the model says at these settings

| | Bear | Base | Bull |
|---|---|---|---|
| Year 1 growth | 64.0% | 82.25% | 95.0% |
| *anchor* | Q2 guidance holds, then flat sequentially — 81.6 + 91.0 × 3 = $354.6B. A **floor**: going lower requires H2 below an already-guided Q2. | consensus | ahead of consensus, on Ex 8's ~$730B hyperscaler capex and ~$1T Blackwell + Rubin visibility |
| FY2031 revenue | $718B (51% of TAM) | $1,088B (78%) | $1,316B (94%) |
| Year 5 margin / WACC / terminal | 45% / 12.0% / 2% | 55% / 11.25% / 3% | 62% / 10.5% / 4% |
| **Value per share** | **$94.26** (−50.4%) | **$194.91** (+2.6%) | **$315.52** (+66.1%) |

Probability-weighted at the opening 25/50/25 split: **$199.90, +5.2%, HOLD at low
conviction** — the weighted mean sits inside the HOLD band while 75% of the probability
sits above the price, and the app reports that disagreement rather than blending it away.

Three things worth knowing before you read anything into that:

- **The base case lands on the price, and that is the finding.** Anchoring Year 1 on
  consensus and discounting at CAPM produces $194.91 against a $190.01 close — a 2.6% gap.
  The model's enterprise value of $4,614B against the market-implied $4,487B says the same
  thing. **The market is priced roughly for consensus.** So the argument about NVIDIA is
  not about the level; it is about the *shape of the deceleration curve* — which is exactly
  what the Year-1-to-Year-5 taper lets you argue with.
- **No single driver has to do anything heroic.** Every break-even sits within about 1.5
  percentage points of its own opening setting, and all five read *defensible*. Contrast
  the sell-side: at Exhibit 6's **$302.83** consensus target, the required Year-5 margin
  (93%) exceeds the gross margin, terminal growth cannot reach it at all, and both growth
  routes imply more revenue than the entire industry is forecast to reach.
- **Terminal value is still roughly half of enterprise value**, and one point on WACC or
  terminal growth moves the answer far more than one point on Year-1 growth. The inputs
  that matter most remain the two nobody can observe.

Treat the output as a tool for testing which assumptions a price implies, not as a price
target.

## Coursework

FIN 6515.21 — Fall 2026.
