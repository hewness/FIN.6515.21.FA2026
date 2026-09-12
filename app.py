"""Interactive DCF valuation app for NVIDIA."""

import os

import gradio as gr

from dcf import (
    BOTTOM_UP_BETA, CONSENSUS_TARGET, EQUITY_RISK_PREMIUM, NVDA_DEFAULTS, RISK_FREE,
    break_even, capm_wacc, growth_schedule, margin_schedule, probability_split,
    recommend, run_dcf, sensitivity_grid, weighted_valuation_from_cases,
)
from viz import (
    render_break_even, render_heatmap, render_probability_bar,
    render_projection_chart, render_recommendation, render_scenario_panel,
    render_warnings, render_waterfall,
)

# Upside thresholds that separate the three signals.
BUY_ABOVE = 0.15
SELL_BELOW = -0.15

SIGNAL_COLORS = {
    "BUY": ("#16a34a", "rgba(22,163,74,0.12)"),
    "HOLD": ("#d97706", "rgba(217,119,6,0.12)"),
    "SELL": ("#dc2626", "rgba(220,38,38,0.12)"),
}

# Sensitivity axes. Both grids share the terminal-growth rows, so the two can be
# read against each other; only the columns differ.
WACC_AXIS = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
TERMINAL_AXIS = [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05]
# Brackets the 55% Year-5 default and the 65.6% Year-1 figure from Q1 FY2027.
MARGIN_AXIS = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

TAPER, PER_YEAR = "Taper Y1 to Y5", "Set each year"

# --- opening assumptions, one dict per case ------------------------------------
# Every figure traces to NVIDIA_Exhibits.xlsx (compiled 30 July 2026). Year-1 margin
# is the same in all three: Q1 FY2027 is banked and Q2 is guided, so Year 1 is close
# to known and the cases differentiate on the Year-5 margin instead. WACC is the CAPM
# build-up at the low / mid / high end of the bottom-up semiconductor beta.
BETA_BULL, BETA_BASE, BETA_BEAR = BOTTOM_UP_BETA


def _wacc_pct(beta):
    return round(capm_wacc(beta) * 100, 4)


BASE_DEFAULTS = dict(
    # Ex 6: consensus FY2027 revenue $393.6B against FY2026's $215.9B.
    y1_growth=82.25,
    # Lands FY2031 revenue at $1,088B -- 78% of Ex 8's $1.4T 2030 accelerator market,
    # inside the 75-85% share band the exhibit gives. 0.25 rather than 0.00 so the
    # taper's four steps land exactly on the sliders' 0.25 grid.
    y5_growth=0.25,
    y1_margin=65.6, y5_margin=55.0,
    net_capex=1.5, nwc=12.8, tax=17.0,
    wacc=_wacc_pct(BETA_BASE), terminal=3.0, horizon=10,
)
# Bear: Q2 guidance holds and then revenue is flat sequentially -- 81.6 + 91.0 x 3 =
# $354.6B, +64%. That is a floor, not a guess: going lower requires H2 to fall below
# an already-guided Q2. FY2031 lands at 51% of the accelerator market, i.e. custom
# silicon and AMD take half of it.
BEAR_DEFAULTS = dict(BASE_DEFAULTS, y1_growth=64.0, y5_growth=-5.0, y5_margin=45.0,
                     wacc=_wacc_pct(BETA_BEAR), terminal=2.0)
# Bull: ~$421B in FY2027, ahead of consensus, on Ex 8's ~$730B of 2026 hyperscaler
# capex and ~$1T of cumulative Blackwell + Rubin visibility. FY2031 at 94% of the
# accelerator market -- share holds near its 2023 peak.
BULL_DEFAULTS = dict(BASE_DEFAULTS, y1_growth=95.0, y5_growth=0.0, y5_margin=62.0,
                     wacc=_wacc_pct(BETA_BULL), terminal=4.0)


def per_year_defaults(d):
    """A case's taper expressed as five explicit years.

    The per-year sliders open on the taper's own schedule, so switching mode at the
    opening settings does not move the valuation. Derived per case rather than held
    in one module-level list -- otherwise all three cases would open identically in
    per-year mode while their taper sliders differed.
    """
    return (growth_schedule(d["y1_growth"], d["y5_growth"], d["terminal"], 10)[:5],
            margin_schedule(d["y1_margin"], d["y5_margin"], horizon=10)[:5])


GROWTH_BY_YEAR, MARGIN_BY_YEAR = per_year_defaults(BASE_DEFAULTS)

CSS = """
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.kpi { border: 1px solid var(--border-color-primary); border-radius: 10px;
       padding: 14px 16px; background: var(--background-fill-secondary); }
.kpi .label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .06em;
              opacity: .65; margin-bottom: 6px; }
.kpi .value { font-size: 1.6rem; font-weight: 650; line-height: 1.15; }
.kpi .sub { font-size: 0.78rem; opacity: .6; margin-top: 4px; }
.bridge { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 0.9rem; }
.bridge td { padding: 7px 4px; border-bottom: 1px solid var(--border-color-primary); }
.bridge td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
.bridge tr.total td { font-weight: 700; border-bottom: none; }
.bridge caption { caption-side: top; text-align: left; font-size: 0.78rem;
                  text-transform: uppercase; letter-spacing: .06em; opacity: .65;
                  padding: 14px 0 2px; }
.warn { border: 1px solid #dc2626; background: rgba(220,38,38,0.08);
        border-radius: 10px; padding: 16px; }

/* Amber, not red: the model produced a number, it just comes with conditions. Same
   treatment as the recommendation's mean-vs-mass notice, so there is one visual
   language for "this computed, but be careful". */
.model-warn { border: 1px solid rgba(217,119,6,0.35); background: rgba(217,119,6,0.10);
              border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; }
.model-warn-head { font-size: 0.78rem; font-weight: 650; text-transform: uppercase;
                   letter-spacing: .05em; color: #d97706; margin-bottom: 6px; }
.model-warn ul { margin: 0; padding-left: 18px; }
.model-warn li { font-size: 0.85rem; line-height: 1.55; margin: 3px 0; }
.case-flag { color: #d97706; cursor: help; }

/* Slider caption. Recessive on purpose -- it sources the number above it without
   competing with the control for attention. */
.cap { display: block; font-size: 0.76rem; line-height: 1.5; opacity: .62;
       margin: -4px 0 2px; }

/* --- year-by-year projection --- */
.proj { width: 100%; border-collapse: collapse; font-size: 0.82rem;
        font-variant-numeric: tabular-nums; }
.proj caption { caption-side: top; text-align: left; font-size: 0.78rem;
                text-transform: uppercase; letter-spacing: .06em; opacity: .65;
                padding: 16px 0 8px; }
.proj th { font-weight: 550; font-size: 0.72rem; text-align: right;
           color: var(--body-text-color-subdued); padding: 4px 8px;
           border-bottom: 1px solid var(--border-color-primary); white-space: nowrap; }
.proj th:first-child { text-align: left; }
.proj td { text-align: right; padding: 5px 8px; white-space: nowrap;
           border-bottom: 1px solid var(--border-color-primary); }
.proj td:first-child { text-align: left; opacity: .7; }
.proj tbody tr:last-child td { border-bottom: 2px solid var(--border-color-primary); }
.proj tfoot td { font-weight: 650; border-bottom: none; padding-top: 8px; }
.proj tfoot td:first-child { text-align: right; opacity: 1; font-weight: 550; }
.proj-note { font-size: 0.78rem; color: var(--body-text-color-subdued);
             margin: 10px 0 0; line-height: 1.5; }

/* --- projection chart --- */
.chart-wrap { margin-top: 4px; }
.chart { width: 100%; height: auto; display: block; overflow: visible; }
.c-legend { display: flex; flex-wrap: wrap; gap: 18px; margin: 4px 0 12px; }
.c-key { display: inline-flex; align-items: center; gap: 7px; font-size: 0.8rem;
         color: var(--body-text-color-subdued); }
.c-key-line { display: inline-block; width: 18px; height: 2px; border-radius: 1px;
              background: var(--c-l); }
.c-grid, .c-axis { stroke: var(--border-color-primary); stroke-width: 1; fill: none; }
.c-axis { stroke-opacity: .9; }
.c-tick { font-size: 11px; fill: var(--body-text-color-subdued); text-anchor: middle;
          font-variant-numeric: tabular-nums; }
.c-tick-y { text-anchor: end; }
.c-line { fill: none; stroke: var(--c-l); stroke-width: 2;
          stroke-linejoin: round; stroke-linecap: round; }
/* 2px ring in the surface colour so markers stay legible where lines cross */
.c-end, .c-dot { fill: var(--c-l); stroke: var(--background-fill-primary); stroke-width: 2; }
.c-end-label { font-size: 11px; fill: var(--body-text-color); font-weight: 550;
               font-variant-numeric: tabular-nums; }
.c-note { font-size: 0.78rem; color: var(--body-text-color-subdued); margin: 8px 0 0; }

/* hover layer: transparent per-year bands drive a CSS-only crosshair */
.c-hit { fill: transparent; }
.c-hover { opacity: 0; pointer-events: none; }
.c-band:hover .c-hover, .c-band:focus-within .c-hover { opacity: 1; }
.c-cross { stroke: var(--body-text-color-subdued); stroke-width: 1; stroke-opacity: .55; }
.c-tip-bg { fill: var(--background-fill-secondary); stroke: var(--border-color-primary);
            stroke-width: 1; }
.c-tip { font-size: 11px; fill: var(--body-text-color); font-variant-numeric: tabular-nums; }
.c-tip-year { font-weight: 650; }
.c-tip-row { fill: var(--body-text-color); }

@media (prefers-color-scheme: dark) {
  .c-key-line { background: var(--c-d); }
  .c-line { stroke: var(--c-d); }
  .c-end, .c-dot { fill: var(--c-d); }
}
.dark .c-key-line { background: var(--c-d); }
.dark .c-line { stroke: var(--c-d); }
.dark .c-end, .dark .c-dot { fill: var(--c-d); }
html:not(.dark) .c-key-line { background: var(--c-l); }
html:not(.dark) .c-line { stroke: var(--c-l); }
html:not(.dark) .c-end, html:not(.dark) .c-dot { fill: var(--c-l); }

/* --- valuation waterfall --- */
.wf-wrap { margin-top: 4px; }
.wf { width: 100%; height: auto; display: block; }
.wf-grid { stroke: var(--border-color-primary); stroke-width: 1; }
.wf-zero { stroke: var(--body-text-color-subdued); stroke-width: 1; stroke-opacity: .7; }
.wf-link { stroke: var(--body-text-color-subdued); stroke-width: 1; stroke-opacity: .45; }
.wf-bar { fill: var(--c-l); }
.wf-tick { font-size: 11px; fill: var(--body-text-color-subdued); text-anchor: middle;
           font-variant-numeric: tabular-nums; }
.wf-tick-y { text-anchor: end; }
.wf-value { font-size: 11px; font-weight: 650; fill: var(--body-text-color);
            text-anchor: middle; font-variant-numeric: tabular-nums; }
.wf-cat { font-size: 10.5px; fill: var(--body-text-color-subdued); text-anchor: middle; }
/* Bars carry their own <title> tooltip -- on a bar chart the mark is the hit
   target, so there is no crosshair to reveal. */
.wf-hit { fill: transparent; }
.wf-note { font-size: 0.82rem; color: var(--body-text-color-subdued);
           margin: 10px 0 0; line-height: 1.5; }

@media (prefers-color-scheme: dark) { .wf-bar { fill: var(--c-d); } }
.dark .wf-bar { fill: var(--c-d); }
html:not(.dark) .wf-bar { fill: var(--c-l); }

/* The mode box: the toggle and, once checked, the split it controls -- one
   container, so they read as the same control. The border lives here and nowhere
   else; Gradio's own form box around the checkbox is flattened so the two do not
   nest, and there is no secondary grey fill. */
.mode-box { border: 1px solid var(--border-color-primary); border-radius: 10px;
            background: transparent; padding: 12px 14px 6px; margin-bottom: 14px;
            gap: 4px; }
.mode-box .form,
.mode-box .block,
.mode-box .gr-box { border: none !important; background: transparent !important;
                    box-shadow: none !important; padding: 0 !important; }
.mode-note p { font-size: 0.82rem; color: var(--body-text-color-subdued);
               margin: 2px 0 8px; }

/* Scenarios panel head: the verdict beside its supporting numbers. Shares the
   3fr/2fr ratio of the chart/table split below so one column edge runs the length
   of the panel. */
.sp-head { display: grid; gap: 20px; align-items: start; margin-bottom: 4px;
           grid-template-columns: minmax(0, 3fr) minmax(0, 2fr) minmax(0, 4fr); }
.sp-head > .rec { margin-bottom: 0; }
.sp-head-drivers { min-width: 0; }
.sp-head-drivers .be-wrap { margin-top: 0; }
/* Three columns need more room than two, so this breaks earlier: first to verdict +
   tiles over drivers, then to a single column. */
@media (max-width: 1250px) {
  .sp-head { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
  .sp-head-drivers { grid-column: 1 / -1; }
}
@media (max-width: 900px) { .sp-head { grid-template-columns: minmax(0, 1fr); } }

/* Stacked tiles run narrow, so they trade the big hero figure for a tighter box. */
.kpi-stack { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }
.kpi-stack .kpi { padding: 11px 14px; }
.kpi-stack .kpi .value { font-size: 1.35rem; }
.kpi-stack .kpi .label { margin-bottom: 3px; }

/* Scenarios panel: the value chart and the by-scenario table read together, so
   they sit side by side. Collapses to one column when there is not room. */
.sp-split { display: grid; gap: 20px; align-items: start; margin-top: 6px;
            grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
.sp-split-chart, .sp-split-table { min-width: 0; }
.sp-split-table .bridge { margin-top: 0; }
@media (max-width: 900px) { .sp-split { grid-template-columns: minmax(0, 1fr); } }

/* The table is in a narrower column now, so it trades a little air for fit. */
.bridge.compact { font-size: 0.82rem; }
.bridge.compact td { padding: 5px 4px; }
.bridge.compact caption { padding-top: 0; }

/* --- recommendation & break-even --- */
.rec { border: 1px solid var(--border-color-primary); border-left: 4px solid var(--rec);
       border-radius: 10px; padding: 16px 18px; margin-bottom: 14px;
       background: var(--background-fill-secondary); }
.rec-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: .08em;
             opacity: .6; margin-bottom: 6px; }
.rec-verdict { font-size: 1.7rem; font-weight: 700; line-height: 1.1; }
.rec-verdict.rec-verdict.rec-verdict { color: var(--rec); }   /* tripled: see the heatmap note */
.rec-conv { font-size: 0.95rem; font-weight: 550; color: var(--body-text-color-subdued); }
.rec-range { font-size: 0.95rem; margin-top: 8px; }
.rec-mass { font-size: 0.85rem; color: var(--body-text-color-subdued); margin-top: 4px; }
.rec-why { font-style: italic; }
.rec-warn { font-size: 0.85rem; line-height: 1.55; margin: 12px 0 0; padding: 10px 12px;
            border-radius: 8px; background: rgba(217,119,6,0.10);
            border: 1px solid rgba(217,119,6,0.35); }

.be-wrap { margin-top: 22px; }
.be-cap { font-size: 0.78rem; text-transform: uppercase; letter-spacing: .06em;
          opacity: .65; margin-bottom: 8px; }
.be { width: 100%; height: auto; display: block; }
.be-track { stroke: var(--border-color-primary); stroke-width: 4; stroke-linecap: round; }
.be-join { stroke: var(--c-dumb); stroke-width: 2; stroke-opacity: .55; }
.be-yours { fill: var(--background-fill-primary); stroke: var(--c-dumb); stroke-width: 2; }
.be-req { fill: var(--c-dumb); stroke: var(--background-fill-primary); stroke-width: 2; }
.be-label { font-size: 12px; font-weight: 550; fill: var(--body-text-color);
            text-anchor: end; }
.be-verdict { font-size: 10.5px; font-weight: 650; text-anchor: end; }
.be-reason { font-size: 10.5px; fill: var(--body-text-color-subdued); }
.be-num { font-size: 11px; fill: var(--body-text-color); font-weight: 550;
          font-variant-numeric: tabular-nums; }
.be-na { font-size: 10.5px; fill: var(--body-text-color-subdued); font-style: italic; }
.be-summary { font-size: 0.85rem; line-height: 1.55; margin: 10px 0 0;
              color: var(--body-text-color); }

:root { --c-dumb: #2a78d6; }
@media (prefers-color-scheme: dark) { :root { --c-dumb: #3987e5; } }
.dark { --c-dumb: #3987e5; }
html:not(.dark) { --c-dumb: #2a78d6; }

/* --- scenario panel --- */
.sp-wrap { margin-top: 6px; }
.sp { width: 100%; height: auto; display: block; }
.sp-grid { stroke: var(--border-color-primary); stroke-width: 1; }
.sp-bar-r { fill: var(--c-l); }
.sp-name { font-size: 11.5px; font-weight: 550; fill: var(--body-text-color);
           text-anchor: end; }
.sp-val { font-size: 11px; fill: var(--body-text-color); font-weight: 550;
          font-variant-numeric: tabular-nums; }
.sp-na { font-size: 11px; fill: var(--body-text-color-subdued); font-style: italic; }
.sp-tick { font-size: 10.5px; fill: var(--body-text-color-subdued); text-anchor: middle; }

/* probability allocation bar: ordinal grey ramp, read-only */
.sp-bar { display: flex; width: 100%; height: 30px; border-radius: 6px;
          overflow: hidden; margin: 2px 0 10px; gap: 2px;
          background: var(--border-color-primary); }
.sp-seg { display: flex; align-items: center; justify-content: center;
          background: var(--c-l); min-width: 0; }
/* Ink tripled for the same reason as the heatmap cells -- see the note there. The
   Base segment is a light grey, so losing its ink to a dark theme's body colour
   would put white text on a near-white segment. */
.sp-seg-l { font-size: 0.72rem; font-weight: 600;
            white-space: nowrap; overflow: hidden; padding: 0 4px;
            letter-spacing: .01em; }
.sp-seg-l.sp-seg-l.sp-seg-l { color: var(--ink-l); }
.sp-note { font-size: 0.8rem; color: var(--body-text-color-subdued);
           margin: 8px 0 0; line-height: 1.5; }
.sp-partial { color: #d97706; font-weight: 600; }

@media (prefers-color-scheme: dark) {
  .sp-bar-r { fill: var(--c-d); }
  .sp-seg { background: var(--c-d); }
  .sp-seg-l.sp-seg-l.sp-seg-l { color: var(--ink-d); }
}
.dark .sp-bar-r { fill: var(--c-d); }
.dark .sp-seg { background: var(--c-d); }
.dark .sp-seg-l.sp-seg-l.sp-seg-l { color: var(--ink-d); }
html:not(.dark) .sp-bar-r { fill: var(--c-l); }
html:not(.dark) .sp-seg { background: var(--c-l); }
html:not(.dark) .sp-seg-l.sp-seg-l.sp-seg-l { color: var(--ink-l); }

/* --- sensitivity heatmap --- */
.hm-scroll { overflow-x: auto; }
.hm { border-collapse: separate; border-spacing: 2px; width: 100%; }
.hm-cap { caption-side: top; text-align: left; font-size: 0.82rem;
          color: var(--body-text-color-subdued); padding-bottom: 10px; }
.hm th { font-weight: 550; font-size: 0.78rem; color: var(--body-text-color-subdued);
         padding: 5px 7px; white-space: nowrap; }
.hm-corner { text-align: left; font-size: 0.72rem; }
.hm-rh { text-align: right; font-variant-numeric: tabular-nums; }
.hm-cell { text-align: center; padding: 9px 6px; border-radius: 5px; min-width: 62px;
           line-height: 1.2; cursor: default; background: var(--bg-l); }
.hm-v { display: block; font-size: 0.95rem; font-weight: 620;
        font-variant-numeric: tabular-nums; }
.hm-u { display: block; font-size: 0.72rem; opacity: .78;
        font-variant-numeric: tabular-nums; }
.hm-na { text-align: center; color: var(--body-text-color-subdued); opacity: .5; }
.hm-legend { display: flex; flex-wrap: wrap; gap: 2px; margin-top: 16px; align-items: flex-end; }
.hm-key { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.hm-sw { display: block; width: 42px; height: 12px; border-radius: 3px; background: var(--bg-l); }
.hm-kl { font-size: 0.68rem; color: var(--body-text-color-subdued);
         font-variant-numeric: tabular-nums; }

@media (prefers-color-scheme: dark) {
  .hm-cell { background: var(--bg-d); }
  .hm-sw { background: var(--bg-d); }
}
.dark .hm-cell { background: var(--bg-d); }
.dark .hm-sw { background: var(--bg-d); }
html:not(.dark) .hm-cell { background: var(--bg-l); }
html:not(.dark) .hm-sw { background: var(--bg-l); }

/* Ink is set separately, and at doubled specificity, because Gradio ships
       .gradio-container-<version> .prose * { color: var(--body-text-color) }
   That is a (0,2,0) rule which sets `color` DIRECTLY on every descendant of a gr.HTML.
   It outranks any single-class rule of ours, and because it paints the descendants
   directly it also defeats inheritance from the cell -- so the <span>s carrying the
   value and the upside took the theme's body colour instead of the ink chosen to suit
   their own cell. At the diverging ramp's neutral step the cell is near-white, so in a
   dark theme that meant white text on a white cell.

   Tripling the class buys the specificity back without !important and without depending
   on Gradio's version-stamped container class. Every variant is tripled equally, so the
   light/dark cascade keeps exactly the order it had. */
.hm-cell.hm-cell.hm-cell,
.hm-cell.hm-cell.hm-cell .hm-v,
.hm-cell.hm-cell.hm-cell .hm-u { color: var(--ink-l); }
@media (prefers-color-scheme: dark) {
  .hm-cell.hm-cell.hm-cell,
  .hm-cell.hm-cell.hm-cell .hm-v,
  .hm-cell.hm-cell.hm-cell .hm-u { color: var(--ink-d); }
}
.dark .hm-cell.hm-cell.hm-cell,
.dark .hm-cell.hm-cell.hm-cell .hm-v,
.dark .hm-cell.hm-cell.hm-cell .hm-u { color: var(--ink-d); }
html:not(.dark) .hm-cell.hm-cell.hm-cell,
html:not(.dark) .hm-cell.hm-cell.hm-cell .hm-v,
html:not(.dark) .hm-cell.hm-cell.hm-cell .hm-u { color: var(--ink-l); }
"""


def signal_for(upside: float) -> str:
    if upside > BUY_ABOVE:
        return "BUY"
    if upside < SELL_BELOW:
        return "SELL"
    return "HOLD"


def _kpi(label: str, value: str, sub: str = "", color: str = "", bg: str = "") -> str:
    style = f' style="color:{color};background:{bg}"' if color else ""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="kpi"{style}><div class="label">{label}</div>'
        f'<div class="value">{value}</div>{sub_html}</div>'
    )


def _signed_b(value: float) -> str:
    """Accounting style: negatives in parentheses, as a finance reader expects."""
    if value < 0:
        return f"(${abs(value):,.1f}B)"
    return f"${value:,.1f}B"


def _projection_table(r) -> str:
    """Year-by-year forecast: revenue through to each year's present value.

    The gap between NOPAT and free cash flow is net capex plus the change in
    working capital, both set on the Cash flow sliders.
    """
    body = "".join(
        f"<tr><td>{row.year}</td>"
        f"<td>{row.growth_rate:+.1%}</td>"
        f"<td>${row.revenue:,.1f}</td>"
        f"<td>{row.operating_margin:.1%}</td>"
        f"<td>${row.operating_income:,.1f}</td>"
        f"<td>${row.nopat:,.1f}</td>"
        f"<td>${row.free_cash_flow:,.1f}</td>"
        f"<td>{row.discount_factor:.3f}</td>"
        f"<td>${row.pv_of_fcf:,.1f}</td></tr>"
        for row in r.rows
    )

    final = r.rows[-1]
    # Spell the Gordon Growth arithmetic out with this scenario's own numbers, so
    # the terminal value is checkable on screen rather than taken on trust.
    formula = (
        f"<strong>Gordon Growth:</strong> terminal value = "
        f"${final.free_cash_flow:,.1f}B &times; {1 + r.terminal_growth:.3f} &divide; "
        f"({r.wacc:.3f} &minus; {r.terminal_growth:.3f}) = ${r.terminal_value:,.0f}B, "
        f"discounted at {final.discount_factor:.3f} to ${r.pv_of_terminal:,.0f}B today."
    )

    return f"""
    <div class="hm-scroll">
      <table class="proj">
        <caption>Forecast &mdash; all figures $B except per-year rates</caption>
        <thead><tr>
          <th>Yr</th><th>Growth</th><th>Revenue</th><th>Op margin</th><th>EBIT</th>
          <th>NOPAT</th><th>FCF</th><th>Disc. factor</th><th>PV of FCF</th>
        </tr></thead>
        <tbody>{body}</tbody>
        <tfoot>
          <tr class="subtotal"><td colspan="8">PV of forecast cash flows</td>
              <td>${r.pv_of_forecast:,.1f}</td></tr>
          <tr class="terminal"><td colspan="8">Terminal value (Gordon Growth), discounted</td>
              <td>${r.pv_of_terminal:,.1f}</td></tr>
        </tfoot>
      </table>
    </div>
    <p class="proj-note">{formula}</p>
    """


def build_valuation(mode, growth_taper, margin_taper, growth_years, margin_years,
                    terminal_growth, tax_rate, net_capex_pct, nwc_pct,
                    wacc, horizon):
    """Run the model and render both panels. Percentages in, decimals to the model."""
    per_year = mode == PER_YEAR
    shared = dict(
        year_1_growth=growth_taper[0] / 100,
        year_5_growth=growth_taper[1] / 100,
        growth_rates=[g / 100 for g in growth_years] if per_year else None,
        year_1_margin=margin_taper[0] / 100,
        year_5_margin=margin_taper[1] / 100,
        operating_margins=[m / 100 for m in margin_years] if per_year else None,
        tax_rate=tax_rate / 100,
        net_capex_pct=net_capex_pct / 100,
        nwc_pct_of_growth=nwc_pct / 100,
        horizon=int(horizon),
    )

    price = NVDA_DEFAULTS["current_price"]
    heat = render_heatmap(
        sensitivity_grid("wacc", WACC_AXIS, "terminal_growth", TERMINAL_AXIS, **shared),
        WACC_AXIS, TERMINAL_AXIS, price,
        x_label="WACC", y_label="Terminal growth",
    )
    # `shared` leaves WACC out because the grid above varies it as an axis. This
    # grid does not, so it has to pass the slider's value through explicitly --
    # otherwise every cell would quietly use run_dcf's 10% default and the WACC
    # slider would have no effect on this tab at all.
    margin_heat = render_heatmap(
        sensitivity_grid("year_5_margin", MARGIN_AXIS,
                         "terminal_growth", TERMINAL_AXIS,
                         wacc=wacc / 100, **shared),
        MARGIN_AXIS, TERMINAL_AXIS, price,
        x_label="Year 5 operating margin", y_label="Terminal growth",
    )

    try:
        r = run_dcf(wacc=wacc / 100, terminal_growth=terminal_growth / 100, **shared)
    except ValueError as exc:
        # Every panel gets the warning -- never a half-drawn chart or table.
        warning = f'<div class="warn"><strong>Cannot value this scenario.</strong><br>{exc}</div>'
        return warning, warning, warning, heat, margin_heat

    signal = signal_for(r.upside)
    color, bg = SIGNAL_COLORS[signal]
    direction = "Upside" if r.upside >= 0 else "Downside"
    tv_share = r.pv_of_terminal / r.enterprise_value

    kpis = "".join([
        _kpi("Intrinsic value / share", f"${r.value_per_share:,.2f}",
             f"vs. ${r.current_price:,.2f} market price"),
        _kpi(direction, f"{r.upside:+.1%}",
             f"${r.value_per_share - r.current_price:+,.2f} per share",
             color=color, bg=bg),
        _kpi("Signal", signal,
             f"buy &gt;{BUY_ABOVE:.0%} &middot; sell &lt;{SELL_BELOW:.0%}", color=color, bg=bg),
        _kpi("Enterprise value", f"${r.enterprise_value:,.0f}B",
             f"{tv_share:.0%} of it is terminal value"),
    ])

    bridge = f"""
    <table class="bridge">
      <caption>Valuation bridge</caption>
      <tr><td>PV of forecast cash flows ({len(r.rows)} yrs)</td><td>${r.pv_of_forecast:,.0f}B</td></tr>
      <tr><td>PV of terminal value</td><td>${r.pv_of_terminal:,.0f}B</td></tr>
      <tr><td>Enterprise value</td><td>${r.enterprise_value:,.0f}B</td></tr>
      <tr><td>+ Cash</td><td>${r.cash:,.1f}B</td></tr>
      <tr><td>&minus; Debt</td><td>${r.debt:,.1f}B</td></tr>
      <tr><td>= Net debt{" (net cash)" if r.net_debt < 0 else ""}</td>
          <td>{_signed_b(r.net_debt)}</td></tr>
      <tr><td>Equity value</td><td>${r.equity_value:,.0f}B</td></tr>
      <tr><td>&divide; Shares outstanding</td><td>{r.shares:,.1f}B</td></tr>
      <tr class="total"><td>Intrinsic value per share</td><td>${r.value_per_share:,.2f}</td></tr>
    </table>
    """
    return (f'{render_warnings(r.warnings)}'
            f'<div class="kpi-grid">{kpis}</div>{_projection_table(r)}{bridge}',
            render_projection_chart(r),
            render_waterfall(r),
            heat,
            margin_heat)


CUT_A_DEFAULT, CUT_B_DEFAULT = 25.0, 75.0

#: Controls in one assumption panel. Four panels exist: the left pane plus one per case.
CASE_PANEL_SIZE = 21


def assumptions_from_panel(values) -> dict:
    """One panel's 21 slider values, in panel order, as a complete run_dcf dict.

    Percentages in, decimals out. Returns every keyword `run_dcf` needs, so the
    caller can value a case directly rather than merging overrides onto a base --
    see `weighted_valuation_from_cases` for why that distinction matters.
    """
    (forecast_mode, y1g, y5g, g1, g2, g3, g4, g5, y1m, y5m,
     m1, m2, m3, m4, m5, net_capex_pct, nwc_pct, tax_pct, wacc_pct,
     terminal_pct, years) = values
    per_year = forecast_mode == PER_YEAR
    return dict(
        year_1_growth=y1g / 100,
        year_5_growth=y5g / 100,
        growth_rates=[v / 100 for v in (g1, g2, g3, g4, g5)] if per_year else None,
        year_1_margin=y1m / 100,
        year_5_margin=y5m / 100,
        operating_margins=[v / 100 for v in (m1, m2, m3, m4, m5)] if per_year else None,
        tax_rate=tax_pct / 100,
        net_capex_pct=net_capex_pct / 100,
        nwc_pct_of_growth=nwc_pct / 100,
        wacc=wacc_pct / 100,
        terminal_growth=terminal_pct / 100,
        horizon=int(years),
    )


def build_scenarios(cut_a, cut_b, base_values, bear_values, bull_values):
    """Weight three complete, independent cases. Returns (panel, probability bar)."""
    cases = {
        "Base": assumptions_from_panel(base_values),
        "Bear": assumptions_from_panel(bear_values),
        "Bull": assumptions_from_panel(bull_values),
    }
    p_bear, p_base, p_bull = probability_split(cut_a, cut_b)
    wv = weighted_valuation_from_cases([
        ("Bear", p_bear, cases["Bear"]),
        ("Base", p_base, cases["Base"]),
        ("Bull", p_bull, cases["Bull"]),
    ])
    bar = render_probability_bar((p_bear, p_base, p_bull))

    if wv.all_failed:
        return ('<div class="warn"><strong>No scenario can be valued.</strong><br>'
                "Every case has WACC at or below its terminal growth.</div>", bar)

    rec = recommend(wv, BUY_ABOVE, SELL_BELOW)
    signal = signal_for(wv.upside)
    color, bg = SIGNAL_COLORS[signal]
    kpis = "".join([
        _kpi("Probability-weighted value", f"${wv.weighted_value:,.2f}",
             f"vs. ${wv.current_price:,.2f} market price"),
        _kpi("Upside" if wv.upside >= 0 else "Downside", f"{wv.upside:+.1%}",
             f"on the weighted mean alone: {signal}", color=color, bg=bg),
        _kpi("P(worth more than price)", f"{wv.probability_above_price:.0%}",
             "summed probability of the cases above it"),
    ])

    body = ""
    for s in wv.scenarios:
        if s.result is None:
            body += (f'<tr><td>{s.name}</td><td>{s.probability:.0%}</td>'
                     f'<td colspan="3">cannot be valued</td></tr>')
            continue
        flag = ""
        if s.result.warnings:
            codes = ", ".join(w.code.replace("_", " ") for w in s.result.warnings)
            flag = (f' <span class="case-flag" title="{codes}">&#9888;</span>')
        body += (
            f'<tr><td>{s.name}{flag}</td><td>{s.weight:.0%}</td>'
            f'<td>${s.result.value_per_share:,.2f}</td>'
            f'<td>{s.result.upside:+.1%}</td>'
            f'<td>${s.contribution:,.2f}</td></tr>'
        )

    partial = ""
    valued = [s for s in wv.scenarios if s.result]
    if wv.valued_mass < 0.999:
        partial = (f'<span class="sp-partial">Weighted over {len(valued)} of '
                   f'{len(wv.scenarios)} cases ({wv.valued_mass:.0%} of probability '
                   f'mass).</span> ')

    return (
        # Recommendation and the three tiles share a row, tiles stacked on the right.
        # Same 3fr/2fr split as the chart and table below, so the column edge runs
        # straight down the panel.
        f'<div class="sp-head">'
        f'  {render_recommendation(rec, wv.current_price)}'
        f'  <div class="kpi-stack">{kpis}</div>'
        f'  <div class="sp-head-drivers">'
        f'    {render_break_even(break_even(cases["Base"], wv.current_price), wv.current_price)}'
        f'  </div>'
        f'</div>'
        # Chart and table side by side rather than stacked: the panel was long enough
        # to scroll, and the two are read together anyway. A CSS grid does this because
        # the whole panel is one gr.HTML string, not separate Gradio columns.
        f'<div class="sp-split">'
        f'  <div class="sp-split-chart">{render_scenario_panel(wv)}</div>'
        f'  <div class="sp-split-table">'
        f'    <table class="bridge compact"><caption>By scenario</caption>'
        f'    <tr><td>Case</td><td>Weight</td><td>Value</td><td>vs price</td>'
        f'    <td>Contribution</td></tr>{body}</table>'
        f'  </div>'
        f'</div>'
        f'<p class="sp-note">{partial}Weighting applies to the <em>values</em>, not the '
        f'assumptions &mdash; the model is non-linear, so averaging the inputs and '
        f'valuing once would give a materially different answer.</p>',
        bar,
    )


with gr.Blocks(title="NVIDIA DCF Valuation") as demo:
    gr.Markdown("# NVIDIA DCF Valuation")
    gr.Markdown(
        f"Revenue ${NVDA_DEFAULTS['revenue']}B &middot; cash ${NVDA_DEFAULTS['cash']}B &middot; "
        f"debt ${NVDA_DEFAULTS['debt']}B &middot; {NVDA_DEFAULTS['shares']}B shares &middot; "
        f"price ${NVDA_DEFAULTS['current_price']:.2f}. Move a slider to revalue."
    )

    def assumption_panel(defaults=None):
        """One complete 21-control assumption panel.

        Returns the controls in `valuate`'s parameter order, plus the four groups
        the taper/per-year toggle shows and hides. Four of these exist -- the left
        pane and one per case -- built from this single definition so the panels
        cannot drift apart.
        """
        d = {**BASE_DEFAULTS, **(defaults or {})}
        growth_by_year, margin_by_year = per_year_defaults(d)
        gr.Markdown("### Forecast detail")
        panel_mode = gr.Radio([TAPER, PER_YEAR], value=TAPER,
                              label="Growth & margin inputs")

        gr.Markdown("### Revenue growth")
        with gr.Group() as growth_taper_group:
            # Max 120, not 100: the bull case opens at 95, so a 100 ceiling leaves no
            # room to stress the input it is most worth stressing.
            y1g = gr.Slider(-20, 120, d["y1_growth"], step=0.25,
                            label="Year 1 revenue growth (%)")
            y5g = gr.Slider(-10, 60, d["y5_growth"], step=0.25,
                            label="Year 5 revenue growth (%)")
        with gr.Group(visible=False) as growth_year_group:
            growth = [gr.Slider(-20, 120, growth_by_year[i], step=0.25,
                                label=f"Year {i + 1} revenue growth (%)")
                      for i in range(5)]

        gr.Markdown("### Operating margin")
        with gr.Group() as margin_taper_group:
            y1m = gr.Slider(0, 90, d["y1_margin"], step=0.05,
                            label="Year 1 operating margin (%)")
            y5m = gr.Slider(0, 90, d["y5_margin"], step=0.05,
                            label="Year 5 operating margin (%)")
        with gr.Group(visible=False) as margin_year_group:
            margins = [gr.Slider(0, 90, margin_by_year[i], step=0.05,
                                 label=f"Year {i + 1} operating margin (%)")
                       for i in range(5)]

        gr.Markdown("### Cash flow")
        capex = gr.Slider(0, 25, d["net_capex"], step=0.1,
                          label="Net capex (% of revenue)")
        # Step 0.1, not 0.5: the 12.8% default is calibrated to FY2026 actual free cash
        # flow, and a coarser grid would round the calibration away.
        work_cap = gr.Slider(0, 50, d["nwc"], step=0.1,
                             label="Working capital (% of revenue growth)")
        tax = gr.Slider(0, 40, d["tax"], step=0.5, label="Tax rate (%)")

        gr.Markdown("### Discount rate")
        discount = gr.Slider(4, 20, d["wacc"], step=0.25, label="WACC (%)")
        gr.Markdown(
            f"<span class='cap'>CAPM: {RISK_FREE:.1%} risk-free + &beta; &times; "
            f"{EQUITY_RISK_PREMIUM:.2%} equity risk premium. Bottom-up semiconductor "
            f"&beta; {BOTTOM_UP_BETA[0]}&ndash;{BOTTOM_UP_BETA[-1]}.</span>"
        )
        terminal = gr.Slider(0, 6, d["terminal"], step=0.1,
                             label="Terminal growth (%)")
        years = gr.Slider(5, 20, d["horizon"], step=1, label="Forecast years")

        controls = [panel_mode, y1g, y5g, *growth, y1m, y5m, *margins,
                    capex, work_cap, tax, discount, terminal, years]
        groups = (growth_taper_group, growth_year_group,
                  margin_taper_group, margin_year_group)
        return controls, panel_mode, groups

    def view_tabs():
        """The five views of one model. Returns their HTML components in panel order."""
        with gr.Tabs():
            with gr.Tab("Valuation"):
                val = gr.HTML()
            with gr.Tab("Projection"):
                proj = gr.HTML()
                gr.Markdown(
                    "Free cash flow climbs every year, but its **present value** "
                    "peaks mid-forecast and then falls: past that point discounting "
                    "outruns growth. That is why so much of the valuation ends up "
                    "in the terminal value rather than the years you projected."
                )
            with gr.Tab("Valuation Waterfall"):
                fall = gr.HTML()
                gr.Markdown(
                    "Each bar is a contribution to equity value. **Blue adds, red "
                    "subtracts, grey is a running total** &mdash; the same meaning "
                    "those colours carry in the sensitivity grid."
                )
            with gr.Tab("Sensitivity - WACC vs. Terminal Growth"):
                grid_wacc = gr.HTML()
                gr.Markdown(
                    "Each cell revalues the company at that WACC and terminal growth "
                    "rate, holding every other assumption fixed. Blue is worth more "
                    "than the market price, red is worth less."
                )
            with gr.Tab("Sensitivity - Operating Margin vs. Terminal Growth"):
                grid_margin = gr.HTML()
                gr.Markdown(
                    "The same grid against margin instead of discount rate. The column "
                    "axis is the **Year-5 operating margin** &mdash; the level that "
                    "holds flat from Year 5 into perpetuity."
                )
        return [val, proj, fall, grid_wacc, grid_margin]

    # The toggle governs the whole layout, so it sits at page level rather than on top
    # of one column -- and the split it controls lives in the same box, appearing only
    # when the box is checked. No "Probability split" heading: the checkbox's own
    # label and note already say what this is.
    #
    # A plain Column, not a Group: Group paints the secondary grey fill, and Gradio
    # wraps the checkbox in its own bordered `form` inside that, so the two nested.
    # Here the Column carries the only border and the inner form's box is flattened
    # in CSS, which leaves one container holding both controls.
    with gr.Column(elem_classes="mode-box"):
        scenario_mode = gr.Checkbox(
            value=False, label="Scenario analysis",
            info="Split the model into independent bear, base and bull cases",
        )
        with gr.Column(visible=False) as probability_panel:
            gr.Markdown(
                "Two cut points on a 0&ndash;100 axis, so the three probabilities "
                "always sum to 100 by construction.",
                elem_classes="mode-note",
            )
            probability_bar = gr.HTML()
            with gr.Row():
                cut_a = gr.Slider(0, 100, CUT_A_DEFAULT, step=1,
                                  label="Bear / Base boundary")
                cut_b = gr.Slider(0, 100, CUT_B_DEFAULT, step=1,
                                  label="Base / Bull boundary")

    with gr.Row():
        # The column itself is what the toggle hides, not an inner wrapper: with it
        # out of the flex flow its scale=3 sibling becomes the row's only laid-out
        # child and takes the full width.
        #
        # Two assumption panels exist for the base case: this one, authoritative when
        # the mode is off, and the one inside the Base tab, authoritative when it is
        # on. Gradio cannot move a component between containers, so the toggle copies
        # values across once instead -- one direction only, so there is no sync loop.
        with gr.Column(scale=2, visible=True) as assumptions_column:
            all_inputs, global_mode, global_groups = assumption_panel()

        with gr.Column(scale=3):
            # Two sibling Tabs containers rather than one container with tabs shown
            # and hidden individually. Per-tabitem visibility did not take effect in
            # the browser -- the update payload was correct, but the tab bar kept
            # rendering the hidden tabs -- and toggling a whole gr.Tabs is a plain
            # show/hide of one element instead of a tab-bar re-render. It also means
            # no hidden tab can ever be the selected one, which is what left the
            # right-hand pane blank on first load.
            with gr.Tabs(visible=True) as single_model_tabs:
                single_views = []
                for label, tab_id in [
                    ("Valuation", "valuation"),
                    ("Projection", "projection"),
                    ("Valuation Waterfall", "waterfall"),
                    ("Sensitivity - WACC vs. Terminal Growth", "sens_wacc"),
                    ("Sensitivity - Operating Margin vs. Terminal Growth", "sens_margin"),
                ]:
                    with gr.Tab(label, id=tab_id):
                        single_views.append(gr.HTML())
                        if tab_id == "projection":
                            gr.Markdown(
                                "Free cash flow climbs every year, but its **present "
                                "value** peaks mid-forecast and then falls: past that "
                                "point discounting outruns growth."
                            )

            # Scenarios is simply the first tab of its own container, so it leads and
            # opens active without any `selected` juggling.
            with gr.Tabs(visible=False) as scenario_model_tabs:
                with gr.Tab("Scenarios", id="scenarios"):
                    scenario_panel = gr.HTML()

                case_inputs, case_views, case_modes, case_groups = {}, {}, {}, {}
                for case, case_id, defaults in [
                    ("Base", "case_base", None),
                    ("Bear", "case_bear", BEAR_DEFAULTS),
                    ("Bull", "case_bull", BULL_DEFAULTS),
                ]:
                    with gr.Tab(case, id=case_id):
                        with gr.Row():
                            with gr.Column(scale=2):
                                controls, panel_mode, groups = assumption_panel(defaults)
                            with gr.Column(scale=3):
                                views = view_tabs()
                    case_inputs[case] = controls
                    case_views[case] = views
                    case_modes[case] = panel_mode
                    case_groups[case] = groups

    # --- handlers -------------------------------------------------------------

    def settles(components):
        """Trigger when a control settles rather than on every step of a drag.

        A slider's `.change` fires continuously while the handle moves. Each firing
        ships ~62KB of HTML across seven components and re-renders 126 heatmap cells
        and two SVGs, so a drag queues a stream of full round trips and the panels
        crawl or appear to hang. Compute is only ~11ms -- the cost is all payload and
        DOM work, so the fix is to fire once per gesture. `.release` does that for
        sliders; radios and checkboxes have no release event and are cheap anyway.
        """
        return [c.release if isinstance(c, gr.Slider) else c.change
                for c in components]

    # Progress animation is counter-productive here: the work takes milliseconds, and
    # a spinner covering the output on every update is what reads as "queuing".
    QUIET = "hidden"

    def valuate(
        forecast_mode,
        year_1_growth, year_5_growth,
        growth_y1, growth_y2, growth_y3, growth_y4, growth_y5,
        year_1_margin, year_5_margin,
        margin_y1, margin_y2, margin_y3, margin_y4, margin_y5,
        net_capex_pct, working_capital_pct, tax_pct, wacc_pct,
        terminal_growth_pct, forecast_years,
    ):
        return build_valuation(
            mode=forecast_mode,
            growth_taper=(year_1_growth, year_5_growth),
            margin_taper=(year_1_margin, year_5_margin),
            growth_years=[growth_y1, growth_y2, growth_y3, growth_y4, growth_y5],
            margin_years=[margin_y1, margin_y2, margin_y3, margin_y4, margin_y5],
            terminal_growth=terminal_growth_pct,
            tax_rate=tax_pct,
            net_capex_pct=net_capex_pct,
            nwc_pct=working_capital_pct,
            wacc=wacc_pct,
            horizon=forecast_years,
        )

    gr.on(
        triggers=settles(all_inputs) + [demo.load],
        fn=valuate,
        inputs=all_inputs,
        outputs=single_views,
        show_progress=QUIET,
    )

    # The same function, registered once per case. Each case's panel drives only its
    # own views, so moving a bear slider does not recompute the base or bull grids.
    for case in ("Base", "Bear", "Bull"):
        gr.on(
            triggers=settles(case_inputs[case]) + [demo.load],
            fn=valuate,
            inputs=case_inputs[case],
            outputs=case_views[case],
            show_progress=QUIET,
        )

    scenario_all = [cut_a, cut_b, *case_inputs["Base"],
                    *case_inputs["Bear"], *case_inputs["Bull"]]

    def evaluate_scenarios(*values):
        """Two cut points followed by three complete panels, in Base/Bear/Bull order.

        Taken as *values rather than 65 named parameters: the slice boundaries are
        asserted in test_app_wiring.py, which is a sturdier guard than a signature
        that long.
        """
        size = CASE_PANEL_SIZE
        cut_a_pct, cut_b_pct = values[0], values[1]
        base = values[2:2 + size]
        bear = values[2 + size:2 + 2 * size]
        bull = values[2 + 2 * size:2 + 3 * size]
        return build_scenarios(cut_a_pct, cut_b_pct, base, bear, bull)

    gr.on(
        triggers=settles(scenario_all) + [demo.load],
        fn=evaluate_scenarios,
        inputs=scenario_all,
        outputs=[scenario_panel, probability_bar],
        show_progress=QUIET,
    )

    def switch_detail(selected):
        """One radio, four groups: growth and margin each show taper or per-year."""
        taper = gr.update(visible=selected == TAPER)
        per_year = gr.update(visible=selected == PER_YEAR)
        return taper, per_year, taper, per_year

    for panel_mode, groups in [(global_mode, global_groups)] + [
        (case_modes[c], case_groups[c]) for c in ("Base", "Bear", "Bull")
    ]:
        panel_mode.change(fn=switch_detail, inputs=panel_mode, outputs=list(groups))

    # Dragging one cut point past the other pushes it along, the way a segmented bar
    # behaves. probability_split clamps too, so this is presentation only.
    cut_a.release(fn=lambda a, b: gr.update(value=max(a, b)), inputs=[cut_a, cut_b],
                  outputs=cut_b, show_progress=QUIET)
    cut_b.release(fn=lambda a, b: gr.update(value=min(a, b)), inputs=[cut_a, cut_b],
                  outputs=cut_a, show_progress=QUIET)

    mode_toggle_inputs = [scenario_mode, *all_inputs, *case_inputs["Base"]]
    mode_toggle_outputs = (
        [assumptions_column, probability_panel, single_model_tabs, scenario_model_tabs]
        + all_inputs
        + case_inputs["Base"]
    )

    def toggle_scenario_mode(on, *values):
        """Show one layout or the other, and carry the base assumptions across.

        Whichever base panel is becoming authoritative is the source: turning the
        mode on copies the left pane into the Base tab, turning it off copies it
        back. Both panels are written from that one source, so the copy can only
        flow one way and there is no loop.
        """
        size = CASE_PANEL_SIZE
        left_values, base_values = values[:size], values[size:2 * size]
        source = left_values if on else base_values

        return (
            [gr.update(visible=not on), gr.update(visible=on),
             gr.update(visible=not on), gr.update(visible=on)]
            + [gr.update(value=v) for v in source]
            + [gr.update(value=v) for v in source]
        )

    scenario_mode.change(
        fn=toggle_scenario_mode,
        inputs=mode_toggle_inputs,
        outputs=mode_toggle_outputs,
        show_progress=QUIET,
    )

if __name__ == "__main__":
    # Hugging Face Spaces runs this file directly and needs the server bound to all
    # interfaces; locally it stays on loopback so the app is not exposed to the network.
    on_spaces = bool(os.getenv("SPACE_ID"))
    demo.launch(
        server_name="0.0.0.0" if on_spaces else "127.0.0.1",
        server_port=int(os.getenv("PORT", "7860")),
        css=CSS,
    )
