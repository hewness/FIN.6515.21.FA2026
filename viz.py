"""Colour scales and SVG rendering for the app's three visualisations.

Holds the OKLab colour maths, the sensitivity heatmap, the projection chart and
the valuation waterfall. Two of the three encode *polarity* -- above or below a
reference -- so they share one diverging pair and one meaning: blue is worth
more, red is worth less.
"""

# Diverging poles and neutral midpoint, per the reference palette.
POLES = {
    "light": {"under": "#2a78d6", "over": "#e34948", "mid": "#f0efec"},
    "dark": {"under": "#3987e5", "over": "#e66767", "mid": "#383835"},
}
INK = {"light": {"on_light": "#0b0b0b", "on_dark": "#ffffff"},
       "dark": {"on_light": "#0b0b0b", "on_dark": "#ffffff"}}

# Upside cut points, symmetric about zero; ±15% matches the buy/sell thresholds.
BANDS = [-0.50, -0.30, -0.15, -0.05, 0.05, 0.15, 0.30, 0.50]


# --- OKLab conversion (sRGB <-> OKLab), so ramp steps are perceptually even ---

def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_oklab(h: str) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(h))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def oklab_to_hex(lab: tuple[float, float, float]) -> str:
    L, a, bb = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * bb) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * bb) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * bb) ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return _rgb_to_hex(tuple(_linear_to_srgb(c) for c in (r, g, b)))


def diverging_ramp(mode: str = "light", steps_per_arm: int = 4) -> list[str]:
    """Nine colors: over-valued arm (red) -> neutral -> under-valued arm (blue).

    Each arm is interpolated in OKLab from the neutral midpoint to its pole, so
    lightness moves evenly and monotonically outward from the middle.
    """
    p = POLES[mode]
    mid = hex_to_oklab(p["mid"])
    ramp = []
    for pole in ("over", "under"):
        end = hex_to_oklab(p[pole])
        arm = [
            oklab_to_hex(tuple(mid[i] + (end[i] - mid[i]) * (n / steps_per_arm)
                               for i in range(3)))
            for n in range(1, steps_per_arm + 1)
        ]
        ramp = list(reversed(arm)) + ramp if pole == "over" else ramp + arm
    return ramp[:steps_per_arm] + [p["mid"]] + ramp[steps_per_arm:]


def band_index(upside: float) -> int:
    """Which of the 9 buckets an upside figure falls into."""
    idx = 0
    for cut in BANDS:
        if upside >= cut:
            idx += 1
    return idx


def ink_for(bg_hex: str, mode: str) -> str:
    """Pick primary ink that stays legible on this cell."""
    L = hex_to_oklab(bg_hex)[0]
    return INK[mode]["on_dark"] if L < 0.62 else INK[mode]["on_light"]


def render_heatmap(grid, x_values, y_values, current_price,
                   x_label: str = "WACC", y_label: str = "Terminal growth") -> str:
    """Diverging heatmap of intrinsic value per share across two varied inputs.

    Every cell prints its own value, so color is never the only encoding, and
    the grid doubles as the table view. The axes are named by the caller so the
    same component serves more than one pair of assumptions.
    """
    ramps = {m: diverging_ramp(m) for m in ("light", "dark")}

    head = "".join(f"<th>{x:.0%}</th>" for x in x_values)
    body = ""
    for y, row in zip(y_values, grid):
        cells = ""
        for x, res in zip(x_values, row):
            if res is None:
                cells += '<td class="hm-na" title="WACC must exceed terminal growth">–</td>'
                continue
            i = band_index(res.upside)
            bg_l, bg_d = ramps["light"][i], ramps["dark"][i]
            tip = (f"{x_label} {x:.1%} · {y_label.lower()} {y:.1%}&#10;"
                   f"Value ${res.value_per_share:,.2f} vs price ${current_price:,.2f}"
                   f"&#10;{res.upside:+.1%}")
            cells += (
                f'<td class="hm-cell" title="{tip}" style="'
                f"--bg-l:{bg_l};--bg-d:{bg_d};"
                f"--ink-l:{ink_for(bg_l, 'light')};--ink-d:{ink_for(bg_d, 'dark')}\">"
                f'<span class="hm-v">${res.value_per_share:,.0f}</span>'
                f'<span class="hm-u">{res.upside:+.0%}</span></td>'
            )
        body += f'<tr><th class="hm-rh">{y:.1%}</th>{cells}</tr>'

    legend_swatches = ""
    labels = ["≤−50%", "−30%", "−15%", "−5%", "fair", "+5%", "+15%", "+30%", "≥+50%"]
    for i, lab in enumerate(labels):
        legend_swatches += (
            f'<div class="hm-key"><span class="hm-sw" style="'
            f'--bg-l:{ramps["light"][i]};--bg-d:{ramps["dark"][i]}"></span>'
            f'<span class="hm-kl">{lab}</span></div>'
        )

    return f"""
    <div class="hm-wrap">
      <div class="hm-scroll">
        <table class="hm">
          <caption class="hm-cap">Intrinsic value per share · upside vs.
            ${current_price:,.2f} market price</caption>
          <thead><tr><th class="hm-corner">{y_label} ↓ / {x_label} →</th>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      <div class="hm-legend">{legend_swatches}</div>
    </div>
    """


# --- projection chart -------------------------------------------------------
# Categorical slots 1-3 from the reference palette, in fixed order. Validated in
# both themes (worst all-pairs CVD dE 9.2 light / 9.4 dark, clear of the >=8 target).
# Light-mode aqua sits at 2.74:1 against the surface, below the 3:1 bar, so the
# relief rule applies: every line carries a visible direct endpoint label.
SERIES = [
    {"key": "revenue", "label": "Revenue", "light": "#2a78d6", "dark": "#3987e5"},
    {"key": "fcf", "label": "Free cash flow", "light": "#eb6834", "dark": "#d95926"},
    {"key": "pv", "label": "PV of FCF", "light": "#1baf7a", "dark": "#199e70"},
]

# Plot geometry, in SVG user units. The viewBox scales to the container.
_W, _H = 720, 340
_PAD = {"l": 54, "r": 96, "t": 16, "b": 34}


def _nice_ceiling(value: float) -> tuple[float, float]:
    """Round an axis maximum up to a readable step. Returns (maximum, step)."""
    if value <= 0:
        return 1.0, 0.25
    import math

    rough = value / 4                      # aim for about four gridlines
    magnitude = 10 ** math.floor(math.log10(rough))
    for multiple in (1, 2, 2.5, 5, 10):
        step = multiple * magnitude
        if step >= rough:
            break
    return math.ceil(value / step) * step, step


#: Minimum vertical gap between stacked endpoint labels, in SVG user units.
#: The label font is 11px, so anything tighter than this overlaps.
LABEL_GAP = 13.0


def _decollide(ys: list[float], floor_y: float, ceiling_y: float) -> list[float]:
    """Spread label positions so no two sit closer than LABEL_GAP.

    Walks the labels in vertical order pushing each below the previous one, then
    slides the whole run back up if it overshot the plot, and clamps into range.
    Returns positions in the original series order.
    """
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    placed = [ys[i] for i in order]

    # Forward: push each label below its predecessor, keeping it inside the plot.
    for k in range(len(placed)):
        lower_bound = floor_y if k == 0 else placed[k - 1] + LABEL_GAP
        placed[k] = max(placed[k], lower_bound)

    # Backward: pull anything that overshot the bottom back up. Done as a second
    # pass rather than shifting the whole run, so a label that was never crowded
    # is not dragged along by one that was.
    for k in range(len(placed) - 1, -1, -1):
        upper_bound = ceiling_y if k == len(placed) - 1 else placed[k + 1] - LABEL_GAP
        placed[k] = min(placed[k], upper_bound)

    out = [0.0] * len(ys)
    for slot, i in enumerate(order):
        out[i] = placed[slot]
    return out


def render_projection_chart(r) -> str:
    """Three-line forecast chart: revenue, free cash flow, and its present value.

    All three are $B on one shared axis -- same unit, so no second scale is
    needed and the dual-axis trap does not arise.
    """
    values = {
        "revenue": [row.revenue for row in r.rows],
        "fcf": [row.free_cash_flow for row in r.rows],
        "pv": [row.pv_of_fcf for row in r.rows],
    }
    years = [row.year for row in r.rows]
    n = len(years)

    y_max, step = _nice_ceiling(max(values["revenue"]))
    plot_w = _W - _PAD["l"] - _PAD["r"]
    plot_h = _H - _PAD["t"] - _PAD["b"]

    def x_at(i: int) -> float:
        return _PAD["l"] + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def y_at(v: float) -> float:
        return _PAD["t"] + plot_h * (1 - v / y_max)

    # Gridlines and y labels -- hairline, solid, recessive.
    grid, ticks = "", []
    level = 0.0
    while level <= y_max + 1e-9:
        y = y_at(level)
        grid += f'<line class="c-grid" x1="{_PAD["l"]}" y1="{y:.1f}" x2="{_PAD["l"] + plot_w}" y2="{y:.1f}"/>'
        ticks.append(f'<text class="c-tick c-tick-y" x="{_PAD["l"] - 8}" y="{y + 3.5:.1f}">{level:,.0f}</text>')
        level += step

    # X ticks: every year when there is room, otherwise every other one.
    every = 1 if n <= 12 else 2
    for i, year in enumerate(years):
        if i % every == 0 or i == n - 1:
            ticks.append(
                f'<text class="c-tick" x="{x_at(i):.1f}" y="{_PAD["t"] + plot_h + 18}">{year}</text>'
            )

    # Endpoint labels are the relief for light-mode aqua sitting below 3:1 contrast,
    # so they have to stay readable at every setting -- not just the default one.
    # Where the three series converge (a short horizon at a low WACC will stack them
    # within a pixel of each other) push the labels apart to a legible gap. The marker
    # stays on the true value; only the text moves.
    label_y = _decollide(
        [y_at(values[spec["key"]][-1]) for spec in SERIES],
        floor_y=_PAD["t"] + 4,
        ceiling_y=_PAD["t"] + plot_h - 4,
    )

    lines, markers, end_labels = "", "", ""
    for slot, spec in enumerate(SERIES):
        pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(values[spec["key"]]))
        lines += (
            f'<polyline class="c-line" data-series="{spec["key"]}" points="{pts}" '
            f'style="--c-l:{spec["light"]};--c-d:{spec["dark"]}"/>'
        )
        last_x, last_v = x_at(n - 1), values[spec["key"]][-1]
        markers += (
            f'<circle class="c-end" cx="{last_x:.1f}" cy="{y_at(last_v):.1f}" r="4" '
            f'style="--c-l:{spec["light"]};--c-d:{spec["dark"]}"/>'
        )
        end_labels += (
            f'<text class="c-end-label" x="{last_x + 10:.1f}" y="{label_y[slot] + 3.5:.1f}">'
            f'{spec["label"]} ${last_v:,.0f}B</text>'
        )

    # Hover layer: one transparent full-height band per year. Pure CSS -- no script,
    # which Gradio might not execute anyway.
    band_w = plot_w / max(n - 1, 1)
    bands = ""
    for i, year in enumerate(years):
        cx = x_at(i)
        rows_html = "".join(
            f'<tspan class="c-tip-row" x="0" dy="{14 if j else 0}">'
            f'{spec["label"]}  ${values[spec["key"]][i]:,.1f}B</tspan>'
            for j, spec in enumerate(SERIES)
        )
        # Flip the tooltip to the left half-way across, so it never runs off the edge.
        flip = i > n / 2
        tip_x = cx - 132 if flip else cx + 10
        bands += (
            f'<g class="c-band">'
            f'<rect class="c-hit" x="{cx - band_w / 2:.1f}" y="{_PAD["t"]}" '
            f'width="{band_w:.1f}" height="{plot_h:.1f}"/>'
            f'<g class="c-hover">'
            f'<line class="c-cross" x1="{cx:.1f}" y1="{_PAD["t"]}" x2="{cx:.1f}" '
            f'y2="{_PAD["t"] + plot_h:.1f}"/>'
            + "".join(
                f'<circle class="c-dot" cx="{cx:.1f}" cy="{y_at(values[s["key"]][i]):.1f}" r="4" '
                f'style="--c-l:{s["light"]};--c-d:{s["dark"]}"/>'
                for s in SERIES
            )
            + f'<g transform="translate({tip_x:.1f},{_PAD["t"] + 16})">'
            f'<rect class="c-tip-bg" x="-8" y="-14" width="128" height="62" rx="6"/>'
            f'<text class="c-tip"><tspan class="c-tip-year" x="0" dy="0">Year {year}</tspan>'
            f'<tspan x="0" dy="16"> </tspan>{rows_html}</text></g>'
            f'</g></g>'
        )

    legend = "".join(
        f'<span class="c-key"><span class="c-key-line" '
        f'style="--c-l:{s["light"]};--c-d:{s["dark"]}"></span>{s["label"]}</span>'
        for s in SERIES
    )

    return f"""
    <div class="chart-wrap">
      <div class="c-legend">{legend}</div>
      <svg class="chart" viewBox="0 0 {_W} {_H}" role="img"
           aria-label="Revenue, free cash flow and present value of free cash flow by forecast year">
        {grid}
        <line class="c-axis" x1="{_PAD["l"]}" y1="{_PAD["t"] + plot_h}" x2="{_PAD["l"] + plot_w}" y2="{_PAD["t"] + plot_h}"/>
        {"".join(ticks)}
        {lines}{markers}{end_labels}
        {bands}
      </svg>
      <p class="c-note">All figures $B. Hover any year for the full read-out.</p>
    </div>
    """


# --- valuation waterfall ----------------------------------------------------
# Polarity, so the colour job is diverging -- and the poles are the ones the
# heatmap already uses, keeping one meaning across the app: blue adds value, red
# takes it away. Totals sit in a neutral that is deliberately not either pole.
# All three clear 3:1 on both surfaces. Direction of travel and a signed value
# label carry the same information, so colour is never the only channel.
WF_COLORS = {
    "increase": {"light": "#2a78d6", "dark": "#3987e5"},
    "decrease": {"light": "#e34948", "dark": "#e66767"},
    "total": {"light": "#898781", "dark": "#898781"},
}

WF_W, WF_H = 720, 360
WF_PAD = {"l": 62, "r": 20, "t": 22, "b": 54}
WF_BAR = 24.0        # mark spec caps a column here; the band's leftover is air


def waterfall_steps(r) -> list[dict]:
    """The bridge as a list of contributions and running totals.

    Anchored steps (the subtotal and the total) are drawn from zero; the rest
    float, each starting where the previous one ended.
    """
    net_cash = -r.net_debt          # positive when the company holds net cash
    return [
        {"label": "PV of forecast\ncash flows", "amount": r.pv_of_forecast,
         "start": 0.0, "end": r.pv_of_forecast, "kind": "delta"},
        {"label": "PV of terminal\nvalue", "amount": r.pv_of_terminal,
         "start": r.pv_of_forecast, "end": r.enterprise_value, "kind": "delta"},
        {"label": "Enterprise\nvalue", "amount": r.enterprise_value,
         "start": 0.0, "end": r.enterprise_value, "kind": "anchor"},
        # A bar labelled "Net debt" that pushes the total UP would be a lie, so
        # the label follows the sign, matching the equity bridge's wording.
        {"label": "Net cash" if net_cash >= 0 else "Net debt", "amount": net_cash,
         "start": r.enterprise_value, "end": r.equity_value, "kind": "delta"},
        {"label": "Equity\nvalue", "amount": r.equity_value,
         "start": 0.0, "end": r.equity_value, "kind": "anchor"},
    ]


def _wf_fill(step: dict) -> dict:
    if step["kind"] == "anchor":
        return WF_COLORS["total"]
    return WF_COLORS["increase" if step["amount"] >= 0 else "decrease"]


def render_waterfall(r) -> str:
    """Vertical waterfall from discounted cash flows to equity value."""
    steps = waterfall_steps(r)
    n = len(steps)

    # The domain has to cover every bar end, and zero, since components can go
    # negative at thin margins with heavy capex.
    extremes = [0.0] + [s["start"] for s in steps] + [s["end"] for s in steps]
    hi, lo = max(extremes), min(extremes)
    top, step_size = _nice_ceiling(hi) if hi > 0 else (0.0, 1.0)
    bottom = -_nice_ceiling(-lo)[0] if lo < 0 else 0.0
    span = (top - bottom) or 1.0

    plot_w = WF_W - WF_PAD["l"] - WF_PAD["r"]
    plot_h = WF_H - WF_PAD["t"] - WF_PAD["b"]
    band = plot_w / n

    def y_at(v: float) -> float:
        return WF_PAD["t"] + plot_h * (1 - (v - bottom) / span)

    def cx(i: int) -> float:
        return WF_PAD["l"] + band * (i + 0.5)

    # Gridlines across the whole domain, hairline and solid.
    grid, ticks = "", ""
    level = bottom
    while level <= top + 1e-9:
        y = y_at(level)
        grid += f'<line class="wf-grid" x1="{WF_PAD["l"]}" y1="{y:.1f}" x2="{WF_PAD["l"] + plot_w}" y2="{y:.1f}"/>'
        ticks += f'<text class="wf-tick wf-tick-y" x="{WF_PAD["l"] - 8}" y="{y + 3.5:.1f}">{level:,.0f}</text>'
        level += step_size

    bars, labels, connectors, hits = "", "", "", ""
    for i, s in enumerate(steps):
        fill = _wf_fill(s)
        y_top, y_bot = y_at(max(s["start"], s["end"])), y_at(min(s["start"], s["end"]))
        height = max(y_bot - y_top, 1.5)          # keep a sliver visible
        x = cx(i) - WF_BAR / 2
        bars += (
            f'<rect class="wf-bar" data-step="{i}" x="{x:.1f}" y="{y_top:.1f}" '
            f'width="{WF_BAR}" height="{height:.1f}" rx="3" '
            f'style="--c-l:{fill["light"]};--c-d:{fill["dark"]}"/>'
        )

        # Signed for deltas, plain for the anchored subtotal and total.
        shown = (f'{s["amount"]:+,.0f}' if s["kind"] == "delta" else f'{s["amount"]:,.0f}')
        labels += (
            f'<text class="wf-value" x="{cx(i):.1f}" y="{y_top - 7:.1f}">{shown}</text>'
        )
        for line_no, part in enumerate(s["label"].split("\n")):
            labels += (
                f'<text class="wf-cat" x="{cx(i):.1f}" '
                f'y="{WF_PAD["t"] + plot_h + 18 + line_no * 12:.1f}">{part}</text>'
            )

        # Connector from this bar's end to where the next one starts.
        if i < n - 1:
            y_link = y_at(s["end"])
            connectors += (
                f'<line class="wf-link" x1="{cx(i) + WF_BAR / 2:.1f}" y1="{y_link:.1f}" '
                f'x2="{cx(i + 1) - WF_BAR / 2:.1f}" y2="{y_link:.1f}"/>'
            )

        # Hit target spans the band, comfortably wider than the 24-unit bar.
        tip = (f'{s["label"].replace(chr(10), " ")}: ${s["amount"]:,.1f}B'
               f' \u00b7 running total ${s["end"]:,.1f}B')
        hits += (
            f'<g class="wf-hit-g"><rect class="wf-hit" x="{cx(i) - band / 2:.1f}" '
            f'y="{WF_PAD["t"]}" width="{band:.1f}" height="{plot_h:.1f}">'
            f'<title>{tip}</title></rect></g>'
        )

    zero_line = ""
    if bottom < 0:
        zero_line = (f'<line class="wf-zero" x1="{WF_PAD["l"]}" y1="{y_at(0):.1f}" '
                     f'x2="{WF_PAD["l"] + plot_w}" y2="{y_at(0):.1f}"/>')

    per_share = (
        f'Equity value ${r.equity_value:,.0f}B &divide; {r.shares:,.1f}B shares = '
        f'<strong>${r.value_per_share:,.2f}</strong> per share, against a '
        f'${r.current_price:,.2f} market price.'
    )

    return f"""
    <div class="wf-wrap">
      <svg class="wf" viewBox="0 0 {WF_W} {WF_H}" role="img"
           aria-label="Waterfall from discounted cash flows and terminal value to equity value">
        {grid}{zero_line}
        {ticks}
        {connectors}{bars}{labels}
        {hits}
      </svg>
      <p class="wf-note">{per_share}</p>
    </div>
    """


# --- scenario panel ---------------------------------------------------------
# Bear / base / bull is a STATUS scale -- bad, neutral, good -- so it takes the
# red / grey / green reading everyone already has, and it lines up with the buy /
# hold / sell signal colours used elsewhere in the app.
#
# Red against green is the classic colour-vision-deficiency trap, so the steps are
# separated in LIGHTNESS rather than hue alone, which is what CVD preserves. Both
# sets pass the all-pairs gate that way:
#   light  worst pair green<->red  deltaE 8.6 deutan   (>=8 target)
#   dark   worst pair green<->red  deltaE 16.1 deutan
# The neutral sits below 3:1 against its surface in both themes by design -- it is a
# pale block, not a mark -- and every segment carries an inline label, which is the
# documented relief. Colour is never the only channel here.
PROB_COLORS = {
    "Bear": {"light": "#dc2626", "dark": "#e66767"},
    "Base": {"light": "#d8d6cd", "dark": "#52514e"},
    "Bull": {"light": "#15803d", "dark": "#6ee7a0"},
}

# Derived quantities wear the waterfall's total grey, marking them as not an input.
DERIVED_GREY = "#898781"

SP_W, SP_H = 720, 210
SP_PAD = {"l": 86, "r": 20, "t": 18, "b": 38}
SP_BAR = 24.0


def render_probability_bar(shares: tuple[float, float, float],
                           names=("Bear", "Base", "Bull")) -> str:
    """Read-only segmented bar showing how probability is allocated.

    Each segment picks its own ink by lightness, so the label stays legible on a
    deep red, a pale grey and a bright green alike -- a single hard-coded text
    colour cannot work across all three.
    """
    segments = ""
    for name, share in zip(names, shares):
        if share <= 0:
            continue
        colour = PROB_COLORS[name]
        segments += (
            f'<div class="sp-seg" style="flex:{share:.6f};'
            f'--c-l:{colour["light"]};--c-d:{colour["dark"]};'
            f'--ink-l:{ink_for(colour["light"], "light")};'
            f'--ink-d:{ink_for(colour["dark"], "dark")}"'
            f' title="{name} {share:.0%}">'
            f'<span class="sp-seg-l">{name} {share:.0%}</span></div>'
        )
    return f'<div class="sp-bar">{segments}</div>'


def render_scenario_panel(wv) -> str:
    """Diverging bars from the market price, one per case plus the weighted average.

    Each case's job is its distance from the market price, which is the diverging
    case -- so this reuses the same poles as the heatmap and the waterfall: blue is
    worth more than the price, red is worth less.
    """
    rows = [(s.name, s.result.value_per_share if s.result else None, s.weight, s.error)
            for s in wv.scenarios]
    rows.append(("Weighted", wv.weighted_value, None, None))

    price = wv.current_price
    values = [v for _, v, _, _ in rows if v is not None] + [price, 0.0]
    top, _ = _nice_ceiling(max(values))
    plot_w = SP_W - SP_PAD["l"] - SP_PAD["r"]
    plot_h = SP_H - SP_PAD["t"] - SP_PAD["b"]
    band = plot_h / len(rows)

    def x_at(v: float) -> float:
        return SP_PAD["l"] + plot_w * (v / top)

    price_x = x_at(price)
    grid = ""
    for level in (0, price, top):
        grid += (f'<line class="sp-grid" x1="{x_at(level):.1f}" y1="{SP_PAD["t"]}" '
                 f'x2="{x_at(level):.1f}" y2="{SP_PAD["t"] + plot_h:.1f}"/>')

    bars, labels = "", ""
    for i, (name, value, weight, error) in enumerate(rows):
        cy = SP_PAD["t"] + band * (i + 0.5)
        labels += (f'<text class="sp-name" x="{SP_PAD["l"] - 10}" '
                   f'y="{cy + 3.5:.1f}">{name}</text>')

        if value is None:
            labels += (f'<text class="sp-na" x="{price_x + 8:.1f}" y="{cy + 3.5:.1f}">'
                       f'cannot be valued</text>')
            continue

        x = x_at(value)
        left, right = min(price_x, x), max(price_x, x)
        if name == "Weighted":
            fill_l = fill_d = DERIVED_GREY
        elif value >= price:
            fill_l, fill_d = POLES["light"]["under"], POLES["dark"]["under"]
        else:
            fill_l, fill_d = POLES["light"]["over"], POLES["dark"]["over"]

        bars += (
            f'<rect class="sp-bar-r" data-case="{name}" x="{left:.1f}" '
            f'y="{cy - SP_BAR / 2:.1f}" width="{max(right - left, 1.5):.1f}" '
            f'height="{SP_BAR}" rx="3" style="--c-l:{fill_l};--c-d:{fill_d}">'
            f'<title>{name}: ${value:,.2f} ({value / price - 1:+.1%} vs price)</title>'
            f'</rect>'
        )
        suffix = f'  ({weight:.0%})' if weight is not None else ""
        labels += (f'<text class="sp-val" x="{right + 8:.1f}" y="{cy + 3.5:.1f}">'
                   f'${value:,.0f}{suffix}</text>')

    return f"""
    <div class="sp-wrap">
      <svg class="sp" viewBox="0 0 {SP_W} {SP_H}" role="img"
           aria-label="Intrinsic value by scenario against the market price">
        {grid}{bars}{labels}
        <text class="sp-tick" x="{price_x:.1f}" y="{SP_PAD["t"] + plot_h + 16:.1f}">
          price ${price:,.0f}</text>
        <text class="sp-tick" x="{SP_PAD["l"]:.1f}" y="{SP_PAD["t"] + plot_h + 16:.1f}">0</text>
      </svg>
    </div>
    """


# --- recommendation & break-even --------------------------------------------
# The dumbbell is one hue, not the usual "1 hue, 2 shades": the light step
# (#86b6ef) reaches only 2.11:1 on white, so the before/after distinction is
# carried by hollow-vs-filled instead. Rings in the surface colour are already
# this app's mark vocabulary.
DUMBBELL = {"light": "#2a78d6", "dark": "#3987e5"}     # 4.42 / 5.26 contrast

# Reserved status palette. These always ship with an icon AND a label -- light-mode
# warning is 1.83:1 by design, and the pairing is the documented mitigation.
VERDICT_STYLE = {
    "impossible": ("#d03b3b", "&#10007;", "impossible"),
    "demanding": ("#fab219", "&#9888;", "demanding"),
    "defensible": ("#0ca30c", "&#10003;", "defensible"),
}
CONVICTION_NOTE = {
    "high": "every weighted case falls on one side of the price",
    "moderate": "the weighted range spans the price",
    "low": "the central estimate and the probability mass disagree",
}

BE_W, BE_ROW = 720, 40
BE_PAD = {"l": 188, "r": 150}


def render_recommendation(rec, price: float) -> str:
    """Verdict, conviction, and the range it rests on -- rounded, not precise.

    The headline rounds to the nearest $10 on purpose: a scenario range two
    hundred dollars wide does not support cents.
    """
    colour = {"BUY": "#16a34a", "HOLD": "#d97706", "SELL": "#dc2626"}[rec.verdict]
    warn = ""
    if rec.disagreement:
        warn = f'<p class="rec-warn">&#9888; {rec.disagreement}</p>'
    return f"""
    <div class="rec" style="--rec:{colour}">
      <div class="rec-label">Recommendation</div>
      <div class="rec-verdict">{rec.verdict}
        <span class="rec-conv">&middot; {rec.conviction} conviction</span></div>
      <div class="rec-range">Value range
        <strong>${round(rec.range_lo, -1):,.0f} &ndash; ${round(rec.range_hi, -1):,.0f}</strong>
        against a ${price:,.0f} market price</div>
      <div class="rec-mass">{rec.mass_below:.0%} of your probability sits below the price
        &middot; <span class="rec-why">{CONVICTION_NOTE[rec.conviction]}</span></div>
      {warn}
    </div>
    """


def render_break_even(rows, price: float) -> str:
    """Dumbbell per driver: your assumption against what the price requires.

    Each row is scaled to its own bracket. The drivers are in different units, so
    a shared axis would invite a comparison that does not mean anything.
    """
    height = BE_ROW * len(rows) + 16
    track_w = BE_W - BE_PAD["l"] - BE_PAD["r"]
    marks, text = "", ""

    for i, r in enumerate(rows):
        cy = 14 + BE_ROW * i
        colour, icon, word = VERDICT_STYLE[r.verdict]
        text += (f'<text class="be-label" x="{BE_PAD["l"] - 12}" y="{cy + 4:.1f}">'
                 f'{r.label}</text>')
        marks += (f'<line class="be-track" x1="{BE_PAD["l"]}" y1="{cy:.1f}" '
                  f'x2="{BE_PAD["l"] + track_w}" y2="{cy:.1f}"/>')

        def at(value: float) -> float:
            span = (r.range_hi - r.range_lo) or 1.0
            frac = min(max((value - r.range_lo) / span, 0.0), 1.0)
            return BE_PAD["l"] + track_w * frac

        if r.required is None:
            text += (f'<text class="be-na" x="{BE_PAD["l"] + 4}" y="{cy + 4:.1f}">'
                     f'unreachable on this driver alone</text>')
        else:
            x_base, x_req = at(r.base), at(r.required)
            marks += (f'<line class="be-join" x1="{x_base:.1f}" y1="{cy:.1f}" '
                      f'x2="{x_req:.1f}" y2="{cy:.1f}"/>')
            # hollow = your assumption, filled = what the price demands
            marks += (f'<circle class="be-yours" cx="{x_base:.1f}" cy="{cy:.1f}" r="5">'
                      f'<title>your assumption: {r.base:.1%}</title></circle>')
            marks += (f'<circle class="be-req" data-driver="{r.key}" cx="{x_req:.1f}" '
                      f'cy="{cy:.1f}" r="5"><title>required: {r.required:.1%}</title></circle>')
            text += (f'<text class="be-num" x="{BE_PAD["l"] + track_w + 10}" '
                     f'y="{cy + 4:.1f}">{r.base:.1%} &#8594; {r.required:.1%}</text>')

        text += (f'<text class="be-verdict" style="fill:{colour}" '
                 f'x="{BE_PAD["l"] - 12}" y="{cy + 17:.1f}">{icon} {word}</text>')
        text += (f'<text class="be-reason" x="{BE_PAD["l"] + 4}" y="{cy + 17:.1f}">'
                 f'{r.reason}</text>')

    closed = sum(1 for r in rows if r.verdict != "defensible")
    ok = [r.label for r in rows if r.verdict == "defensible"]
    tail = (f"Defensible: {', '.join(ok)} &mdash; that is where the research effort belongs."
            if ok else "None of them is defensible on its own.")
    summary = (
        f"<strong>{closed} of the {len(rows)}</strong> single-driver routes to "
        f"${price:,.0f} are impossible or demanding. {tail}"
    )
    return f"""
    <div class="be-wrap">
      <div class="be-cap">What ${price:,.0f} requires &mdash; each driver alone,
        everything else at your base case</div>
      <svg class="be" viewBox="0 0 {BE_W} {height}" role="img"
           aria-label="Required value of each driver to justify the market price">
        {marks}{text}
      </svg>
      <p class="be-summary">{summary}</p>
    </div>
    """


def render_warnings(warnings) -> str:
    """Amber notice for conditions the model valued through but a reader should know.

    Deliberately the same treatment as the recommendation's mean-versus-mass notice:
    the app already has one way of saying "this computed, but be careful", and a
    second visual language would just be noise. Returns an empty string when there is
    nothing to say, so a clean scenario shows no chrome at all.
    """
    if not warnings:
        return ""
    items = "".join(
        f'<li data-code="{w.code}">{w.message}</li>' for w in warnings
    )
    plural = "" if len(warnings) == 1 else "s"
    return (
        f'<div class="model-warn">'
        f'<div class="model-warn-head">&#9888; {len(warnings)} thing{plural} worth '
        f'knowing about this valuation</div>'
        f'<ul>{items}</ul></div>'
    )
