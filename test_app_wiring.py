"""Guards on the Gradio wiring.

`gr.on` binds `all_inputs` to `valuate()` positionally, so a slider added or moved
in one place and not the other misassigns values silently -- the app would still
run and still produce a plausible number, just the wrong one. These tests make
that failure loud.
"""

import inspect
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
    assert "($34.7B)" in panel


def test_guardrail_renders_a_warning_not_a_half_built_table():
    panel = _panel(**{"WACC (%)": 4.0, "Terminal growth (%)": 5.0})
    assert "Cannot value this scenario" in panel
    assert "<tbody>" not in panel


