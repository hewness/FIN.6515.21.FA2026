"""Guards on the projection chart and the valuation waterfall.

A chart is harder to check than a table: it renders, it looks plausible, and it
can still be drawing a shape the engine never produced. So these tests invert the
plotted geometry back into model units and compare. With no browser available,
they also sweep slider combinations for label collisions and off-canvas marks --
the nearest substitute for looking at the thing.
"""

import re

import pytest

from dcf import run_dcf
from viz import (
    _PAD, _H, _W, SERIES, WF_BAR, WF_COLORS, WF_H, WF_PAD, WF_W,
    _nice_ceiling, render_projection_chart, render_waterfall, waterfall_steps,
)


def _polylines(svg):
    """Series key -> list of (x, y) points, in SVG user units."""
    out = {}
    for key, pts in re.findall(r'data-series="(\w+)" points="([^"]+)"', svg):
        out[key] = [tuple(float(n) for n in p.split(",")) for p in pts.split()]
    return out


def _invert_y(y, y_max):
    """Undo the y scale: SVG user units back into $B."""
    plot_h = _H - _PAD["t"] - _PAD["b"]
    return (1 - (y - _PAD["t"]) / plot_h) * y_max


def test_plotted_points_invert_back_to_the_model():
    """The decisive test: the geometry must recover the engine's numbers."""
    r = run_dcf()
    svg = render_projection_chart(r)
    y_max, _ = _nice_ceiling(max(row.revenue for row in r.rows))
    lines = _polylines(svg)

    expected = {
        "revenue": [row.revenue for row in r.rows],
        "fcf": [row.free_cash_flow for row in r.rows],
        "pv": [row.pv_of_fcf for row in r.rows],
    }
    for key, series in expected.items():
        assert len(lines[key]) == len(series)
        recovered = [_invert_y(y, y_max) for _, y in lines[key]]
        # 0.1 user unit of rounding in the SVG is well under $1B at this scale
        assert recovered == pytest.approx(series, abs=1.0)


def test_x_positions_are_evenly_spaced_and_ordered():
    svg = render_projection_chart(run_dcf())
    xs = [x for x, _ in _polylines(svg)["revenue"]]
    assert xs == sorted(xs)
    # Coordinates are emitted to one decimal place, so equal gaps can differ by
    # up to that rounding granularity -- 63.3 against 63.4.
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    assert round(max(gaps) - min(gaps), 6) <= 0.1
    assert xs[0] == pytest.approx(_PAD["l"])
    assert xs[-1] == pytest.approx(_W - _PAD["r"])


@pytest.mark.parametrize("horizon", [5, 10, 20])
def test_point_and_band_counts_track_the_horizon(horizon):
    svg = render_projection_chart(run_dcf(horizon=horizon))
    for spec in SERIES:
        assert len(_polylines(svg)[spec["key"]]) == horizon
    assert svg.count('class="c-band"') == horizon


def test_hover_bands_stay_above_the_24px_hit_target():
    """Even at the longest horizon a band must be comfortably clickable."""
    svg = render_projection_chart(run_dcf(horizon=20))
    widths = [float(w) for w in re.findall(r'class="c-hit"[^>]*width="([\d.]+)"', svg)]
    assert widths and min(widths) >= 24


def test_every_series_carries_a_direct_endpoint_label():
    """Not decorative: light-mode aqua is below 3:1, so labels are the relief."""
    r = run_dcf()
    svg = render_projection_chart(r)
    finals = {
        "Revenue": r.rows[-1].revenue,
        "Free cash flow": r.rows[-1].free_cash_flow,
        "PV of FCF": r.rows[-1].pv_of_fcf,
    }
    for label, value in finals.items():
        assert f"{label} ${value:,.0f}B" in svg


def test_series_colours_are_the_documented_palette_slots():
    """Both themes. Guards a validated palette against a later tidy-up."""
    assert [(s["light"], s["dark"]) for s in SERIES] == [
        ("#2a78d6", "#3987e5"),   # slot 1 blue
        ("#eb6834", "#d95926"),   # slot 2 orange
        ("#1baf7a", "#199e70"),   # slot 3 aqua
    ]
    svg = render_projection_chart(run_dcf())
    for spec in SERIES:
        assert f'--c-l:{spec["light"]};--c-d:{spec["dark"]}' in svg


def test_legend_names_every_series():
    svg = render_projection_chart(run_dcf())
    assert svg.count('class="c-key"') == len(SERIES)
    for spec in SERIES:
        assert spec["label"] in svg


def test_geometry_stays_inside_the_viewbox():
    """Cheap stand-in for eyeballing: nothing plotted off-canvas."""
    for horizon in (5, 10, 20):
        svg = render_projection_chart(run_dcf(horizon=horizon))
        for pts in _polylines(svg).values():
            for x, y in pts:
                assert 0 <= x <= _W
                assert 0 <= y <= _H


def test_pv_line_peaks_before_the_final_year():
    """The reason this chart exists -- discounting overtaking growth."""
    r = run_dcf()
    pv = [row.pv_of_fcf for row in r.rows]
    assert pv.index(max(pv)) < len(pv) - 1
    assert [row.free_cash_flow for row in r.rows] == sorted(
        row.free_cash_flow for row in r.rows
    )


def test_endpoint_labels_never_collide_at_any_setting():
    """Found by sweeping, not by looking -- there are no browser tools here.

    At a short horizon with a low WACC and thin margins the three series converge
    and their endpoint labels landed 0.7px apart: unreadable, and worse than
    cosmetic, since those labels are the accessibility relief for light-mode aqua.
    """
    from viz import LABEL_GAP

    worst = min(
        _label_separation(horizon, wacc, growth, margin)
        for horizon in (5, 8, 10, 15, 20)
        for wacc in (0.05, 0.08, 0.10, 0.14, 0.20)
        for growth in (-0.20, 0.0, 0.25, 0.50, 1.00)
        for margin in (0.05, 0.30, 0.55, 0.85)
    )
    assert worst >= LABEL_GAP - 0.01


def _label_separation(horizon, wacc, growth, margin):
    try:
        r = run_dcf(horizon=horizon, wacc=wacc, year_1_growth=growth, year_5_margin=margin)
    except ValueError:
        return float("inf")
    svg = render_projection_chart(r)
    ys = sorted(float(y) for y in re.findall(r'class="c-end-label"[^>]*y="([\d.-]+)"', svg))
    assert 0 <= min(ys) and max(ys) <= _H          # and never off-canvas
    return min(b - a for a, b in zip(ys, ys[1:]))


def test_decollide_leaves_well_separated_labels_untouched():
    """It must only move what actually collides."""
    from viz import _decollide

    spread = [40.0, 150.0, 280.0]
    assert _decollide(spread, floor_y=20, ceiling_y=302) == spread


def test_nice_ceiling_covers_the_data():
    for value in (757.1, 100.0, 1234.0, 45.6, 0.4):
        ceiling, step = _nice_ceiling(value)
        assert ceiling >= value
        assert step > 0
        assert ceiling % step == pytest.approx(0, abs=1e-6)


# --- valuation waterfall ----------------------------------------------------

THIN = dict(year_1_margin=0.02, year_5_margin=0.02, net_capex_pct=0.20)


def _bars(svg):
    """Step index -> (x, y, width, height) of the rendered bar."""
    found = {}
    for m in re.finditer(
        r'class="wf-bar" data-step="(\d+)" x="([\d.-]+)" y="([\d.-]+)" '
        r'width="([\d.]+)" height="([\d.-]+)"', svg
    ):
        found[int(m.group(1))] = tuple(float(m.group(i)) for i in range(2, 6))
    return found


def _wf_scale(r):
    """Recover the y-scale the renderer used, so bars can be inverted."""
    steps = waterfall_steps(r)
    extremes = [0.0] + [s["start"] for s in steps] + [s["end"] for s in steps]
    hi, lo = max(extremes), min(extremes)
    top = _nice_ceiling(hi)[0] if hi > 0 else 0.0
    bottom = -_nice_ceiling(-lo)[0] if lo < 0 else 0.0
    return bottom, (top - bottom) or 1.0


def _invert_wf(y, bottom, span):
    plot_h = WF_H - WF_PAD["t"] - WF_PAD["b"]
    return (1 - (y - WF_PAD["t"]) / plot_h) * span + bottom


def test_waterfall_steps_chain_into_equity_value():
    """Each floating bar starts where the last ended; anchors sit at zero.

    This is the specific way a waterfall goes wrong while still looking fine:
    bars of plausible height that do not actually add up.
    """
    r = run_dcf()
    steps = waterfall_steps(r)
    assert [s["kind"] for s in steps] == ["delta", "delta", "anchor", "delta", "anchor"]

    assert steps[0]["start"] == 0
    assert steps[1]["start"] == pytest.approx(steps[0]["end"])
    assert steps[1]["end"] == pytest.approx(r.enterprise_value)
    assert steps[2]["start"] == 0                     # enterprise value anchor
    assert steps[3]["start"] == pytest.approx(r.enterprise_value)
    assert steps[3]["end"] == pytest.approx(r.equity_value)
    assert steps[4]["start"] == 0                     # equity value anchor

    for s in steps:
        if s["kind"] == "delta":
            assert s["end"] - s["start"] == pytest.approx(s["amount"])


def test_bar_geometry_inverts_back_to_the_model():
    r = run_dcf()
    svg = render_waterfall(r)
    bottom, span = _wf_scale(r)
    bars = _bars(svg)
    assert len(bars) == 5

    for i, s in enumerate(waterfall_steps(r)):
        _, y, _, h = bars[i]
        high = _invert_wf(y, bottom, span)
        low = _invert_wf(y + h, bottom, span)
        assert max(s["start"], s["end"]) == pytest.approx(high, abs=8)
        assert min(s["start"], s["end"]) == pytest.approx(low, abs=8)


def test_columns_respect_the_24_unit_mark_cap():
    svg = render_waterfall(run_dcf())
    assert {w for _, _, w, _ in _bars(svg).values()} == {WF_BAR}
    assert WF_BAR <= 24


def test_net_debt_bar_flips_label_and_colour_with_its_sign():
    """A bar reading "Net debt" that pushes the total up would be a lie."""
    net_cash = run_dcf()                            # cash 115.5 > debt 8.47
    assert net_cash.net_debt < 0
    step = waterfall_steps(net_cash)[3]
    assert step["label"] == "Net cash"
    assert step["amount"] > 0
    assert "Net cash" in render_waterfall(net_cash)

    leveraged = run_dcf(cash=5.0, debt=90.0)               # now genuinely indebted
    assert leveraged.net_debt > 0
    step = waterfall_steps(leveraged)[3]
    assert step["label"] == "Net debt"
    assert step["amount"] < 0
    svg = render_waterfall(leveraged)
    assert "Net debt" in svg
    assert WF_COLORS["decrease"]["light"] in svg           # and it is red


def test_negative_components_render_below_a_zero_line():
    """Thin margins with heavy capex invert both present values."""
    r = run_dcf(**THIN)
    assert r.pv_of_forecast < 0 and r.pv_of_terminal < 0

    svg = render_waterfall(r)
    assert 'class="wf-zero"' in svg                        # zero line appears
    bottom, span = _wf_scale(r)
    assert bottom < 0                                      # domain covers them

    zero_y = float(re.search(r'class="wf-zero"[^>]*y1="([\d.-]+)"', svg).group(1))
    for i in (0, 1):
        _, y, _, h = _bars(svg)[i]
        assert y + h > zero_y                              # extends below zero


def test_fills_are_the_documented_diverging_poles():
    svg = render_waterfall(run_dcf())
    assert WF_COLORS["increase"]["light"] in svg           # blue adds
    assert WF_COLORS["total"]["light"] in svg              # grey totals
    assert WF_COLORS == {
        "increase": {"light": "#2a78d6", "dark": "#3987e5"},
        "decrease": {"light": "#e34948", "dark": "#e66767"},
        "total": {"light": "#898781", "dark": "#898781"},
    }


def test_every_bar_carries_a_hit_target_over_24px():
    svg = render_waterfall(run_dcf())
    widths = [float(w) for w in re.findall(r'class="wf-hit"[^>]*width="([\d.]+)"', svg)]
    assert len(widths) == 5
    assert min(widths) >= 24


def test_waterfall_geometry_stays_on_canvas():
    """Numeric stand-in for eyeballing, across ordinary and extreme settings."""
    scenarios = [{}, THIN, dict(cash=5.0, debt=90.0), dict(wacc=0.19),
                 dict(horizon=20), dict(year_1_growth=-0.20, year_5_margin=0.05)]
    for kwargs in scenarios:
        svg = render_waterfall(run_dcf(**kwargs))
        for x, y, w, h in _bars(svg).values():
            assert 0 <= x and x + w <= WF_W
            assert 0 <= y and y + h <= WF_H
        for y in re.findall(r'class="wf-value"[^>]*y="([\d.-]+)"', svg):
            assert 0 <= float(y) <= WF_H
