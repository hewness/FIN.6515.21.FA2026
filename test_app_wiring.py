"""Guards on the Gradio wiring.

`gr.on` binds `all_inputs` to `valuate()` positionally, so a slider added or moved
in one place and not the other misassigns values silently -- the app would still
run and still produce a plausible number, just the wrong one. These tests make
that failure loud.
"""

import inspect
import pathlib
import re

import pytest

import app


def test_every_input_has_a_parameter():
    params = list(inspect.signature(app.valuate).parameters)
    assert len(params) == len(app.all_inputs), (
        f"valuate() takes {len(params)} parameters but {len(app.all_inputs)} "
        "components are wired to it"
    )


def test_inputs_are_bound_in_the_order_valuate_expects():
    """Each component's label must match the parameter it lands on."""
    expected = [
        "Growth & margin inputs",
        # growth block: taper pair, then the five per-year sliders
        "Year 1 revenue growth (%)", "Year 5 revenue growth (%)",
        *[f"Year {i} revenue growth (%)" for i in range(1, 6)],
        # margin block, same shape
        "Year 1 operating margin (%)", "Year 5 operating margin (%)",
        *[f"Year {i} operating margin (%)" for i in range(1, 6)],
        "Net capex (% of revenue)",
        "Working capital (% of revenue growth)",
        "Tax rate (%)",
        "WACC (%)",
        "Terminal growth (%)",
        "Forecast years",
    ]
    assert [c.label for c in app.all_inputs] == expected


def test_per_year_defaults_reproduce_the_taper():
    """Switching mode at the opening settings must not move the valuation.

    The per-year sliders open on the taper's own schedule, so the two modes are
    the same forecast expressed two ways.
    """
    from dcf import growth_schedule, margin_schedule

    for name, d in (("Base", app.BASE_DEFAULTS), ("Bear", app.BEAR_DEFAULTS),
                    ("Bull", app.BULL_DEFAULTS)):
        growth, margins = app.per_year_defaults(d)
        assert growth == growth_schedule(d["y1_growth"], d["y5_growth"],
                                         d["terminal"], horizon=10)[:5], name
        assert margins == margin_schedule(d["y1_margin"], d["y5_margin"],
                                          horizon=10)[:5], name
        # Every per-year value must land exactly on its slider's step, or the
        # slider rounds it and the two modes stop agreeing on the screen even
        # though they agree in the model. This is what forced the Base case's
        # Year-5 growth to 0.25% rather than 0.00%.
        assert all(abs(round(v / 0.25) * 0.25 - v) < 1e-9 for v in growth), name
        assert all(abs(round(v / 0.05) * 0.05 - v) < 1e-9 for v in margins), name

    assert (app.GROWTH_BY_YEAR, app.MARGIN_BY_YEAR) == app.per_year_defaults(
        app.BASE_DEFAULTS)


def test_valuate_feeds_every_panel():
    defaults = [c.value for c in app.all_inputs]
    panels = app.valuate(*defaults)
    assert len(panels) == 6
    valuation, chart, waterfall, heat, margin_heat, growth_heat = panels
    assert "<table class=\"proj\"" in valuation
    assert 'class="chart"' in chart
    assert 'class="wf"' in waterfall
    assert all("hm-cell" in g for g in (heat, margin_heat, growth_heat))
    # the three grids must name different axis pairs
    assert "WACC &rarr;" in heat or "WACC →" in heat
    assert "Year 5 operating margin" in margin_heat
    assert "Year 1 revenue growth" in growth_heat
    assert "Terminal growth" in heat and "Terminal growth" in margin_heat
    # ... and the growth grid varies WACC instead of terminal growth
    assert "Terminal growth" not in growth_heat


def test_both_modes_render_the_same_panels_at_defaults():
    defaults = [c.value for c in app.all_inputs]
    taper = app.valuate(*defaults)

    per_year = list(defaults)
    per_year[0] = app.PER_YEAR
    py = app.valuate(*per_year)

    assert taper == py          # valuation, chart and heatmap all identical


def test_signal_thresholds():
    assert app.signal_for(0.30) == "BUY"
    assert app.signal_for(0.0) == "HOLD"
    assert app.signal_for(-0.40) == "SELL"


# --- the projection table must report the engine, not re-derive it ---



def _panel(**overrides):
    """Render the valuation panel at defaults, with optional slider overrides."""
    values = [c.value for c in app.all_inputs]
    labels = [c.label for c in app.all_inputs]
    for label, value in overrides.items():
        values[labels.index(label)] = value
    return app.valuate(*values)[0]


def _body_rows(panel):
    body = re.search(r"<tbody>(.*?)</tbody>", panel, re.S).group(1)
    return re.findall(r"<tr>(.*?)</tr>", body, re.S)


def test_one_row_per_forecast_year():
    assert len(_body_rows(_panel())) == 10
    assert len(_body_rows(_panel(**{"Forecast years": 20}))) == 20
    assert len(_body_rows(_panel(**{"Forecast years": 5}))) == 5


def test_rendered_figures_match_the_model():
    """Parse the table back out of the HTML and reconcile against run_dcf().

    A table showing numbers the engine never produced would pass every other
    test in this file -- it renders, it has the right row count, the app runs.
    Only comparing the printed cells against the model catches it.
    """
    from dcf import run_dcf

    r = run_dcf()
    rendered = _body_rows(_panel())
    assert len(rendered) == len(r.rows)

    for row, html in zip(r.rows, rendered):
        # Compare against the model value formatted, so the check is exact rather
        # than a tolerance that could mask a column landing in the wrong place.
        assert re.findall(r"<td>(.*?)</td>", html) == [
            str(row.year),
            f"{row.growth_rate:+.1%}",
            f"${row.revenue:,.1f}",
            f"{row.operating_margin:.1%}",
            f"${row.operating_income:,.1f}",
            f"${row.nopat:,.1f}",
            f"${row.free_cash_flow:,.1f}",
            f"{row.discount_factor:.3f}",
            f"${row.pv_of_fcf:,.1f}",
        ]


def test_terminal_and_net_debt_rows_are_present():
    panel = _panel()
    assert "Terminal value (Gordon Growth)" in panel
    assert "Gordon Growth:</strong> terminal value" in panel
    assert "Net debt" in panel
    # NVIDIA holds net cash, so the bridge shows it parenthesised
    from dcf import NVDA_DEFAULTS
    net_cash = NVDA_DEFAULTS["cash"] - NVDA_DEFAULTS["debt"]
    assert f"(${net_cash:,.1f}B)" in panel


def test_guardrail_warns_in_every_panel_rather_than_half_drawing():
    bad = {"WACC (%)": 4.0, "Terminal growth (%)": 5.0}
    values = [c.value for c in app.all_inputs]
    labels = [c.label for c in app.all_inputs]
    for label, value in bad.items():
        values[labels.index(label)] = value
    valuation, chart, waterfall, *grids = app.valuate(*values)

    assert "Cannot value this scenario" in valuation
    assert "<tbody>" not in valuation          # no half-built table
    assert "Cannot value this scenario" in chart
    assert "<svg" not in chart                 # no half-drawn chart
    assert "Cannot value this scenario" in waterfall
    assert "<svg" not in waterfall             # no half-drawn waterfall

    # The sensitivity grids deliberately do NOT warn: each cell is its own
    # scenario, so the grid stays useful when the centre point is unvaluable.
    # Unreachable cells render as a dash instead.
    wacc_grid, margin_grid, growth_grid = grids
    for grid in grids:
        assert "Cannot value this scenario" not in grid
        assert "hm-cell" in grid
    # WACC 4% against terminal growth 1-5% makes the upper rows impossible
    assert "hm-na" in margin_grid
    # but the WACC grid varies WACC 8-14%, all of which clear 5% terminal growth
    assert "hm-na" not in wacc_grid
    # the growth grid varies WACC too, so its columns clear 5% terminal growth as well
    assert "hm-na" not in growth_grid




# --- scenario analysis mode -------------------------------------------------
# Four assumption panels now exist (left pane, Base, Bear, Bull) and two handlers
# bind positionally. Offsets are computed from the panel size rather than looked up
# by label, because every panel deliberately reuses the same labels.

SIZE = app.CASE_PANEL_SIZE
CUT_A, CUT_B = 0, 1
BASE_0, BEAR_0, BULL_0 = 2, 2 + SIZE, 2 + 2 * SIZE
# field offsets inside one panel
MODE, Y1G, Y5G = 0, 1, 2
Y1M, Y5M = 8, 9
CAPEX, NWC, TAX, WACC, TERMINAL, HORIZON = 15, 16, 17, 18, 19, 20

PANEL_LABELS = [
    "Growth & margin inputs",
    "Year 1 revenue growth (%)", "Year 5 revenue growth (%)",
    *[f"Year {i} revenue growth (%)" for i in range(1, 6)],
    "Year 1 operating margin (%)", "Year 5 operating margin (%)",
    *[f"Year {i} operating margin (%)" for i in range(1, 6)],
    "Net capex (% of revenue)",
    "Working capital (% of revenue growth)",
    "Tax rate (%)",
    "WACC (%)",
    "Terminal growth (%)",
    "Forecast years",
]


def test_every_panel_is_built_from_the_same_definition():
    """Left pane and all three cases must expose identical controls in one order.

    They are produced by one helper, and this is what keeps a future edit to one
    panel from silently diverging the others.
    """
    assert [c.label for c in app.all_inputs] == PANEL_LABELS
    for case in ("Base", "Bear", "Bull"):
        assert [c.label for c in app.case_inputs[case]] == PANEL_LABELS
        assert len(app.case_inputs[case]) == SIZE


def test_case_panels_open_on_their_own_defaults():
    """Bear and Bull are deviations; Base opens where the left pane does."""
    base = app.case_inputs["Base"]
    bear = app.case_inputs["Bear"]
    bull = app.case_inputs["Bull"]
    assert (base[Y1G].value == app.all_inputs[Y1G].value
            == app.BASE_DEFAULTS["y1_growth"])
    assert bear[Y1G].value == app.BEAR_DEFAULTS["y1_growth"]
    assert bull[Y1G].value == app.BULL_DEFAULTS["y1_growth"]
    assert bear[WACC].value == app.BEAR_DEFAULTS["wacc"]
    assert bull[TERMINAL].value == app.BULL_DEFAULTS["terminal"]


def test_scenario_handler_wiring():
    assert len(app.scenario_all) == 2 + 3 * SIZE == 65
    assert app.scenario_all[CUT_A].label == "Bear / Base boundary"
    assert app.scenario_all[CUT_B].label == "Base / Bull boundary"
    # the slices evaluate_scenarios takes must land on the right panels
    assert app.scenario_all[BASE_0:BASE_0 + SIZE] == app.case_inputs["Base"]
    assert app.scenario_all[BEAR_0:BEAR_0 + SIZE] == app.case_inputs["Bear"]
    assert app.scenario_all[BULL_0:BULL_0 + SIZE] == app.case_inputs["Bull"]


def test_valuate_signature_matches_one_panel():
    """The same handler serves the left pane and all three cases."""
    params = list(inspect.signature(app.valuate).parameters)
    assert len(params) == SIZE == len(app.all_inputs)


def _scenario(overrides=None):
    values = [c.value for c in app.scenario_all]
    for index, value in (overrides or {}).items():
        values[index] = value
    return app.evaluate_scenarios(*values)


def test_scenario_panel_reports_all_cases_and_the_recommendation():
    panel, bar = _scenario()
    for name in ("Bear", "Base", "Bull", "Weighted"):
        assert name in panel
    assert "Probability-weighted value" in panel
    assert 'class="rec-verdict"' in panel              # the recommendation block
    from dcf import NVDA_DEFAULTS
    assert f"What ${NVDA_DEFAULTS['current_price']:.0f} requires" in panel
    assert 'class="sp-bar"' in bar                     # the bar renders separately now


def test_scenario_panel_agrees_with_the_model():
    from dcf import probability_split, weighted_valuation_from_cases

    values = [c.value for c in app.scenario_all]
    cases = {
        name: app.assumptions_from_panel(values[start:start + SIZE])
        for name, start in (("Base", BASE_0), ("Bear", BEAR_0), ("Bull", BULL_0))
    }
    p_bear, p_base, p_bull = probability_split(values[CUT_A], values[CUT_B])
    wv = weighted_valuation_from_cases([
        ("Bear", p_bear, cases["Bear"]),
        ("Base", p_base, cases["Base"]),
        ("Bull", p_bull, cases["Bull"]),
    ])
    panel, _ = _scenario()
    assert f"${wv.weighted_value:,.2f}" in panel
    for s in wv.scenarios:
        assert f"${s.result.value_per_share:,.2f}" in panel


def test_cases_are_genuinely_independent():
    """A bear-only change must move the bear case and nothing else."""
    from dcf import run_dcf

    values = [c.value for c in app.scenario_all]
    bear = app.assumptions_from_panel(values[BEAR_0:BEAR_0 + SIZE])
    base = app.assumptions_from_panel(values[BASE_0:BASE_0 + SIZE])

    values_to = list(values)
    values_to[BEAR_0 + HORIZON] = 7.0
    bear_short = app.assumptions_from_panel(values_to[BEAR_0:BEAR_0 + SIZE])
    base_after = app.assumptions_from_panel(values_to[BASE_0:BASE_0 + SIZE])

    assert len(run_dcf(**bear).rows) == 10          # the default horizon
    assert len(run_dcf(**bear_short).rows) == 7     # bear alone now runs 7 years
    assert base_after == base                       # base untouched

    before, _ = _scenario()
    after, _ = _scenario({BEAR_0 + HORIZON: 7.0})
    assert before != after                          # the weighted result moves


def test_scenario_panel_flags_partial_probability_mass():
    panel, _ = _scenario({BEAR_0 + WACC: 4.0, BEAR_0 + TERMINAL: 5.0})
    assert "cannot be valued" in panel
    assert "of probability mass" in panel
    assert "2 of 3 cases" in panel


def test_scenario_panel_warns_when_no_case_can_be_valued():
    panel, _ = _scenario({
        BASE_0 + WACC: 4.0, BASE_0 + TERMINAL: 5.0,
        BEAR_0 + WACC: 4.0, BEAR_0 + TERMINAL: 5.0,
        BULL_0 + WACC: 4.0, BULL_0 + TERMINAL: 5.0,
    })
    assert "No scenario can be valued" in panel


def test_probability_split_drives_the_rendered_bar():
    _, bar = _scenario({CUT_A: 33.0, CUT_B: 67.0})
    assert "Bear 33%" in bar and "Bull 33%" in bar
    _, all_bull = _scenario({CUT_A: 0.0, CUT_B: 0.0})
    assert "Bull 100%" in all_bull


# --- the mode toggle ---------------------------------------------------------
# Two sibling gr.Tabs containers are toggled, not nine individual tabs. Per-tabitem
# visibility produced a correct update payload that the browser ignored -- the hidden
# tabs stayed on the tab bar -- so the containers are the unit of visibility now.

CONTAINERS = 4              # global panel, probability panel, and the two Tabs


def _toggle(on):
    values = [c.value for c in app.mode_toggle_inputs]
    values[0] = on
    return app.toggle_scenario_mode(*values)


def test_toggle_returns_one_update_per_declared_output():
    for on in (True, False):
        assert len(_toggle(on)) == len(app.mode_toggle_outputs)
        assert len(_toggle(on)) == CONTAINERS + 2 * SIZE


def test_toggle_swaps_the_two_tab_containers():
    """One container hides as the other shows -- a plain element toggle."""
    on, off = _toggle(True), _toggle(False)
    # global panel, probability panel, single-model tabs, scenario tabs
    assert [u["visible"] for u in on[:CONTAINERS]] == [False, True, False, True]
    assert [u["visible"] for u in off[:CONTAINERS]] == [True, False, True, False]


def test_exactly_one_tab_container_is_visible_in_each_state():
    """Both visible would stack two tab bars; neither would blank the pane."""
    for on in (True, False):
        single, scenario = _toggle(on)[2]["visible"], _toggle(on)[3]["visible"]
        assert single != scenario


def test_no_tab_relies_on_individual_visibility_any_more():
    """The regression guard: tab items must not carry a visible=False override.

    A hidden tab item is what the browser failed to honour, and what left a hidden
    tab selected on first load. Every tab now lives in a container that is shown or
    hidden as a whole, so none of them should be individually hidden.
    """
    import gradio as gr

    tabs = [b for b in app.demo.blocks.values() if isinstance(b, gr.Tab)]
    assert tabs, "expected the app to declare some tabs"
    assert all(t.visible is True for t in tabs), (
        "a tab is individually hidden; container visibility is the supported path"
    )


def test_both_tab_containers_open_on_their_first_tab():
    """No `selected` juggling: each container's leading tab is the right one.

    Scenarios leads its own container, so it is active the moment that container
    appears -- and because no hidden tab can be selected, the right-hand pane
    cannot come up blank the way it did before.
    """
    import gradio as gr

    def first_tab(container):
        kids = [c for c in container.children if isinstance(c, gr.Tab)]
        return kids[0].label

    assert app.single_model_tabs.visible is True      # the app opens on this one
    assert first_tab(app.single_model_tabs) == "Valuation"
    assert app.scenario_model_tabs.visible is False
    assert first_tab(app.scenario_model_tabs) == "Scenarios"


def test_toggle_copies_the_base_assumptions_one_way():
    """Turning on copies the left pane into Base; turning off copies it back.

    Both panels are written from the one authoritative source, so the copy cannot
    flow in both directions and cannot loop.
    """
    values = [c.value for c in app.mode_toggle_inputs]
    values[0] = True
    values[1 + Y1G] = 77.0                      # edit the left pane
    out = app.toggle_scenario_mode(*values)
    written = [u["value"] for u in out[CONTAINERS:]]
    left_written, base_written = written[:SIZE], written[SIZE:]
    assert left_written == base_written          # both take the same source
    assert base_written[Y1G] == 77.0             # and the source was the left pane

    values[0] = False
    values[1 + SIZE + Y1G] = 12.0               # edit the Base tab instead
    out = app.toggle_scenario_mode(*values)
    written = [u["value"] for u in out[CONTAINERS:]]
    assert written[Y1G] == written[SIZE + Y1G] == 12.0


# --- layout: the controls must sit above the panels, not inside a column ------

def test_toggle_hides_the_whole_assumptions_column():
    """The void-space fix.

    Previously only the column's *contents* were swapped, so scenario mode still
    reserved two fifths of the page for a bar and two sliders. Hiding the column
    itself takes it out of the flex flow and lets the tabs have the whole row.
    """
    assert app.mode_toggle_outputs[0] is app.assumptions_column
    assert app.assumptions_column.scale == 2
    assert _toggle(True)[0]["visible"] is False
    assert _toggle(False)[0]["visible"] is True


def test_mode_controls_sit_above_the_panel_row_not_inside_it():
    """Structural guard against the dead space coming back.

    If the toggle or the probability split drift back inside a column, that column
    can no longer be hidden and the width is lost again. Asserted against the layout
    tree rather than trusting a comment. Note Gradio wraps inputs in its own `form`
    nodes, so membership is checked over descendants, not direct children.
    """
    config = app.demo.get_config_file()
    by_id = {c["id"]: c for c in config["components"]}

    def subtree(node):
        yield node.get("id")
        for child in node.get("children", []) or []:
            yield from subtree(child)

    top = config["layout"]["children"]
    rows = [n for n in top if by_id.get(n.get("id"), {}).get("type") == "row"]
    assert len(rows) == 1, "expected exactly one top-level panel row"
    panel_row = rows[0]

    inside_row = set(subtree(panel_row))
    assert app.scenario_mode._id not in inside_row, "the toggle must sit above the row"
    assert app.probability_panel._id not in inside_row, "the split must sit above the row"

    # but they are on the page, above it
    page = set()
    for node in top:
        page |= set(subtree(node))
    assert app.scenario_mode._id in page
    assert app.probability_panel._id in page

    # and the row holds exactly the two panel columns, assumptions first
    row_children = panel_row.get("children", [])
    assert len(row_children) == 2
    assert row_children[0].get("id") == app.assumptions_column._id


def test_the_two_cut_sliders_share_a_row():
    """Full width now, so side by side rather than stacked down the page."""
    config = app.demo.get_config_file()
    by_id = {c["id"]: c for c in config["components"]}

    def find(node, target):
        if node.get("id") == target:
            return node
        for child in node.get("children", []) or []:
            hit = find(child, target)
            if hit:
                return hit
        return None

    def subtree(node):
        yield node.get("id")
        for child in node.get("children", []) or []:
            yield from subtree(child)

    panel = find(config["layout"], app.probability_panel._id)
    assert panel is not None, "probability panel should be in the layout"

    def rows(node):
        for child in node.get("children", []) or []:
            if by_id.get(child.get("id"), {}).get("type") == "row":
                yield child
            yield from rows(child)

    shared = [r for r in rows(panel)
              if {app.cut_a._id, app.cut_b._id} <= set(subtree(r))]
    assert shared, "cut_a and cut_b should share one row inside the split panel"


def test_scenario_chart_and_table_sit_side_by_side():
    """The panel was long enough to scroll; the two are read together anyway.

    Done with a CSS grid rather than Gradio columns because the whole panel is one
    gr.HTML string, so there is nothing for Gradio's layout to split.
    """
    panel, _ = _scenario()
    assert 'class="sp-split"' in panel
    assert re.search(r'sp-split-chart">\s*<div class="sp-wrap"', panel), \
        "the value chart belongs in the left cell"
    assert re.search(r'sp-split-table">\s*<table class="bridge compact"', panel), \
        "the by-scenario table belongs in the right cell"
    # and the split must not have cost any content
    assert re.findall(r'data-case="(\w+)"', panel) == ["Bear", "Base", "Bull", "Weighted"]
    assert len(re.findall(r'class="be-req"', panel)) == 5


def test_scenario_split_collapses_on_a_narrow_screen():
    """Two columns are only worth having when there is room for them."""
    assert "minmax(0, 3fr) minmax(0, 2fr)" in app.CSS
    assert "@media (max-width: 900px) { .sp-split { grid-template-columns: minmax(0, 1fr); } }" \
        in app.CSS


def test_break_even_type_is_sized_for_the_column_it_renders_in():
    """The driver type tracks the width of its cell, not a fixed preference.

    That SVG has a 720-unit viewBox, so its text scales with the container. Rendered
    full width it was blown up and the sizes were cut to 9-10px. Now it sits in the
    head row's third column and scales DOWN instead, so the user units have to come
    back up to land at a similar rendered size. The range below is what keeps it
    legible in that cell without ballooning if it is ever widened again.
    """
    sizes = [float(v) for v in re.findall(
        r"\.be-(?:label|verdict|reason|num) \{ font-size: ([\d.]+)px", app.CSS)]
    assert len(sizes) == 4
    assert 10.0 <= min(sizes), "too small once the SVG is scaled down"
    assert max(sizes) <= 13.0, "too large if the column is ever widened"


def test_recommendation_and_tiles_share_the_panel_head():
    """Verdict on the left, its three supporting numbers stacked on the right."""
    panel, _ = _scenario()
    assert 'class="sp-head"' in panel
    assert re.search(r'sp-head">\s*<div class="rec"', panel, re.S), \
        "the recommendation block leads the head row"
    assert 'class="kpi-stack"' in panel
    assert 'class="kpi-grid"' not in panel, "tiles should stack, not sit in a 3-across grid"
    assert panel.count('class="kpi"') == 3
    assert re.findall(r'class="label">([^<]+)<', panel)[:3] == [
        "Probability-weighted value", "Upside", "P(worth more than price)",
    ]


def test_the_head_row_holds_three_columns_and_degrades_in_stages():
    """Verdict, tiles, drivers -- in that order, left to right.

    This deliberately gives up the shared column edge the head and the chart/table
    split used to have: three columns above and two below cannot align without
    distorting one of them. Instead the head breaks in two stages, so it never sits
    in a half-collapsed state where the drivers are crushed.
    """
    assert "minmax(0, 3fr) minmax(0, 2fr) minmax(0, 4fr)" in app.CSS
    assert "@media (max-width: 1250px)" in app.CSS      # drivers drop to their own row
    assert "@media (max-width: 900px)" in app.CSS       # then everything stacks
    assert ".sp-head-drivers { grid-column: 1 / -1; }" in app.CSS

    panel, _ = _scenario()
    head = re.search(r'<div class="sp-head">(.*?)<div class="sp-split">', panel, re.S)
    assert head is not None
    order = re.findall(r'class="(rec|kpi-stack|sp-head-drivers)"', head.group(1))
    assert order == ["rec", "kpi-stack", "sp-head-drivers"]

    # and the drivers are no longer rendered below the chart/table split
    after_split = panel[panel.index('<div class="sp-split">'):]
    assert "be-wrap" not in after_split


def test_warnings_reach_the_panel_and_a_clean_run_shows_nothing():
    """The notice leads the valuation panel, and is absent when there is nothing to say."""
    assert "model-warn" not in _panel()

    flagged = _panel(**{
        "Year 1 operating margin (%)": 2.0,
        "Year 5 operating margin (%)": 2.0,
        "Net capex (% of revenue)": 20.0,
    })
    assert "model-warn" in flagged
    assert 'data-code="negative_terminal_fcf"' in flagged
    # valued, not blocked -- the number is still there
    assert "Cannot value this scenario" not in flagged
    # and the notice comes before the numbers it qualifies
    assert flagged.index("model-warn") < flagged.index("kpi-grid")


def test_a_blocking_condition_still_shows_the_red_card_everywhere():
    values = [c.value for c in app.all_inputs]
    labels = [c.label for c in app.all_inputs]
    values[labels.index("WACC (%)")] = 4.0
    values[labels.index("Terminal growth (%)")] = 3.9
    valuation, chart, waterfall, *grids = app.valuate(*values)

    for panel in (valuation, chart, waterfall):
        assert "Cannot value this scenario" in panel
        assert "too close to terminal growth" in panel
    assert "model-warn" not in valuation, "a blocked run shows the red card, not amber"


def test_a_flagged_case_is_marked_in_the_scenario_table():
    """So a suspect bear case is visible without opening its tab."""
    panel, _ = _scenario({
        BEAR_0 + Y1M: 2.0, BEAR_0 + Y5M: 2.0, BEAR_0 + CAPEX: 20.0,
    })
    assert 'class="case-flag"' in panel
    row = re.search(r"<tr><td>Bear.*?</tr>", panel, re.S).group(0)
    assert "case-flag" in row, "the marker belongs on the Bear row"
    assert "negative terminal fcf" in row      # the code, humanised, in the tooltip

    clean, _ = _scenario()
    assert 'class="case-flag"' not in clean


# --- ink must outrank Gradio's own text colour --------------------------------

#: Gradio ships `.gradio-container-<version> .prose * { color: var(--body-text-color) }`.
#: The universal selector sets `color` directly on every descendant of a `gr.HTML`, so it
#: beats both a single-class rule and inheritance from a parent. Anything of ours that
#: picks ink to suit its own background has to outrank it or the theme repaints the text.
PROSE_STAR_SPECIFICITY = (0, 2, 0)

#: Elements whose text sits on a background *we* choose, so the ink is not decorative --
#: if the theme repaints it the text can vanish entirely. At the diverging ramp's neutral
#: step the heatmap cell is near-white, which is exactly where this was first seen.
INK_ON_CUSTOM_BACKGROUND = ("hm-cell", "hm-v", "hm-u", "sp-seg-l")


def _specificity(selector):
    """(ids, classes, elements) for a CSS selector, per the cascade spec."""
    inside_not = " ".join(re.findall(r":not\(([^)]*)\)", selector))
    bare = re.sub(r":not\([^)]*\)", " ", selector)
    # Pseudo-ELEMENTS count at element level, pseudo-CLASSES (:hover) at class level.
    # Pull the former out first, or the latter's pattern claims them. The four legacy
    # single-colon spellings still count as elements, and Gradio's compiled CSS uses
    # `:after` -- so missing them would misjudge the very rules we compare against.
    pseudo_element = r"::[\w-]+|:(?:after|before|first-line|first-letter)\b"
    pseudo_elements = len(re.findall(pseudo_element, bare))
    bare = re.sub(pseudo_element, " ", bare)
    ids = len(re.findall(r"#[\w-]+", bare)) + len(re.findall(r"#[\w-]+", inside_not))
    classes = (len(re.findall(r"\.[\w-]+|\[[^\]]+\]", bare))
               + len(re.findall(r"\.[\w-]+|\[[^\]]+\]", inside_not))
               + len(re.findall(r":[\w-]+", bare)))
    stripped = re.sub(r"\.[\w-]+|#[\w-]+|:[\w-]+|\[[^\]]+\]", " ", bare)
    elements = len(re.findall(r"[a-zA-Z][\w-]*", stripped)) + pseudo_elements
    return (ids, classes, elements)


def _colour_rules():
    """Every (selector, declarations) pair in the app's CSS that sets `color`.

    Comments are stripped first and the whole selector list is kept: a multi-line list
    like `.a,
.a .b,
.a .c { ... }` must yield all three, or a guard built on this
    silently checks only the last one.
    """
    css = re.sub(r"/\*.*?\*/", " ", app.CSS, flags=re.S)
    for raw_sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(raw_sel.split())
        if not selector or selector.startswith("@"):
            continue
        if not re.search(r"(?:^|;|\s)color\s*:", body):
            continue
        for one in (s.strip() for s in selector.split(",")):
            if one:
                yield one, body


def test_specificity_helper_agrees_with_the_cascade_rules():
    """The guard below is only as good as this; pin it on known answers."""
    assert _specificity(".hm-cell") == (0, 1, 0)
    assert _specificity(".hm-cell.hm-cell") == (0, 2, 0)
    assert _specificity(".hm-cell.hm-cell .hm-v") == (0, 3, 0)
    assert _specificity(".dark .hm-cell.hm-cell") == (0, 3, 0)
    # :not() contributes its argument's specificity, not its own
    assert _specificity("html:not(.dark) .hm-cell") == (0, 2, 1)
    assert _specificity(".gradio-container-6-26-0 .prose *") == PROSE_STAR_SPECIFICITY
    # a pseudo-element scores as an element, a pseudo-class as a class
    assert _specificity(".a::after") == (0, 1, 1)
    assert _specificity(".a:hover") == (0, 2, 0)
    assert _specificity(".tab-container.svelte-11gaq1:after") == (0, 2, 1)


def test_ink_on_custom_backgrounds_outranks_the_theme():
    """The regression guard for white-on-white heatmap cells.

    Every rule that inks an element sitting on one of our own backgrounds must beat
    `.prose *`, in every one of its light/dark variants -- a single variant left at one
    class is enough to hand that branch of the cascade back to the theme.
    """
    seen = {name: 0 for name in INK_ON_CUSTOM_BACKGROUND}
    for selector, _ in _colour_rules():
        for name in INK_ON_CUSTOM_BACKGROUND:
            if re.search(rf"\.{name}\b", selector):
                seen[name] += 1
                assert _specificity(selector) > PROSE_STAR_SPECIFICITY, (
                    f"`{selector}` sets ink on a background we choose but only scores "
                    f"{_specificity(selector)}, so Gradio's .prose * ({PROSE_STAR_SPECIFICITY}) "
                    f"repaints it with the theme's body colour"
                )
    for name, count in seen.items():
        assert count >= 2, f".{name} needs a light and a dark ink rule, found {count}"


def test_every_heatmap_band_is_legible_against_its_own_cell():
    """Ink is chosen per band; check the choice actually separates from the background.

    The neutral 'fair' band is the one that bit us: a near-white cell in light mode and a
    dark grey one in dark mode, so a single hardcoded ink cannot serve both.
    """
    from viz import diverging_ramp, hex_to_oklab, ink_for

    for mode in ("light", "dark"):
        for i, bg in enumerate(diverging_ramp(mode)):
            ink = ink_for(bg, mode)
            gap = abs(hex_to_oklab(bg)[0] - hex_to_oklab(ink)[0])
            assert gap > 0.35, (
                f"{mode} band {i}: ink {ink} on {bg} separates by only {gap:.2f} in "
                f"OKLab lightness"
            )


# --- tab styling ---------------------------------------------------------------

#: What Gradio's own tab rules score. Its component styles are `.tab-container` /
#: `.selected` paired with a `svelte-<hash>` class, i.e. two classes.
GRADIO_TAB_SPECIFICITY = (0, 2, 0)


def _tab_rules():
    css = re.sub(r"/\*.*?\*/", " ", app.CSS, flags=re.S)
    for raw_sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(raw_sel.split())
        if selector and ("tab-container" in selector or "tab-wrapper" in selector):
            yield selector, body


def test_tab_rules_outrank_gradios_own_component_styles():
    """Same failure mode as the heatmap ink: a tie is decided by source order."""
    rules = list(_tab_rules())
    assert rules, "no tab styling found"
    for selector, _ in rules:
        assert _specificity(selector) > GRADIO_TAB_SPECIFICITY, (
            f"`{selector}` scores {_specificity(selector)}, which does not beat "
            f"Gradio's own tab rules at {GRADIO_TAB_SPECIFICITY}"
        )


def test_tab_rules_never_key_on_a_svelte_hash():
    """Those class names change on every Gradio release, so styling must not use them."""
    assert not re.search(r"svelte-[a-z0-9]+", app.CSS), \
        "a svelte hash in our CSS will silently stop matching on the next upgrade"


def test_tab_selectors_require_both_the_class_and_the_role():
    """Gradio renders decoys that a looser selector would hit.

    A `visually-hidden` .tab-container is rendered as a measuring clone (it carries
    no role), and the stepper component puts role="tablist" on .stepper-container.
    Pairing the class with the role excludes both.
    """
    for selector, _ in _tab_rules():
        if "tab-container" in selector:
            assert '[role="tablist"]' in selector, selector
        assert "stepper" not in selector


def test_the_active_tab_is_marked_by_more_than_colour():
    """Greyscale and colour-vision safety: hue alone must not carry the state."""
    selected = [body for sel, body in _tab_rules() if ".selected" in sel]
    assert selected, "no rule styles the active tab"
    combined = " ".join(selected)
    for signal in ("background", "border-color", "font-weight"):
        assert signal in combined, f"the active tab does not differ by {signal}"


def test_nested_case_tabs_stay_subordinate_to_the_outer_strip():
    """Two equally loud tab strips stacked would lose the hierarchy."""
    nested = [(s, b) for s, b in _tab_rules() if '[role="tabpanel"]' in s]
    assert nested, "nested tabs are not distinguished from the outer strip"
    # the nested strip drops the trough that the outer one draws
    assert any("transparent" in b for _, b in nested)


# --- tab labels ----------------------------------------------------------------
#
# Gradio measures the tab strip and moves whatever does not fit into a ">>" overflow
# menu, so a long label does not wrap or truncate -- it hides a whole view behind a
# dropdown. These guards keep the six views reachable without one.

import gradio as gr  # noqa: E402


def _tab_labels(tabs):
    return [c.label for c in tabs.children if isinstance(c, gr.TabItem)]


def _nested_tabs(node):
    for child in getattr(node, "children", []):
        if isinstance(child, gr.Tabs):
            return child
        found = _nested_tabs(child)
        if found is not None:
            return found
    return None


def test_the_two_tab_structures_carry_identical_labels():
    """The single-model strip and the per-case strips are built separately.

    One is an inline loop over (label, id) pairs, the other is `view_tabs()`. Adding a
    view to one and not the other leaves the case tabs silently short of a panel, and
    nothing else in the suite would notice.
    """
    single = _tab_labels(app.single_model_tabs)
    assert len(single) == 6
    for case in ("Base", "Bear", "Bull"):
        tab = [c for c in app.scenario_model_tabs.children
               if isinstance(c, gr.TabItem) and c.label == case][0]
        nested = _nested_tabs(tab)
        assert nested is not None, case
        assert _tab_labels(nested) == single, case


def test_view_labels_are_short_enough_to_stay_out_of_the_overflow_menu():
    """A budget, not a limit on any single name.

    Six views at these labels come to roughly 1,000px of strip, which fits from about
    a 1,700px window upward. The old "Sensitivity - " prefixes cost ~380px on their
    own and pushed the strip past 1,380px. This keeps a new tab from quietly
    reintroducing that.
    """
    labels = _tab_labels(app.single_model_tabs)
    assert "Sensitivity - " not in " ".join(labels)
    total = sum(len(label) for label in labels)
    assert total <= 130, (
        f"tab labels total {total} characters; past ~130 the strip needs a window "
        f"wider than most laptops or Gradio hides views behind a '>>' menu"
    )
    assert max(len(label) for label in labels) <= 40


def test_scenario_mode_tabs_lead_with_scenarios():
    assert _tab_labels(app.scenario_model_tabs) == ["Scenarios", "Base", "Bear", "Bull"]
