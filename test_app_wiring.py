"""Guards on the Gradio wiring.

`gr.on` binds `all_inputs` to `valuate()` positionally, so a slider added or moved
in one place and not the other misassigns values silently -- the app would still
run and still produce a plausible number, just the wrong one. These tests make
that failure loud.
"""

import inspect

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

    taper_growth = growth_schedule(50, 15, 3, horizon=10)[:5]
    taper_margin = margin_schedule(62.4, 55, horizon=10)[:5]
    assert app.GROWTH_BY_YEAR == taper_growth
    assert app.MARGIN_BY_YEAR == taper_margin


def test_both_modes_render_the_same_panel_at_defaults():
    defaults = [c.value for c in app.all_inputs]
    taper_panel, taper_heat = app.valuate(*defaults)

    per_year = list(defaults)
    per_year[0] = app.PER_YEAR
    py_panel, py_heat = app.valuate(*per_year)

    assert taper_panel == py_panel
    assert taper_heat == py_heat


def test_signal_thresholds():
    assert app.signal_for(0.30) == "BUY"
    assert app.signal_for(0.0) == "HOLD"
    assert app.signal_for(-0.40) == "SELL"
