---
title: NVIDIA DCF Valuation
emoji: 📈
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 6.26.0
app_file: app.py
short_description: Interactive DCF for NVIDIA, sourced from FY2026 filings
python_version: "3.12"
---

# NVIDIA DCF Valuation

An interactive discounted cash flow model for NVIDIA (NVDA). Move a slider and the
valuation recomputes — no submit button, no spreadsheet.

Every opening assumption is sourced from NVIDIA's FY2026 exhibits, valued at the
**29 July 2026 close of $190.01**. The model opens at **$194.91 per share, +2.6%** —
consensus-anchored and within 3% of the market, so the interesting argument is about the
*shape of the deceleration curve*, not the level.

## What to try

- **Move Year-1 and Year-5 revenue growth.** Year 1 opens on consensus (+82.25%,
  implying FY2027 revenue of $393.6B). Year 5 is what decides whether NVIDIA ends up
  with 51%, 78% or 94% of the 2030 AI accelerator market.
- **Switch "Forecast detail" to per-year.** The same forecast, expressed as five explicit
  years instead of a taper — the valuation should not move when you toggle it.
- **Tick "Scenario analysis".** The model splits into three complete, independent cases
  (Bear $94, Base $195, Bull $316), each with its own full assumption panel and its own
  five views. Drag the two cut points to reweight them.
- **Read the break-even table** on the Scenarios tab. Every driver is reverse-solved to
  the value that would justify today's price. At $190 all five read *defensible*; at the
  sell-side's $302.83 target, none of them do.

## The five views

**Valuation** — KPI cards, a year-by-year forecast table, and the equity bridge, with the
Gordon Growth arithmetic printed using the current scenario's own numbers so the terminal
value can be checked rather than taken on trust.

**Projection** — revenue, free cash flow, and the *present value* of free cash flow. The
third line is the one to watch: it peaks mid-forecast and then falls, because past that
point discounting outruns growth. That is why terminal value dominates.

**Valuation Waterfall** — the same bridge as a chart, where the terminal value bar
reaches further than every projected year combined.

**Two sensitivity grids** — WACC × terminal growth, and Year-5 operating margin ×
terminal growth. They share their row axis so the two can be read against each other.
Blue is worth more than the market price, red less.

## Notes on the model

- WACC is **derived, not assumed**: 4.7% risk-free + β × 4.23% equity risk premium, on a
  bottom-up semiconductor β of 1.35–1.75.
- Working capital is **calibrated**: 12.8% of incremental revenue is the figure that
  reproduces FY2026 actual free cash flow to within $0.02B.
- Inputs are validated in two tiers — a few combinations are refused outright (a terminal
  multiple above 100× is arithmetic, not valuation), and others are valued with an amber
  notice explaining why the answer is suspect.

Treat the output as a tool for testing which assumptions a price implies, not as a price
target. Built for FIN 6515.21, Fall 2026.
