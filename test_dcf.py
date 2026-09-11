"""Sanity checks for the DCF math -- run with: .venv/Scripts/python.exe -m pytest -q"""

import pytest

from dcf import growth_schedule, run_dcf


def test_hand_checked_single_year():
    """A case simple enough to verify with a calculator.

    Revenue 100, no growth, 50% gross margin, 30% opex -> EBIT 20, no tax,
    100% FCF conversion. At a 10% WACC and 0% terminal growth the perpetuity
    is worth 20/0.10 = 200 today, and the one forecast year is already inside it.
    """
    r = run_dcf(
        revenue=100, year_1_growth=0.0, year_5_growth=0.0, terminal_growth=0.0,
        gross_margin=0.50, opex_pct=0.30, tax_rate=0.0, wacc=0.10, horizon=1,
        fcf_conversion=1.0, cash=0, debt=0, shares=1, current_price=100,
    )
    assert r.rows[0].free_cash_flow == pytest.approx(20.0)
    assert r.rows[0].pv_of_fcf == pytest.approx(20 / 1.1)
    assert r.terminal_value == pytest.approx(200.0)
    assert r.enterprise_value == pytest.approx(200.0)
    assert r.value_per_share == pytest.approx(200.0)
    assert r.upside == pytest.approx(1.0)


def test_cash_and_debt_bridge():
    """Equity value = enterprise value + cash - debt, divided by shares."""
    base = dict(
        revenue=100, year_1_growth=0.0, year_5_growth=0.0, terminal_growth=0.0,
        gross_margin=0.50, opex_pct=0.30, tax_rate=0.0, wacc=0.10, horizon=1,
        fcf_conversion=1.0, shares=10, current_price=20,
    )
    r = run_dcf(cash=50, debt=30, **base)
    assert r.equity_value == pytest.approx(200.0 + 50 - 30)
    assert r.value_per_share == pytest.approx(22.0)


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


def test_wacc_below_terminal_growth_is_rejected():
    with pytest.raises(ValueError, match="must exceed terminal growth"):
        run_dcf(wacc=0.02, terminal_growth=0.03)


def test_higher_wacc_lowers_value():
    low = run_dcf(wacc=0.08).value_per_share
    high = run_dcf(wacc=0.12).value_per_share
    assert high < low


# --- sensitivity grid & heatmap color scale ---

from dcf import sensitivity_grid
from viz import band_index, diverging_ramp, hex_to_oklab

WACC_AXIS = [0.08, 0.10, 0.12, 0.14]
TERM_AXIS = [0.01, 0.03, 0.05]


def test_grid_shape_and_direction():
    grid = sensitivity_grid(WACC_AXIS, TERM_AXIS)
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
    grid = sensitivity_grid([0.02, 0.10], [0.05])
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
