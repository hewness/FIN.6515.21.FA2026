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

25 tests. `test_dcf.py` covers the valuation math — including a case simple enough to
verify by hand, the cash/debt bridge, both growth/margin schedules, the free cash flow
drivers, and the terminal-value guardrail. `test_app_wiring.py` covers the Gradio
wiring, which binds sliders to the model **positionally**: it asserts the component list
and the handler signature stay in lockstep, so a slider added or moved in one place but
not the other fails loudly instead of silently valuing the wrong assumption.

## Layout

| File | Contains |
|---|---|
| `dcf.py` | The valuation math. Pure functions, no UI imports, independently testable. |
| `viz.py` | Diverging color scale (computed in OKLab) and the heatmap renderer. |
| `app.py` | Gradio UI — sliders, the valuation panel, and the two tabs. |
| `test_dcf.py` | Valuation math tests. |
| `test_app_wiring.py` | Guards on the UI-to-model binding. |

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
6. **Bridges to per-share value**: enterprise value + cash − debt ÷ shares outstanding.

The **Valuation** tab shows KPI cards, a Year-1 cash flow build, and the full bridge. The
**Sensitivity** tab revalues the company across a grid of WACC (8–14%) and terminal
growth (1–5%) rates, holding your other slider settings fixed. Blue cells are worth more
than the market price, red less, with a neutral midpoint at fair value.

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
