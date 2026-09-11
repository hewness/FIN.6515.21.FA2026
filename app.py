"""Interactive DCF valuation app for NVIDIA."""

import gradio as gr

from dcf import NVDA_DEFAULTS, run_dcf, sensitivity_grid
from viz import render_heatmap

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
.warn { border: 1px solid #dc2626; background: rgba(220,38,38,0.08);
        border-radius: 10px; padding: 16px; }

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


def valuate(
    year_1_growth, year_5_growth, gross_margin, opex_pct,
    tax_rate, wacc, terminal_growth, horizon,
):
    """Slider values arrive as percentages; the model wants decimals.

    Returns the valuation panel and the sensitivity heatmap, so both views stay
    in sync with one set of assumptions.
    """
    shared = dict(
        year_1_growth=year_1_growth / 100,
        year_5_growth=year_5_growth / 100,
        gross_margin=gross_margin / 100,
        opex_pct=opex_pct / 100,
        tax_rate=tax_rate / 100,
        horizon=int(horizon),
    )

    grid = sensitivity_grid(WACC_AXIS, TERMINAL_AXIS, **shared)
    heat = render_heatmap(grid, WACC_AXIS, TERMINAL_AXIS, NVDA_DEFAULTS["current_price"])

    try:
        r = run_dcf(wacc=wacc / 100, terminal_growth=terminal_growth / 100, **shared)
    except ValueError as exc:
        return (
            f'<div class="warn"><strong>Cannot value this scenario.</strong><br>{exc}</div>',
            heat,
        )

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
      <tr><td>PV of forecast cash flows ({len(r.rows)} yrs)</td><td>${r.pv_of_forecast:,.0f}B</td></tr>
      <tr><td>PV of terminal value</td><td>${r.pv_of_terminal:,.0f}B</td></tr>
      <tr><td>Enterprise value</td><td>${r.enterprise_value:,.0f}B</td></tr>
      <tr><td>+ Cash</td><td>${r.cash:,.1f}B</td></tr>
      <tr><td>&minus; Debt</td><td>${r.debt:,.1f}B</td></tr>
      <tr><td>Equity value</td><td>${r.equity_value:,.0f}B</td></tr>
      <tr><td>&divide; Shares outstanding</td><td>{r.shares:,.1f}B</td></tr>
      <tr class="total"><td>Intrinsic value per share</td><td>${r.value_per_share:,.2f}</td></tr>
    </table>
    """
    return f'<div class="kpi-grid">{kpis}</div>{bridge}', heat


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
            gr.Markdown("### Growth")
            year_1_growth = gr.Slider(-20, 100, 50, step=1, label="Year 1 revenue growth (%)")
            year_5_growth = gr.Slider(-10, 60, 15, step=0.5, label="Year 5 revenue growth (%)")
            terminal_growth = gr.Slider(0, 6, 3, step=0.1, label="Terminal growth (%)")
            horizon = gr.Slider(5, 20, 10, step=1, label="Forecast years")

            gr.Markdown("### Profitability")
            gross_margin = gr.Slider(0, 100, 75, step=0.5, label="Gross margin (%)")
            opex_pct = gr.Slider(0, 60, 25, step=0.5, label="Operating expenses (% of revenue)")
            tax_rate = gr.Slider(0, 40, 15, step=0.5, label="Tax rate (%)")

            gr.Markdown("### Discount rate")
            wacc = gr.Slider(4, 20, 10, step=0.25, label="WACC (%)")

        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("Valuation"):
                    results = gr.HTML()
                with gr.Tab("Sensitivity"):
                    heatmap = gr.HTML()
                    gr.Markdown(
                        "Each cell revalues the company at that WACC and terminal growth "
                        "rate, holding every other assumption at your slider settings. "
                        "Blue is worth more than the market price, red is worth less."
                    )

    inputs = [year_1_growth, year_5_growth, gross_margin, opex_pct,
              tax_rate, wacc, terminal_growth, horizon]

    gr.on(
        triggers=[s.change for s in inputs] + [demo.load],
        fn=valuate,
        inputs=inputs,
        outputs=[results, heatmap],
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, css=CSS)
