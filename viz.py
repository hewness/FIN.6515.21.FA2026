"""Color and HTML rendering for the sensitivity heatmap.

The heatmap's job is *polarity* -- is this scenario's intrinsic value above or
below the market price -- so it uses a diverging scale: two hues with a neutral
gray midpoint at fair value, equal steps per arm.
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


def render_heatmap(grid, wacc_values, terminal_values, current_price) -> str:
    """Diverging heatmap of intrinsic value per share.

    Every cell prints its own value, so color is never the only encoding, and
    the grid doubles as the table view.
    """
    ramps = {m: diverging_ramp(m) for m in ("light", "dark")}

    head = "".join(f"<th>{w:.0%}</th>" for w in wacc_values)
    body = ""
    for g, row in zip(terminal_values, grid):
        cells = ""
        for w, res in zip(wacc_values, row):
            if res is None:
                cells += '<td class="hm-na" title="WACC must exceed terminal growth">–</td>'
                continue
            i = band_index(res.upside)
            bg_l, bg_d = ramps["light"][i], ramps["dark"][i]
            tip = (f"WACC {w:.1%} · terminal growth {g:.1%}&#10;"
                   f"Value ${res.value_per_share:,.2f} vs price ${current_price:,.2f}"
                   f"&#10;{res.upside:+.1%}")
            cells += (
                f'<td class="hm-cell" title="{tip}" style="'
                f"--bg-l:{bg_l};--bg-d:{bg_d};"
                f"--ink-l:{ink_for(bg_l, 'light')};--ink-d:{ink_for(bg_d, 'dark')}\">"
                f'<span class="hm-v">${res.value_per_share:,.0f}</span>'
                f'<span class="hm-u">{res.upside:+.0%}</span></td>'
            )
        body += f'<tr><th class="hm-rh">{g:.1%}</th>{cells}</tr>'

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
          <thead><tr><th class="hm-corner">Terminal ↓ / WACC →</th>{head}</tr></thead>
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
