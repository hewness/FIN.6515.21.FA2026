"""Interactive DCF valuation app for NVIDIA."""

import gradio as gr

from dcf import NVDA_DEFAULTS, run_dcf, sensitivity_grid
from viz import render_heatmap, render_projection_chart, render_waterfall

# Upside thresholds that separate the three signals.
BUY_ABOVE = 0.15
SELL_BELOW = -0.15

SIGNAL_COLORS = {
    "BUY": ("#16a34a", "rgba(22,163,74,0.12)"),
    "HOLD": ("#d97706", "rgba(217,119,6,0.12)"),
    "SELL": ("#dc2626", "rgba(220,38,38,0.12)"),
}

# Sensitivity axes: WACC 8-14%, terminal growth 1-5%.
WACC_AXIS = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
TERMINAL_AXIS = [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05]

TAPER, PER_YEAR = "Taper Y1 to Y5", "Set each year"

# Per-year defaults are the taper's own schedule, so switching mode at the
# opening settings does not move the valuation.
GROWTH_BY_YEAR = [50.0, 41.25, 32.5, 23.75, 15.0]
MARGIN_BY_YEAR = [62.4, 60.55, 58.7, 56.85, 55.0]

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
           line-height: 1.2; cursor: default;
           background: var(--bg-l); color: var(--ink-l); }
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
  .hm-cell { background: var(--bg-d); color: var(--ink-d); }
  .hm-sw { background: var(--bg-d); }
}
.dark .hm-cell { background: var(--bg-d); color: var(--ink-d); }
.dark .hm-sw { background: var(--bg-d); }
html:not(.dark) .hm-cell { background: var(--bg-l); color: var(--ink-l); }
html:not(.dark) .hm-sw { background: var(--bg-l); }
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

    grid = sensitivity_grid(WACC_AXIS, TERMINAL_AXIS, **shared)
    heat = render_heatmap(grid, WACC_AXIS, TERMINAL_AXIS, NVDA_DEFAULTS["current_price"])

    try:
        r = run_dcf(wacc=wacc / 100, terminal_growth=terminal_growth / 100, **shared)
    except ValueError as exc:
        # Every panel gets the warning -- never a half-drawn chart or table.
        warning = f'<div class="warn"><strong>Cannot value this scenario.</strong><br>{exc}</div>'
        return warning, warning, warning, heat

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
    return (f'<div class="kpi-grid">{kpis}</div>{_projection_table(r)}{bridge}',
            render_projection_chart(r),
            render_waterfall(r),
            heat)


with gr.Blocks(title="NVIDIA DCF Valuation") as demo:
    gr.Markdown("# NVIDIA DCF Valuation")
    gr.Markdown(
        f"Revenue ${NVDA_DEFAULTS['revenue']}B &middot; cash ${NVDA_DEFAULTS['cash']}B &middot; "
        f"debt ${NVDA_DEFAULTS['debt']}B &middot; {NVDA_DEFAULTS['shares']}B shares &middot; "
        f"price ${NVDA_DEFAULTS['current_price']:.2f}. Move a slider to revalue."
    )

    with gr.Row():
        # Sliders sit outside the tabs so one set of assumptions scopes both views.
        with gr.Column(scale=2):
            gr.Markdown("### Forecast detail")
            mode = gr.Radio([TAPER, PER_YEAR], value=TAPER, label="Growth & margin inputs")

            gr.Markdown("### Revenue growth")
            with gr.Group() as growth_taper_group:
                y1_growth = gr.Slider(-20, 100, 50, step=0.25, label="Year 1 revenue growth (%)")
                y5_growth = gr.Slider(-10, 60, 15, step=0.25, label="Year 5 revenue growth (%)")

            with gr.Group(visible=False) as growth_year_group:
                growth_sliders = [
                    gr.Slider(-20, 100, GROWTH_BY_YEAR[i], step=0.25,
                              label=f"Year {i + 1} revenue growth (%)")
                    for i in range(5)
                ]

            gr.Markdown("### Operating margin")
            with gr.Group() as margin_taper_group:
                y1_margin = gr.Slider(0, 90, 62.4, step=0.05, label="Year 1 operating margin (%)")
                y5_margin = gr.Slider(0, 90, 55, step=0.05, label="Year 5 operating margin (%)")

            with gr.Group(visible=False) as margin_year_group:
                margin_sliders = [
                    gr.Slider(0, 90, MARGIN_BY_YEAR[i], step=0.05,
                              label=f"Year {i + 1} operating margin (%)")
                    for i in range(5)
                ]

            gr.Markdown("### Cash flow")
            net_capex = gr.Slider(0, 25, 1.5, step=0.1, label="Net capex (% of revenue)")
            nwc = gr.Slider(0, 50, 10, step=0.5, label="Working capital (% of revenue growth)")
            tax_rate = gr.Slider(0, 40, 15, step=0.5, label="Tax rate (%)")

            gr.Markdown("### Discount rate")
            wacc = gr.Slider(4, 20, 10, step=0.25, label="WACC (%)")
            terminal_growth = gr.Slider(0, 6, 3, step=0.1, label="Terminal growth (%)")
            horizon = gr.Slider(5, 20, 10, step=1, label="Forecast years")

        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("Valuation"):
                    results = gr.HTML()
                with gr.Tab("Projection"):
                    chart = gr.HTML()
                    gr.Markdown(
                        "Free cash flow climbs every year, but its **present value** "
                        "peaks mid-forecast and then falls: past that point discounting "
                        "outruns growth. That is why so much of the valuation ends up "
                        "in the terminal value rather than the years you projected."
                    )
                with gr.Tab("Valuation Waterfall"):
                    waterfall = gr.HTML()
                    gr.Markdown(
                        "Each bar is a contribution to equity value. **Blue adds, red "
                        "subtracts, grey is a running total** &mdash; the same meaning "
                        "those colours carry in the sensitivity grid. Note how far the "
                        "terminal value bar reaches next to every projected year "
                        "combined."
                    )
                with gr.Tab("Sensitivity - WACC vs. Terminal Growth"):
                    heatmap = gr.HTML()
                    gr.Markdown(
                        "Each cell revalues the company at that WACC and terminal growth "
                        "rate, holding every other assumption at your slider settings. "
                        "Blue is worth more than the market price, red is worth less."
                    )

    # Every slider stays wired in regardless of visibility -- hidden components keep
    # their values, and `mode` decides which set the model actually reads.
    #
    # This list's order must match valuate()'s parameter order exactly; Gradio binds
    # them positionally. test_app_wiring.py asserts the two stay in step.
    all_inputs = [mode,
                  y1_growth, y5_growth, *growth_sliders,
                  y1_margin, y5_margin, *margin_sliders,
                  net_capex, nwc, tax_rate, wacc, terminal_growth, horizon]

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
        triggers=[c.change for c in all_inputs] + [demo.load],
        fn=valuate,
        inputs=all_inputs,
        outputs=[results, chart, waterfall, heatmap],
    )

    def switch_mode(selected):
        """One toggle, four groups: growth and margin each show taper or per-year."""
        taper = gr.update(visible=selected == TAPER)
        per_year = gr.update(visible=selected == PER_YEAR)
        return taper, per_year, taper, per_year

    mode.change(
        fn=switch_mode,
        inputs=mode,
        outputs=[growth_taper_group, growth_year_group,
                 margin_taper_group, margin_year_group],
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, css=CSS)
