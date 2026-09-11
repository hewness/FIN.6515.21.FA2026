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

11 tests cover the valuation math, including a case simple enough to verify by hand,
the cash/debt bridge, the growth taper, the terminal-value guardrail, and the
sensitivity grid's directional behaviour.

## Layout

| File | Contains |
|---|---|
| `dcf.py` | The valuation math. Pure functions, no UI imports, independently testable. |
| `viz.py` | Diverging color scale (computed in OKLab) and the heatmap renderer. |
| `app.py` | Gradio UI — sliders, the valuation panel, and the two tabs. |
| `test_dcf.py` | The test suite. |

## What the model does

1. **Projects revenue** using a growth rate that glides from a Year-1 rate to a Year-5
   rate, then tapers toward the long-run terminal rate — so hypergrowth fades rather
   than stopping abruptly.
2. **Converts revenue to cash**: gross margin → operating expenses → EBIT → tax →
   NOPAT, with free cash flow assumed at 90% of NOPAT.
3. **Discounts** each year at the WACC.
4. **Adds a terminal value** via Gordon Growth. The model refuses to value a scenario
   where WACC does not exceed terminal growth, rather than returning a confident wrong
   number.
5. **Bridges to per-share value**: enterprise value + cash − debt ÷ shares outstanding.

The **Sensitivity** tab revalues the company across a grid of WACC (8–14%) and terminal
growth (1–5%) rates, holding your other slider settings fixed. Blue cells are worth more
than the market price, red less, with a neutral midpoint at fair value.

## On the assumptions — read this before quoting a number

The starting figures are NVIDIA's FY2025 actuals: revenue $130.5B, cash $43.2B, debt
$8.5B, 24.5B shares, reference price $180.

**Everything else is an input you set, not a researched estimate.** The slider defaults
were chosen to make the model run, and at least one of them is deliberately
conservative: the opex default of **25% of revenue implies a 50% operating margin, while
NVIDIA's actual FY2025 operating margin was 62.4%**. That single assumption is worth
roughly $31/share. The app therefore opens on ~$114/share and a SELL signal; correcting
the opex to ~12.6% moves it to ~$145/share.

Two further caveats worth knowing:

- **Terminal value is ~60% of enterprise value** under default settings. Most of the
  answer comes from one formula about a year you cannot see.
- **WACC and terminal growth dominate.** One percentage point on either moves value
  ~13%; one point on Year-1 revenue growth moves it ~1.7%. The inputs that matter most
  are the two nobody can observe.

Treat the output as a tool for testing which assumptions a price implies, not as a price
target.

## Coursework

FIN 6515.21 — Fall 2026.
