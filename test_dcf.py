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


# --- bear / base / bull scenarios ---

from dcf import probability_split, weighted_valuation  # noqa: E402

BEAR = dict(year_1_growth=0.25, year_5_growth=0.05, year_5_margin=0.45,
            wacc=0.12, terminal_growth=0.02)
BULL = dict(year_1_growth=0.75, year_5_growth=0.25, year_5_margin=0.65,
            wacc=0.09, terminal_growth=0.04)
CASES = [("Bear", 0.25, BEAR), ("Base", 0.50, {}), ("Bull", 0.25, BULL)]


def test_probability_split_always_sums_to_one():
    for a, b in [(25, 75), (0, 100), (50, 50), (0, 0), (100, 100), (33, 67)]:
        shares = probability_split(a, b)
        assert sum(shares) == pytest.approx(1.0)
        assert all(s >= 0 for s in shares)


def test_probability_split_clamps_reversed_and_out_of_range_cuts():
    assert probability_split(75, 25) == probability_split(25, 75)   # reversed
    assert probability_split(-40, 160) == (0.0, 1.0, 0.0)           # clamped
    assert probability_split(0, 100) == (0.0, 1.0, 0.0)             # base only
    assert probability_split(50, 50) == (0.5, 0.0, 0.5)             # no base


def test_weighted_value_is_the_sum_of_contributions():
    wv = weighted_valuation({}, CASES)
    assert wv.weighted_value == pytest.approx(
        sum(s.weight * s.result.value_per_share for s in wv.scenarios)
    )
    assert sum(s.weight for s in wv.scenarios) == pytest.approx(1.0)
    assert wv.valued_mass == pytest.approx(1.0)


def test_weighting_values_is_not_weighting_inputs():
    """Pinned deliberately -- the gap is ~47% and it flips the signal.

    The model is non-linear in its inputs (1/(WACC - g) is convex), so collapsing
    three run_dcf calls into one valuation of averaged assumptions would look like
    a harmless optimisation and change the answer enormously.
    """
    by_values = weighted_valuation({}, CASES).weighted_value

    # The same three cases with every key spelled out, so the average is plain.
    base = dict(year_1_growth=0.50, year_5_growth=0.15, year_5_margin=0.55,
                wacc=0.10, terminal_growth=0.03)
    weighted_inputs = {
        key: 0.25 * BEAR[key] + 0.50 * base[key] + 0.25 * BULL[key]
        for key in base
    }
    by_inputs = run_dcf(**weighted_inputs).value_per_share

    assert by_values != pytest.approx(by_inputs, rel=0.05)
    assert by_values > by_inputs                 # convexity pushes the true mean up
    assert by_values / by_inputs - 1 > 0.30      # and the gap is large, not marginal


def test_an_unvaluable_case_is_excluded_and_the_shortfall_reported():
    broken = dict(BEAR, wacc=0.03, terminal_growth=0.04)     # WACC below terminal
    wv = weighted_valuation({}, [("Bear", 0.25, broken),
                                 ("Base", 0.50, {}),
                                 ("Bull", 0.25, BULL)])
    bear = wv.scenarios[0]
    assert bear.result is None
    assert "must exceed terminal growth" in bear.error
    assert bear.weight == 0 and bear.contribution == 0

    assert wv.valued_mass == pytest.approx(0.75)             # the shortfall is visible
    assert sum(s.weight for s in wv.scenarios) == pytest.approx(1.0)   # renormalised
    assert not wv.all_failed


def test_all_cases_unvaluable_is_flagged():
    dead = dict(wacc=0.03, terminal_growth=0.04)
    wv = weighted_valuation({}, [(n, p, dead) for n, p, _ in CASES])
    assert wv.all_failed
    assert wv.weighted_value == 0


def test_scenario_margin_override_bites_in_per_year_mode():
    """The same trap as the sensitivity axis: an explicit list beats the keyword."""
    per_year = dict(operating_margins=[0.624, 0.6055, 0.587, 0.5685, 0.55])
    wv = weighted_valuation(per_year, CASES)
    values = [s.result.value_per_share for s in wv.scenarios]
    assert len(set(round(v, 2) for v in values)) == 3      # the cases really differ
    assert values[0] < values[1] < values[2]               # bear < base < bull


def test_probability_above_price_counts_the_cases_over_it():
    wv = weighted_valuation({}, CASES)
    expected = sum(s.probability for s in wv.scenarios
                   if s.result.value_per_share > wv.current_price)
    assert wv.probability_above_price == pytest.approx(expected)


# --- break-even solver and the recommendation ---

from dcf import (  # noqa: E402
    BREAK_EVEN_DRIVERS, DEFENSIBLE, DEMANDING, GLOBAL_SEMI_REVENUE, IMPOSSIBLE,
    MAX_TERMINAL_GROWTH, MIN_CREDIBLE_WACC, NVDA_GROSS_MARGIN, _apply_axis,
    break_even, current_setting, recommend, solve_for_target,
)

PRICE = 180.0


def test_solver_recovers_a_known_input():
    """Solving for the base case's own value must return the base assumption."""
    base = run_dcf().value_per_share
    found = solve_for_target({}, "wacc", 0.05, 0.25, base)
    assert found == pytest.approx(0.10, abs=1e-4)


def test_solver_returns_none_when_the_target_is_out_of_bracket():
    assert solve_for_target({}, "wacc", 0.09, 0.11, 10_000.0) is None
    assert solve_for_target({}, "terminal_growth", 0.0, 0.04, 1e9) is None


def test_every_break_even_value_round_trips_to_the_price():
    """The decisive test: the reverse solve and the forward model must agree.

    A solver that drifted would still produce plausible-looking required values
    and a confident-sounding verdict built on them.
    """
    for row in break_even({}, PRICE):
        if row.required is None:
            continue
        got = run_dcf(**_apply_axis({}, row.key, row.required)).value_per_share
        assert got == pytest.approx(PRICE, abs=0.01), row.label


def test_solver_bites_in_per_year_mode():
    """Third outing for the apply_year_5_margin trap: the list beats the keyword."""
    per_year = dict(operating_margins=[0.624, 0.6055, 0.587, 0.5685, 0.55])
    required = solve_for_target(per_year, "year_5_margin", 0.0, 0.95, PRICE)
    assert required is not None
    got = run_dcf(**_apply_axis(per_year, "year_5_margin", required)).value_per_share
    assert got == pytest.approx(PRICE, abs=0.01)


def test_current_setting_reads_whichever_way_margins_were_expressed():
    assert current_setting({}, "year_5_margin") == pytest.approx(0.55)
    assert current_setting(
        dict(operating_margins=[0.62, 0.60, 0.58, 0.56, 0.41]), "year_5_margin"
    ) == pytest.approx(0.41)
    assert current_setting(
        dict(growth_rates=[0.80, 0.6, 0.4, 0.3, 0.22]), "year_1_growth"
    ) == pytest.approx(0.80)
    # an explicit None must fall back to the default, not be returned as-is
    assert current_setting({"operating_margins": None}, "year_5_margin") == pytest.approx(0.55)


def test_break_even_covers_every_declared_driver():
    rows = break_even({}, PRICE)
    assert [r.key for r in rows] == [k for k, _, _, _ in BREAK_EVEN_DRIVERS]
    assert all(r.reason for r in rows)            # a verdict always carries its basis


def test_plausibility_verdicts_fire_on_their_thresholds():
    rows = {r.key: r for r in break_even({}, PRICE)}

    # at defaults the required margin exceeds NVIDIA's gross margin -> impossible
    assert rows["year_5_margin"].required > NVDA_GROSS_MARGIN
    assert rows["year_5_margin"].verdict == IMPOSSIBLE
    assert "gross margin" in rows["year_5_margin"].reason

    # and the required terminal growth exceeds long-run nominal GDP
    assert rows["terminal_growth"].required > MAX_TERMINAL_GROWTH
    assert rows["terminal_growth"].verdict == IMPOSSIBLE

    # growth routes imply more revenue than the whole industry
    for key in ("year_1_growth", "year_5_growth"):
        assert rows[key].verdict == DEMANDING
        assert str(int(GLOBAL_SEMI_REVENUE)) in rows[key].reason

    # the WACC route is the only defensible one here
    assert rows["wacc"].verdict == DEFENSIBLE
    assert rows["wacc"].required > MIN_CREDIBLE_WACC


def test_verdicts_track_the_target_rather_than_telling_a_fixed_story():
    """At a cheap target the demanding routes become defensible -- or unreachable.

    Terminal growth cannot get the value down to $60 even at 0% (the base is worth
    $103 there), so that driver is correctly reported as unreachable rather than
    given a spurious required value.
    """
    rows = {r.key: r for r in break_even({}, 60.0)}

    assert rows["year_5_margin"].required == pytest.approx(0.208, abs=0.01)
    assert rows["year_5_margin"].verdict == DEFENSIBLE
    assert rows["wacc"].verdict == DEFENSIBLE          # a high WACC is fine here

    for key in ("terminal_growth", "year_5_growth"):
        assert rows[key].required is None
        assert rows[key].verdict == IMPOSSIBLE
        assert "does not" in rows[key].reason or "no value" in rows[key].reason


# --- the recommendation -------------------------------------------------------

def _wv(cut_a, cut_b):
    bear = dict(year_1_growth=0.25, year_5_growth=0.05, year_5_margin=0.45,
                wacc=0.12, terminal_growth=0.02)
    bull = dict(year_1_growth=0.75, year_5_growth=0.25, year_5_margin=0.65,
                wacc=0.09, terminal_growth=0.04)
    p_bear, p_base, p_bull = probability_split(cut_a, cut_b)
    return weighted_valuation({}, [("Bear", p_bear, bear), ("Base", p_base, {}),
                                   ("Bull", p_bull, bull)])


def test_disagreement_forces_low_conviction_and_explains_itself():
    """At defaults the mean says HOLD and the mass says SELL.

    The honest answer is the more cautious verdict at low conviction, plus the
    reason -- not a confident HOLD resting on one fat tail.
    """
    rec = recommend(_wv(25, 75), 0.15, -0.15)
    assert rec.mean_verdict == "HOLD"
    assert rec.mass_verdict == "SELL"
    assert rec.verdict == "SELL"
    assert rec.conviction == "low"
    assert rec.disagreement and "Bull" in rec.disagreement
    assert "treat the mean with caution" in rec.disagreement


def test_agreement_without_a_straddle_gives_high_conviction():
    """All probability on the bull case: nothing weighted sits below the price."""
    rec = recommend(_wv(0, 0), 0.15, -0.15)
    assert rec.verdict == "BUY"
    assert rec.conviction == "high"
    assert not rec.straddles_price
    assert rec.disagreement is None

    rec = recommend(_wv(100, 100), 0.15, -0.15)       # all on bear
    assert rec.verdict == "SELL" and rec.conviction == "high"


def test_zero_probability_cases_do_not_widen_the_range():
    """A case the analyst has ruled out must not deny them high conviction."""
    rec = recommend(_wv(0, 0), 0.15, -0.15)
    bull_only = [s for s in _wv(0, 0).scenarios if s.probability > 0]
    assert len(bull_only) == 1
    assert rec.range_lo == pytest.approx(rec.range_hi)


def test_mass_thresholds():
    from dcf import MASS_BUY, MASS_SELL
    assert MASS_SELL < 0.5 < MASS_BUY
    # a split that puts most weight on the bull case flips the mass verdict
    assert recommend(_wv(5, 30), 0.15, -0.15).mass_verdict == "BUY"
    assert recommend(_wv(25, 75), 0.15, -0.15).mass_verdict == "SELL"


def test_recommendation_reports_the_mass_below_the_price():
    wv = _wv(25, 75)
    rec = recommend(wv, 0.15, -0.15)
    assert rec.mass_below == pytest.approx(1 - wv.probability_above_price)
    assert rec.mass_below == pytest.approx(0.75)


# --- complete cases must bypass the override merge ---

from dcf import weighted_valuation_from_cases  # noqa: E402

COMPLETE = dict(
    year_1_growth=0.25, year_5_growth=0.05, growth_rates=None,
    year_1_margin=0.60, year_5_margin=0.45, operating_margins=None,
    tax_rate=0.15, net_capex_pct=0.015, nwc_pct_of_growth=0.10,
    wacc=0.12, terminal_growth=0.02, horizon=10,
)


def test_merging_a_complete_case_is_order_dependent():
    """Why `weighted_valuation_from_cases` exists, pinned as a fact.

    A complete case always carries both `operating_margins` (None in taper mode)
    and `year_5_margin`. Pushing that through `_apply_axis` gives a different
    answer depending on which key lands first, and neither matches the direct
    call -- applying `year_5_margin` at all materialises a margin list, which is
    not what the taper path means.
    """
    def merged(order):
        assumptions = {}
        for key in order:
            assumptions = _apply_axis(assumptions, key, COMPLETE[key])
        return run_dcf(**assumptions).value_per_share

    keys = list(COMPLETE)
    margin_first = (["year_5_margin"]
                    + [k for k in keys if k != "year_5_margin"])
    list_first = (["operating_margins"]
                  + [k for k in keys if k != "operating_margins"])

    direct = run_dcf(**COMPLETE).value_per_share
    assert merged(margin_first) != pytest.approx(merged(list_first), abs=0.01)
    assert merged(margin_first) != pytest.approx(direct, abs=0.01)
    assert merged(list_first) != pytest.approx(direct, abs=0.01)


def test_from_cases_matches_a_direct_call_for_every_case():
    """The order-independent reading: hand the dict straight to run_dcf."""
    base = dict(COMPLETE, year_1_growth=0.50, year_5_growth=0.15,
                year_1_margin=0.624, year_5_margin=0.55, wacc=0.10,
                terminal_growth=0.03)
    bull = dict(base, year_1_growth=0.75, year_5_growth=0.25,
                year_5_margin=0.65, wacc=0.09, terminal_growth=0.04, horizon=15)

    wv = weighted_valuation_from_cases([
        ("Bear", 0.25, COMPLETE), ("Base", 0.50, base), ("Bull", 0.25, bull)])
    expected = {"Bear": COMPLETE, "Base": base, "Bull": bull}
    for s in wv.scenarios:
        assert s.result.value_per_share == pytest.approx(
            run_dcf(**expected[s.name]).value_per_share
        )
    assert wv.weighted_value == pytest.approx(
        sum(s.weight * s.result.value_per_share for s in wv.scenarios)
    )


def test_cases_may_differ_structurally_not_just_in_the_five_drivers():
    """The point of independent cases: a different horizon, tax rate, capex."""
    lean = dict(COMPLETE, horizon=7, tax_rate=0.28, net_capex_pct=0.08)
    wv = weighted_valuation_from_cases([
        ("Bear", 0.50, lean), ("Base", 0.50, COMPLETE), ("Bull", 0.0, COMPLETE)])
    assert len(run_dcf(**lean).rows) == 7
    assert len(run_dcf(**COMPLETE).rows) == 10
    assert wv.scenarios[0].result.value_per_share < wv.scenarios[1].result.value_per_share


def test_per_year_case_keeps_its_explicit_margin_list():
    """A per-year case must use its list verbatim, not a rebuilt taper."""
    explicit = [0.62, 0.58, 0.54, 0.50, 0.46]
    per_year = dict(COMPLETE, operating_margins=explicit)
    result = weighted_valuation_from_cases(
        [("Bear", 1.0, per_year)]).scenarios[0].result
    assert [row.operating_margin for row in result.rows[:5]] == pytest.approx(explicit)
    # and beyond year 5 it holds at the year-5 level
    assert result.rows[5].operating_margin == pytest.approx(explicit[4])


def test_solver_is_still_exact_at_sixty_iterations():
    """The iteration cut from 200 must not cost precision."""
    for row in break_even({}, 180.0):
        if row.required is None:
            continue
        got = run_dcf(**_apply_axis({}, row.key, row.required)).value_per_share
        assert got == pytest.approx(180.0, abs=0.01), row.label


# --- validation: refuse to value, or value and say why it is suspect ---

from dcf import (  # noqa: E402
    HIGH_TERMINAL_MULTIPLE, MAX_TERMINAL_MULTIPLE, ModelWarning,
)


def _codes(**kwargs):
    return {w.code for w in run_dcf(**kwargs).warnings}


def _wacc_for_multiple(multiple, terminal_growth=0.03):
    """The WACC that produces exactly this terminal multiple."""
    return terminal_growth + (1 + terminal_growth) / multiple


def test_the_defaults_raise_nothing_at_all():
    """The test that stops this becoming noise.

    A validation layer that fires on the opening screen teaches people to ignore it.
    Checked for the left pane and all three scenario cases.
    """
    assert run_dcf().warnings == []
    for kwargs in (
        dict(wacc=0.12, terminal_growth=0.02, year_5_margin=0.45),   # Bear default
        dict(wacc=0.09, terminal_growth=0.04, year_5_margin=0.65),   # Bull default
    ):
        assert run_dcf(**kwargs).warnings == [], kwargs


def test_terminal_multiple_blocks_above_its_cap_and_not_below():
    """The check the strict WACC > g inequality misses.

    At WACC 4.0% against terminal 3.9% -- both reachable on the sliders -- the
    multiple is 1,039x and the model used to report $10,060/share.
    """
    just_over = _wacc_for_multiple(MAX_TERMINAL_MULTIPLE + 2)
    just_under = _wacc_for_multiple(MAX_TERMINAL_MULTIPLE - 2)

    with pytest.raises(ValueError, match="too close to terminal growth"):
        run_dcf(wacc=just_over, terminal_growth=0.03)
    run_dcf(wacc=just_under, terminal_growth=0.03)      # must not raise

    with pytest.raises(ValueError, match=r"1,039"):
        run_dcf(wacc=0.04, terminal_growth=0.039)


def test_a_high_but_allowed_multiple_warns():
    over = _wacc_for_multiple(HIGH_TERMINAL_MULTIPLE + 2)
    under = _wacc_for_multiple(HIGH_TERMINAL_MULTIPLE - 2)
    assert "terminal_multiple" in _codes(wacc=over, terminal_growth=0.03)
    assert "terminal_multiple" not in _codes(wacc=under, terminal_growth=0.03)


def test_terminal_multiple_property_matches_the_formula():
    r = run_dcf(wacc=0.10, terminal_growth=0.03)
    assert r.terminal_multiple == pytest.approx(1.03 / 0.07)
    assert r.terminal_value == pytest.approx(
        r.rows[-1].free_cash_flow * r.terminal_multiple
    )


def test_negative_final_cash_flow_warns_but_still_values():
    """Your call: keep the number, flag it, so a bear case stays in the average."""
    thin = dict(year_1_margin=0.02, year_5_margin=0.02, net_capex_pct=0.20)
    r = run_dcf(**thin)
    assert r.rows[-1].free_cash_flow < 0
    assert r.terminal_value < 0
    assert "negative_terminal_fcf" in {w.code for w in r.warnings}
    assert r.value_per_share < 0                 # still returned, not blocked


def test_implausible_but_computable_inputs_warn_on_their_own_thresholds():
    from dcf import MAX_TERMINAL_GROWTH, MIN_CREDIBLE_WACC, NVDA_GROSS_MARGIN

    # each fires strictly above/below, so a value sitting on the threshold is clean
    assert "terminal_growth_above_gdp" not in _codes(terminal_growth=MAX_TERMINAL_GROWTH)
    assert "terminal_growth_above_gdp" in _codes(terminal_growth=MAX_TERMINAL_GROWTH + 0.001)

    assert "margin_above_gross" not in _codes(
        year_1_margin=NVDA_GROSS_MARGIN, year_5_margin=NVDA_GROSS_MARGIN)
    assert "margin_above_gross" in _codes(
        year_1_margin=NVDA_GROSS_MARGIN + 0.01, year_5_margin=NVDA_GROSS_MARGIN + 0.01)

    assert "wacc_below_floor" not in _codes(wacc=MIN_CREDIBLE_WACC, terminal_growth=0.01)
    assert "wacc_below_floor" in _codes(wacc=MIN_CREDIBLE_WACC - 0.005, terminal_growth=0.01)


def test_warnings_reuse_the_break_even_thresholds():
    """One definition of implausible, not two that can drift apart."""
    from dcf import MAX_TERMINAL_GROWTH, MIN_CREDIBLE_WACC, NVDA_GROSS_MARGIN, break_even

    rows = {r.key: r for r in break_even({}, 180.0)}
    # the same constants drive both the break-even verdicts and the warnings
    assert rows["terminal_growth"].required > MAX_TERMINAL_GROWTH
    assert "terminal_growth_above_gdp" in _codes(
        terminal_growth=rows["terminal_growth"].required)
    assert rows["year_5_margin"].required > NVDA_GROSS_MARGIN
    assert MIN_CREDIBLE_WACC > 0


def test_break_even_still_solves_wacc_after_the_bracket_moved():
    """The bracket had to move from 4.01% to 5%, or this row silently vanishes.

    At a 3% terminal growth, 4.01% is a 102x multiple -- now blocked -- so the solver
    would see a nan at the bracket end and report the whole driver as unreachable.
    """
    from dcf import BREAK_EVEN_DRIVERS, _apply_axis, break_even

    lo = [d for d in BREAK_EVEN_DRIVERS if d[0] == "wacc"][0][2]
    assert lo >= 0.05
    run_dcf(wacc=lo, terminal_growth=0.03)          # the bracket end must be valuable

    row = {r.key: r for r in break_even({}, 180.0)}["wacc"]
    assert row.required is not None, "the WACC break-even row must still solve"
    got = run_dcf(**_apply_axis({}, "wacc", row.required)).value_per_share
    assert got == pytest.approx(180.0, abs=0.01)


def test_sensitivity_grid_dashes_the_newly_blocked_cells():
    """Those cells used to show four-figure values per share."""
    grid = sensitivity_grid("year_5_margin", [0.55], "terminal_growth",
                            [0.01, 0.03, 0.035], wacc=0.04)
    assert grid[0][0] is not None        # 1% terminal growth at a 4% WACC is fine
    assert grid[1][0] is None            # 3.0% -> 103x, blocked
    assert grid[2][0] is None            # 3.5% -> 209x, blocked
