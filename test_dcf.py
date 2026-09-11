"""Sanity checks for the DCF math -- run with: .venv/Scripts/python.exe -m pytest -q"""

import pytest

from dcf import (
    growth_schedule,
    margin_schedule,
    run_dcf,
    sensitivity_grid,
)
from viz import band_index, diverging_ramp, hex_to_oklab

# A stripped-down scenario: no growth, no tax, no capex, no working capital.
# Everything that could complicate the arithmetic is switched off.
PLAIN = dict(
    revenue=100, year_1_growth=0.0, year_5_growth=0.0, terminal_growth=0.0,
    year_1_margin=0.20, year_5_margin=0.20, tax_rate=0.0, wacc=0.10, horizon=1,
    net_capex_pct=0.0, nwc_pct_of_growth=0.0,
)


def test_hand_checked_single_year():
    """A case simple enough to verify with a calculator.

    Revenue 100 at a 20% operating margin is EBIT 20, untaxed, with nothing spent
    on capex or working capital -- so FCF is 20. At a 10% WACC and 0% terminal
    growth the perpetuity is worth 20/0.10 = 200 today.
    """
    r = run_dcf(**PLAIN, cash=0, debt=0, shares=1, current_price=100)
    assert r.rows[0].operating_income == pytest.approx(20.0)
    assert r.rows[0].free_cash_flow == pytest.approx(20.0)
    assert r.rows[0].pv_of_fcf == pytest.approx(20 / 1.1)
    assert r.terminal_value == pytest.approx(200.0)
    assert r.enterprise_value == pytest.approx(200.0)
    assert r.value_per_share == pytest.approx(200.0)
    assert r.upside == pytest.approx(1.0)


def test_cash_and_debt_bridge():
    """Equity value = enterprise value + cash - debt, divided by shares."""
    r = run_dcf(**PLAIN, cash=50, debt=30, shares=10, current_price=20)
    assert r.equity_value == pytest.approx(200.0 + 50 - 30)
    assert r.value_per_share == pytest.approx(22.0)


# --- free cash flow drivers ---

def test_net_capex_reduces_fcf_by_exactly_its_share_of_revenue():
    base = run_dcf(**PLAIN, shares=1)
    with_capex = run_dcf(**{**PLAIN, "net_capex_pct": 0.05}, shares=1)
    row_b, row_c = base.rows[0], with_capex.rows[0]
    assert row_c.net_capex == pytest.approx(row_c.revenue * 0.05)
    assert row_b.free_cash_flow - row_c.free_cash_flow == pytest.approx(row_c.net_capex)


def test_working_capital_keys_off_growth_not_revenue_level():
    """Flat revenue must consume no working capital, however large the company."""
    flat = run_dcf(**{**PLAIN, "nwc_pct_of_growth": 0.50}, shares=1)
    assert flat.rows[0].change_in_nwc == pytest.approx(0.0)

    growing = run_dcf(**{**PLAIN, "year_1_growth": 0.20,
                         "nwc_pct_of_growth": 0.50}, shares=1)
    row = growing.rows[0]
    assert row.change_in_nwc == pytest.approx((120 - 100) * 0.50)   # 10.0
    assert row.free_cash_flow == pytest.approx(row.nopat - row.change_in_nwc)


def test_growing_working_capital_lowers_value():
    cheap = run_dcf(**{**PLAIN, "year_1_growth": 0.20}, shares=1).value_per_share
    dear = run_dcf(**{**PLAIN, "year_1_growth": 0.20,
                      "nwc_pct_of_growth": 0.50}, shares=1).value_per_share
    assert dear < cheap


# --- schedules: taper vs. per-year ---

def test_growth_tapers_through_both_legs():
    rates = growth_schedule(0.50, 0.15, 0.03, horizon=10)
    assert rates[0] == pytest.approx(0.50)      # year 1 hits the entry rate
    assert rates[4] == pytest.approx(0.15)      # year 5 hits the mid rate
    assert rates[-1] == pytest.approx(0.03)     # final year lands on terminal
    assert rates == sorted(rates, reverse=True)  # monotonic decline, no bumps


def test_short_horizon_never_reaches_terminal_leg():
    rates = growth_schedule(0.50, 0.15, 0.03, horizon=3)
    assert len(rates) == 3
    assert rates[0] == pytest.approx(0.50)
    assert rates[2] == pytest.approx(0.325)     # still gliding toward year 5


def test_explicit_growth_is_used_verbatim_then_tapers_from_year_5():
    explicit = [0.60, 0.10, 0.40, 0.20, 0.12]   # deliberately not monotonic
    rates = growth_schedule(0.50, 0.15, 0.02, horizon=7, explicit=explicit)
    assert rates[:5] == pytest.approx(explicit)
    assert rates[6] == pytest.approx(0.02)      # last year still lands on terminal


def test_explicit_margins_used_verbatim_and_held_flat_after_year_5():
    explicit = [0.62, 0.60, 0.58, 0.56, 0.54]
    margins = margin_schedule(0.624, 0.55, horizon=9, explicit=explicit)
    assert margins[:5] == pytest.approx(explicit)
    assert margins[5:] == pytest.approx([0.54] * 4)   # flat at the year-5 level


def test_margin_taper_holds_flat_beyond_year_5():
    margins = margin_schedule(0.624, 0.55, horizon=8)
    assert margins[0] == pytest.approx(0.624)
    assert margins[4] == pytest.approx(0.55)
    assert margins[5:] == pytest.approx([0.55] * 3)


def test_wrong_length_explicit_lists_are_rejected():
    with pytest.raises(ValueError, match="exactly years 1-5"):
        growth_schedule(0.5, 0.15, 0.03, horizon=10, explicit=[0.5, 0.4])
    with pytest.raises(ValueError, match="exactly years 1-5"):
        margin_schedule(0.62, 0.55, horizon=10, explicit=[0.6] * 6)


def test_the_two_modes_are_the_same_model():
    """Per-year mode fed the taper's own schedule must value identically.

    This is what makes the UI toggle a choice of input style rather than a
    choice between two subtly different models.
    """
    taper = run_dcf()
    same = run_dcf(
        growth_rates=growth_schedule(0.50, 0.15, 0.03, horizon=10)[:5],
        operating_margins=margin_schedule(0.624, 0.55, horizon=10)[:5],
    )
    assert same.value_per_share == pytest.approx(taper.value_per_share)
    assert [r.free_cash_flow for r in same.rows] == pytest.approx(
        [r.free_cash_flow for r in taper.rows]
    )


# --- the discounting chain, end to end ---

def test_terminal_value_is_gordon_growth():
    """TV = final-year FCF x (1 + g) / (WACC - g), recomputed independently here.

    Pinned deliberately: this formula is the single largest contributor to the
    valuation, and a refactor that quietly changed it would still produce a
    plausible-looking number.
    """
    for wacc, g in [(0.10, 0.03), (0.08, 0.01), (0.14, 0.045)]:
        r = run_dcf(wacc=wacc, terminal_growth=g)
        expected = r.rows[-1].free_cash_flow * (1 + g) / (wacc - g)
        assert r.terminal_value == pytest.approx(expected)
        assert r.wacc == pytest.approx(wacc)
        assert r.terminal_growth == pytest.approx(g)


def test_every_year_is_discounted_consistently():
    r = run_dcf()
    for row in r.rows:
        assert row.discount_factor == pytest.approx(1 / (1 + r.wacc) ** row.year)
        assert row.pv_of_fcf == pytest.approx(row.free_cash_flow * row.discount_factor)


def test_present_values_sum_to_the_reported_totals():
    r = run_dcf()
    assert r.pv_of_forecast == pytest.approx(sum(row.pv_of_fcf for row in r.rows))
    assert r.pv_of_terminal == pytest.approx(
        r.terminal_value * r.rows[-1].discount_factor
    )
    assert r.enterprise_value == pytest.approx(r.pv_of_forecast + r.pv_of_terminal)


def test_equity_value_is_enterprise_value_less_net_debt():
    r = run_dcf()
    assert r.net_debt == pytest.approx(r.debt - r.cash)
    assert r.equity_value == pytest.approx(r.enterprise_value - r.net_debt)
    assert r.value_per_share == pytest.approx(r.equity_value / r.shares)


def test_net_cash_company_reports_negative_net_debt():
    """NVIDIA holds more cash than debt, so net debt is negative."""
    assert run_dcf().net_debt < 0


# --- guardrails and direction ---

def test_wacc_below_terminal_growth_is_rejected():
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        run_dcf(wacc=0.02, terminal_growth=0.03)


def test_higher_wacc_lowers_value():
    assert run_dcf(wacc=0.12).value_per_share < run_dcf(wacc=0.08).value_per_share


def test_higher_margin_raises_value():
    low = run_dcf(year_1_margin=0.50, year_5_margin=0.45).value_per_share
    high = run_dcf(year_1_margin=0.70, year_5_margin=0.65).value_per_share
    assert high > low


# --- sensitivity grid & heatmap color scale ---

WACC_AXIS = [0.08, 0.10, 0.12, 0.14]
TERM_AXIS = [0.01, 0.03, 0.05]


def test_grid_shape_and_direction():
    grid = sensitivity_grid("wacc", WACC_AXIS, "terminal_growth", TERM_AXIS)
    assert len(grid) == len(TERM_AXIS)
    assert all(len(row) == len(WACC_AXIS) for row in grid)

    values = [[c.value_per_share for c in row] for row in grid]
    for row in values:                      # value falls as WACC rises
        assert row == sorted(row, reverse=True)
    for col in range(len(WACC_AXIS)):       # value rises with terminal growth
        column = [row[col] for row in values]
        assert column == sorted(column)


def test_grid_marks_impossible_pairs_none():
    """WACC 2% with terminal growth 5% has no finite value."""
    grid = sensitivity_grid("wacc", [0.02, 0.10], "terminal_growth", [0.05])
    assert grid[0][0] is None
    assert grid[0][1] is not None


def test_bands_are_symmetric_and_cover_the_ramp():
    assert band_index(-0.90) == 0
    assert band_index(0.0) == 4       # fair value lands on the neutral midpoint
    assert band_index(0.90) == 8


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_ramp_is_monotonic_outward_from_neutral(mode):
    """A diverging ramp is checked on lightness, not CVD adjacency."""
    ramp = diverging_ramp(mode)
    assert len(ramp) == 9
    lightness = [hex_to_oklab(c)[0] for c in ramp]
    over, under = lightness[:5], lightness[4:]
    assert over == sorted(over) or over == sorted(over, reverse=True)
    assert under == sorted(under) or under == sorted(under, reverse=True)
    # the neutral midpoint sits closest to the surface in both modes
    assert lightness[4] == (max(lightness) if mode == "light" else min(lightness))


# --- the generalised sensitivity grid ---

from dcf import apply_year_5_margin, margin_schedule as _ms  # noqa: E402

MARGIN_AXIS = [0.40, 0.50, 0.60, 0.70]


def test_generalised_grid_reproduces_the_wacc_one():
    """Refactoring the grid must not move a single number on the WACC tab."""
    grid = sensitivity_grid("wacc", WACC_AXIS, "terminal_growth", TERM_AXIS)
    for g, row in zip(TERM_AXIS, grid):
        for w, cell in zip(WACC_AXIS, row):
            assert cell.value_per_share == pytest.approx(
                run_dcf(wacc=w, terminal_growth=g).value_per_share
            )


def test_margin_axis_actually_bites_in_per_year_mode():
    """The trap: an explicit margin list silently overrides year_5_margin.

    A grid that set the keyword alone would render identical columns and look
    entirely convincing doing it.
    """
    per_year = dict(operating_margins=[0.624, 0.6055, 0.587, 0.5685, 0.55])

    # the naive approach really is inert -- this is what we are guarding against
    assert run_dcf(**per_year, year_5_margin=0.20).value_per_share == pytest.approx(
        run_dcf(**per_year).value_per_share
    )

    grid = sensitivity_grid("year_5_margin", MARGIN_AXIS,
                            "terminal_growth", TERM_AXIS, **per_year)
    values = [c.value_per_share for c in grid[0]]
    assert len(set(round(v, 2) for v in values)) == len(values)   # every column differs
    assert values == sorted(values)                               # and rises with margin


def test_margin_axis_means_the_same_thing_in_both_input_modes():
    """Moving a taper's endpoint would drag years 2-4; per-year mode would not.

    Left alone, the same question gets two answers depending on an input toggle.
    """
    taper = dict(year_1_margin=0.624, year_5_margin=0.55)
    per_year = dict(operating_margins=_ms(0.624, 0.55, horizon=10)[:5])

    for margin in MARGIN_AXIS:
        from_taper = run_dcf(**apply_year_5_margin(taper, margin))
        from_list = run_dcf(**apply_year_5_margin(per_year, margin))
        assert from_taper.value_per_share == pytest.approx(from_list.value_per_share)


def test_apply_year_5_margin_leaves_earlier_years_untouched():
    out = apply_year_5_margin(dict(year_1_margin=0.624, year_5_margin=0.55), 0.40)
    assert out["operating_margins"] == pytest.approx(
        [0.624, 0.6055, 0.587, 0.5685, 0.40]
    )
    assert "year_5_margin" not in out          # the dead keyword is dropped


def test_margin_grid_direction():
    grid = sensitivity_grid("year_5_margin", MARGIN_AXIS,
                            "terminal_growth", TERM_AXIS)
    values = [[c.value_per_share for c in row] for row in grid]
    for row in values:                                  # value rises with margin
        assert row == sorted(row)
    for col in range(len(MARGIN_AXIS)):                 # and with terminal growth
        assert [r[col] for r in values] == sorted(r[col] for r in values)


def test_margin_grid_honours_the_wacc_it_is_given():
    """It varies margin and terminal growth, so WACC must come from the caller."""
    cheap = sensitivity_grid("year_5_margin", MARGIN_AXIS, "terminal_growth",
                             [0.03], wacc=0.08)[0][0].value_per_share
    dear = sensitivity_grid("year_5_margin", MARGIN_AXIS, "terminal_growth",
                            [0.03], wacc=0.14)[0][0].value_per_share
    assert dear < cheap


def test_margin_grid_marks_unreachable_rows_none():
    """Holding WACC at 4% makes every row at or above it impossible."""
    grid = sensitivity_grid("year_5_margin", [0.55], "terminal_growth",
                            [0.02, 0.04, 0.05], wacc=0.04)
    assert grid[0][0] is not None      # 2% terminal growth is fine
    assert grid[1][0] is None          # 4% is not, at a 4% WACC
    assert grid[2][0] is None
