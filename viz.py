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
