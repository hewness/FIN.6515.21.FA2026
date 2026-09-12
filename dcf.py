"""Discounted cash flow model.

Pure valuation math -- no UI imports, so it can be tested on its own.
All money figures are in billions of USD unless noted; per-share figures are in dollars.
"""

from dataclasses import asdict, dataclass, field

# Terminal value is FCF x (1 + g) / (WACC - g), and that multiple is what misbehaves
# when WACC closes on g. Guarding the multiple rather than the raw spread is deliberate:
# a 1pp spread is harmless at a 20% WACC and ruinous at 4%, so a spread rule would block
# sane inputs and wave through mad ones. At WACC 4.0% against terminal 3.9% -- both
# reachable on the sliders -- the multiple is 1,039x and the model reports $10,060/share.
MAX_TERMINAL_MULTIPLE = 100.0      # beyond this it is arithmetic, not a valuation
HIGH_TERMINAL_MULTIPLE = 40.0      # beyond this, worth saying out loud

# Year 1 is close to known -- Q1 FY2027 is banked and Q2 is guided -- so the Year-1
# margin is an observation, not a forecast. FY2026's full-year 60.4% is NOT the figure
# to use: it is depressed by a gross-margin dip to 71.1% against 75.0% the year before.
# Q1 FY2027 came in at 74.9% gross / 65.6% operating, and Q2 guidance (GM 74.9% +/-50bp,
# opex ~$8.5B on $91.0B revenue) implies 65.6% again. Using FY2026 would carry a one-off
# through all ten forecast years.
DEFAULT_YEAR_1_MARGIN = 0.656   # Ex 2: Q1 FY2027 actual, matched by Q2 FY2027 guidance
DEFAULT_YEAR_5_MARGIN = 0.55    # judgment: compression as custom silicon and AMD arrive

# NVIDIA starting figures ($B except shares and price), from NVIDIA_Exhibits.xlsx,
# compiled 30 July 2026. Valuation date 29 July 2026.
NVDA_DEFAULTS = {
    "revenue": 215.9,        # Ex 1, FY2026 revenue $215,938M
    "cash": 115.5,           # Ex 4/6, ALL non-operating assets -- see the note below
    "debt": 8.47,            # Ex 4, total debt $8,470M
    "shares": 24.22,         # Ex 6, shares outstanding 24.22B
    "current_price": 190.01, # Ex 6, close 29 July 2026
}
# On `cash`: Exhibit 6 backs out enterprise value as market cap less non-operating
# assets of $115.5B, which bundles cash, marketable debt AND equity securities, and
# non-marketable stakes carried at book. Using the same $115.5B here rather than the
# narrower $50.3B (cash + marketable debt) is deliberate: it makes this model's
# enterprise value and the market-implied enterprise value the same construction, so
# the two are directly comparable. The cost is that illiquid stakes sit at book value.

# CAPM inputs, all from Ex 6. Every WACC default in the app is built from these rather
# than typed as a literal, so the three cases cannot drift from the stated beta range.
RISK_FREE = 0.047               # Ex 6, 10-year US Treasury
EQUITY_RISK_PREMIUM = 0.0423    # Ex 6, implied ERP
# Ex 6 gives two betas. The 5-year regression beta is 2.21, which is how the stock has
# actually traded but bakes in a historic run; the bottom-up semiconductor beta of
# 1.35-1.75 is estimated from the industry and is the standard choice for exactly that
# reason. Bull / Base / Bear take the low / mid / high end.
BOTTOM_UP_BETA = (1.35, 1.55, 1.75)
CONSENSUS_TARGET = 302.83       # Ex 6, mean price target across 61 analysts


def capm_wacc(beta: float) -> float:
    """Risk-free + beta x equity risk premium, rounded to the WACC slider's 0.25% step."""
    return round((RISK_FREE + beta * EQUITY_RISK_PREMIUM) * 400) / 400


@dataclass
class ModelWarning:
    """Something worth saying about a result that the model could still compute.

    Carries a `code` as well as prose so tests and callers key off behaviour rather
    than wording.
    """
    code: str
    message: str


@dataclass
class YearRow:
    """One projected year of the forecast."""
    year: int
    growth_rate: float
    revenue: float
    operating_margin: float
    operating_income: float
    nopat: float
    net_capex: float
    change_in_nwc: float
    free_cash_flow: float
    discount_factor: float
    pv_of_fcf: float


@dataclass
class DCFResult:
    rows: list[YearRow]
    pv_of_forecast: float      # sum of discounted FCF over the horizon
    terminal_value: float      # undiscounted terminal value at the horizon
    pv_of_terminal: float      # terminal value discounted back to today
    enterprise_value: float
    cash: float
    debt: float
    equity_value: float
    shares: float
    value_per_share: float
    current_price: float
    upside: float              # fraction, e.g. 0.25 == 25% upside
    wacc: float                # the discount rate this result was built with
    terminal_growth: float     # the long-run rate feeding the Gordon Growth formula
    warnings: list[ModelWarning] = field(default_factory=list)

    @property
    def terminal_multiple(self) -> float:
        """(1 + g) / (WACC - g) -- what the final year's cash flow is capitalised at."""
        spread = self.wacc - self.terminal_growth
        return (1 + self.terminal_growth) / spread if spread > 0 else float("inf")

    @property
    def net_debt(self) -> float:
        """Debt less cash. Negative means the company holds net cash."""
        return self.debt - self.cash

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(value: float) -> float:
    """Strip binary float noise from a rate.

    The same assumption can arrive by two routes -- tapered between two endpoints,
    or handed over as an explicit per-year list -- and those routes disagree in the
    last bits (0.6055 vs 0.6054999999999999). That is invisible in the arithmetic
    but not on screen: at one decimal place the two render as 60.6% and 60.5%, so
    identical forecasts would display different margins depending on the input mode.
    Ten decimal places is far finer than any real assumption and normalises both.
    """
    return round(value, 10)


def _taper_1_to_5(first: float, fifth: float, year: int) -> float:
    """Linear glide from the year-1 value to the year-5 value."""
    return first + (fifth - first) * ((year - 1) / 4)


def _years_1_to_5(first: float, fifth: float, explicit: list[float] | None,
                  year: int) -> float:
    """Value for a year in 1-5, taken verbatim when the caller supplied a list."""
    if explicit is not None:
        return _clean(explicit[year - 1])
    return _clean(_taper_1_to_5(first, fifth, year))


def growth_schedule(
    year_1_growth: float,
    year_5_growth: float,
    terminal_growth: float,
    horizon: int,
    explicit: list[float] | None = None,
) -> list[float]:
    """Revenue growth rate for each forecast year.

    Years 1-5 either glide linearly from `year_1_growth` to `year_5_growth`, or are
    taken verbatim from `explicit` (a 5-element list). Any years beyond that glide
    from the year-5 rate to `terminal_growth`, so the final forecast year lands on
    the long-run rate and the terminal value formula does not absorb a sudden drop.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1 year")
    if explicit is not None and len(explicit) != 5:
        raise ValueError("explicit growth rates must cover exactly years 1-5")

    fifth = explicit[4] if explicit is not None else year_5_growth

    rates = []
    for year in range(1, horizon + 1):
        if year <= 5:
            rates.append(_years_1_to_5(year_1_growth, year_5_growth, explicit, year))
        else:
            # Interpolate across the remaining steps between year 5 and the horizon.
            fraction = (year - 5) / (horizon - 5)
            rates.append(_clean(fifth + (terminal_growth - fifth) * fraction))
    return rates


def margin_schedule(
    year_1_margin: float,
    year_5_margin: float,
    horizon: int,
    explicit: list[float] | None = None,
) -> list[float]:
    """Operating margin for each forecast year.

    Years 1-5 glide from `year_1_margin` to `year_5_margin`, or come verbatim from
    `explicit`. Beyond year 5 the margin holds flat at the year-5 level: unlike
    growth, a margin has no natural long-run anchor to converge on, so holding it
    is the neutral assumption.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1 year")
    if explicit is not None and len(explicit) != 5:
        raise ValueError("explicit operating margins must cover exactly years 1-5")

    fifth = explicit[4] if explicit is not None else year_5_margin

    margins = []
    for year in range(1, horizon + 1):
        if year <= 5:
            margins.append(_years_1_to_5(year_1_margin, year_5_margin, explicit, year))
        else:
            margins.append(_clean(fifth))
    return margins


def run_dcf(
    revenue: float = NVDA_DEFAULTS["revenue"],
    year_1_growth: float = 0.8225,   # Ex 6: consensus FY2027 revenue $393.6B
    year_5_growth: float = 0.0025,   # lands FY2031 at 78% of Ex 8's 2030 accelerator TAM
    growth_rates: list[float] | None = None,
    year_1_margin: float = DEFAULT_YEAR_1_MARGIN,
    year_5_margin: float = DEFAULT_YEAR_5_MARGIN,
    operating_margins: list[float] | None = None,
    terminal_growth: float = 0.03,
    tax_rate: float = 0.17,          # Ex 2: guided FY2027 effective rate 16-18%
    net_capex_pct: float = 0.015,    # Ex 5: (capex 6,042 - D&A 2,843) / revenue 215,938
    nwc_pct_of_growth: float = 0.128,  # calibrated to FY2026 actual FCF -- see note below
    wacc: float = 0.1125,            # CAPM at the mid bottom-up beta of 1.55
    horizon: int = 10,
    cash: float = NVDA_DEFAULTS["cash"],
    debt: float = NVDA_DEFAULTS["debt"],
    shares: float = NVDA_DEFAULTS["shares"],
    current_price: float = NVDA_DEFAULTS["current_price"],
) -> DCFResult:
    """Value the company and return the full year-by-year build-up.

    Growth, margin, tax and WACC inputs are decimals (0.10 == 10%). Pass
    `growth_rates` / `operating_margins` (5-element lists) to set years 1-5
    directly instead of tapering between a year-1 and year-5 value.
    """
    if wacc <= terminal_growth:
        raise ValueError(
            f"WACC ({wacc:.1%}) must exceed terminal growth ({terminal_growth:.1%}); "
            "otherwise the terminal value is infinite or negative."
        )
    multiple = (1 + terminal_growth) / (wacc - terminal_growth)
    if multiple > MAX_TERMINAL_MULTIPLE:
        raise ValueError(
            f"WACC ({wacc:.2%}) is too close to terminal growth "
            f"({terminal_growth:.2%}): the terminal value would be "
            f"{multiple:,.0f}\u00d7 the final year's cash flow. Past about "
            f"{MAX_TERMINAL_MULTIPLE:,.0f}\u00d7 the figure is arithmetic rather than a "
            "valuation \u2014 widen the gap between the two."
        )
    if shares <= 0:
        raise ValueError("shares outstanding must be positive")

    rates = growth_schedule(year_1_growth, year_5_growth, terminal_growth,
                            horizon, growth_rates)
    margins = margin_schedule(year_1_margin, year_5_margin, horizon, operating_margins)

    rows: list[YearRow] = []
    prior_revenue = revenue
    for year, (growth, margin) in enumerate(zip(rates, margins), start=1):
        rev = prior_revenue * (1 + growth)
        operating_income = rev * margin
        nopat = operating_income * (1 - tax_rate)
        net_capex = rev * net_capex_pct
        # Working capital is funded out of *incremental* revenue, so it fades to
        # nothing as growth slows -- which is what the perpetuity below assumes.
        # Working capital is absorbed by *incremental* revenue, not by the level of it.
        # The 12.8% default is calibrated rather than quoted: Ex 5 reports "working
        # capital absorption 19.3%", but that is computed on a different basis than this
        # model uses. Solving instead for the figure that reproduces FY2026 actual free
        # cash flow -- NOPAT 110,699 less net capex 3,199 less X = FCF 96,575 -- gives
        # X = 10,925 on revenue growth of 85,441, i.e. 12.8%. At that value the model
        # returns FY2026 FCF of $96.60B against an actual $96.58B.
        change_in_nwc = (rev - prior_revenue) * nwc_pct_of_growth
        fcf = nopat - net_capex - change_in_nwc
        discount_factor = 1 / (1 + wacc) ** year

        rows.append(
            YearRow(
                year=year,
                growth_rate=growth,
                revenue=rev,
                operating_margin=margin,
                operating_income=operating_income,
                nopat=nopat,
                net_capex=net_capex,
                change_in_nwc=change_in_nwc,
                free_cash_flow=fcf,
                discount_factor=discount_factor,
                pv_of_fcf=fcf * discount_factor,
            )
        )
        prior_revenue = rev

    pv_of_forecast = sum(r.pv_of_fcf for r in rows)

    # Gordon growth: the year after the horizon, growing forever at terminal_growth.
    final_fcf = rows[-1].free_cash_flow
    terminal_value = final_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_of_terminal = terminal_value * rows[-1].discount_factor

    enterprise_value = pv_of_forecast + pv_of_terminal
    equity_value = enterprise_value + cash - debt
    value_per_share = equity_value / shares
    upside = (value_per_share / current_price - 1) if current_price > 0 else 0.0

    return DCFResult(
        rows=rows,
        pv_of_forecast=pv_of_forecast,
        terminal_value=terminal_value,
        pv_of_terminal=pv_of_terminal,
        enterprise_value=enterprise_value,
        cash=cash,
        debt=debt,
        equity_value=equity_value,
        shares=shares,
        value_per_share=value_per_share,
        current_price=current_price,
        upside=upside,
        wacc=wacc,
        terminal_growth=terminal_growth,
        warnings=_validate(rows, wacc, terminal_growth),
    )


def apply_year_5_margin(assumptions: dict, margin: float) -> dict:
    """Move the Year-5 margin, leaving years 1-4 exactly where they were.

    Two things make this fiddlier than a keyword assignment:

    1. An explicit `operating_margins` list wins over `year_5_margin` inside
       `run_dcf`, so in per-year mode setting the keyword alone does nothing --
       a sensitivity axis built that way renders identical columns and looks
       perfectly fine doing it.
    2. In taper mode the Year-5 margin is the taper's *endpoint*, so moving it
       would drag years 2-4 along. That makes the same question ("what if the
       persistent margin were 40%?") get two different answers depending on
       which input mode happens to be selected.

    Both are solved by materialising the first five margins and replacing only
    the fifth, so the axis is a clean single-variable perturbation either way.
    """
    out = dict(assumptions)
    explicit = out.get("operating_margins")
    if explicit is None:
        explicit = [
            _years_1_to_5(out.get("year_1_margin", DEFAULT_YEAR_1_MARGIN),
                          out.get("year_5_margin", DEFAULT_YEAR_5_MARGIN),
                          None, year)
            for year in range(1, 6)
        ]
    out["operating_margins"] = list(explicit[:4]) + [_clean(margin)]
    out.pop("year_5_margin", None)          # the list wins; drop the dead keyword
    return out


def _apply_axis(assumptions: dict, param: str, value: float) -> dict:
    """Put one axis value into the assumptions, however that parameter is set."""
    if param == "year_5_margin":
        return apply_year_5_margin(assumptions, value)
    return {**assumptions, param: value}


def _validate(rows: list[YearRow], wacc: float, terminal_growth: float) -> list[ModelWarning]:
    """Conditions the model can compute through but a reader should know about."""
    found: list[ModelWarning] = []
    multiple = (1 + terminal_growth) / (wacc - terminal_growth)
    final = rows[-1]

    if multiple > HIGH_TERMINAL_MULTIPLE:
        found.append(ModelWarning(
            "terminal_multiple",
            f"The terminal value capitalises the final year's cash flow at "
            f"{multiple:,.0f}\u00d7. Almost all of this valuation rests on that one "
            f"multiple rather than on the years you projected.",
        ))
    if final.free_cash_flow < 0:
        found.append(ModelWarning(
            "negative_terminal_fcf",
            f"The final year's free cash flow is negative "
            f"(${final.free_cash_flow:,.1f}B), so the terminal value is a negative "
            f"perpetuity. The per-share figure is arithmetically consistent but has no "
            f"economic meaning \u2014 equity cannot be worth less than nothing.",
        ))
    if terminal_growth > MAX_TERMINAL_GROWTH:
        found.append(ModelWarning(
            "terminal_growth_above_gdp",
            f"Terminal growth of {terminal_growth:.1%} is above long-run nominal GDP "
            f"growth, sustained in perpetuity. That implies the company eventually "
            f"becomes the whole economy.",
        ))
    peak_margin = max(row.operating_margin for row in rows)
    if peak_margin > NVDA_GROSS_MARGIN:
        found.append(ModelWarning(
            "margin_above_gross",
            f"An operating margin of {peak_margin:.1%} exceeds NVIDIA's "
            f"{NVDA_GROSS_MARGIN:.0%} gross margin, which is not possible \u2014 operating "
            f"margin is what remains after costs.",
        ))
    if wacc < MIN_CREDIBLE_WACC:
        found.append(ModelWarning(
            "wacc_below_floor",
            f"A {wacc:.2%} discount rate is hard to defend for a company with "
            f"NVIDIA's customer concentration.",
        ))
    return found


def sensitivity_grid(
    x_param: str,
    x_values: list[float],
    y_param: str,
    y_values: list[float],
    **assumptions,
) -> list[list[DCFResult | None]]:
    """Value the company at every (y, x) pair on the two given axes.

    Rows are `y_values`, columns are `x_values`. A combination the model refuses
    to value -- WACC at or below terminal growth -- comes back as None so the
    caller can render it as an empty cell.
    """
    grid = []
    for y in y_values:
        row = []
        for x in x_values:
            cell = _apply_axis(_apply_axis(assumptions, y_param, y), x_param, x)
            try:
                row.append(run_dcf(**cell))
            except ValueError:
                row.append(None)
        grid.append(row)
    return grid


# --- bear / base / bull scenarios -------------------------------------------

@dataclass
class ScenarioResult:
    """One named case, its probability weight, and what it is worth."""
    name: str
    probability: float              # 0-1 share of the whole, before dropping failures
    weight: float                   # 0-1, renormalised over the valuable cases
    result: DCFResult | None        # None when this case cannot be valued
    error: str | None = None

    @property
    def contribution(self) -> float:
        """This case's share of the weighted value, in dollars per share."""
        return self.weight * self.result.value_per_share if self.result else 0.0


@dataclass
class WeightedValuation:
    scenarios: list[ScenarioResult]
    weighted_value: float
    valued_mass: float              # probability covered by cases that could be valued
    probability_above_price: float
    current_price: float

    @property
    def upside(self) -> float:
        if self.current_price <= 0:
            return 0.0
        return self.weighted_value / self.current_price - 1

    @property
    def all_failed(self) -> bool:
        return self.valued_mass <= 0


def probability_split(cut_a: float, cut_b: float) -> tuple[float, float, float]:
    """Turn two cut points on a 0-100 axis into three probabilities.

    Three probabilities have two degrees of freedom, so two cut points express
    them exactly -- and the three shares sum to 1 by construction, which removes
    any need to validate or normalise what the user entered. `cut_a` past `cut_b`
    is clamped rather than rejected.
    """
    lo, hi = sorted((max(0.0, min(100.0, cut_a)), max(0.0, min(100.0, cut_b))))
    return lo / 100, (hi - lo) / 100, (100 - hi) / 100


def weighted_valuation(
    base_assumptions: dict,
    cases: list[tuple[str, float, dict]],
) -> WeightedValuation:
    """Value each named case and take the probability-weighted average of the VALUES.

    The weighting has to apply to the values, never to the assumptions: the model
    is non-linear in its inputs (1 / (WACC - g) is convex), so averaging the
    assumptions and valuing once gives a materially different -- and wrong --
    answer. At a plausible bear/base/bull spread the two differ by ~47% and
    disagree about whether the stock is cheap.

    A case the model refuses to value is reported with its error and excluded;
    the remaining weights are renormalised and `valued_mass` records how much
    probability the answer actually covers.
    """
    priced = base_assumptions.get("current_price", NVDA_DEFAULTS["current_price"])

    evaluated: list[ScenarioResult] = []
    for name, probability, overrides in cases:
        assumptions = dict(base_assumptions)
        for key, value in overrides.items():
            # Route through _apply_axis so a Year-5 margin override is not silently
            # swallowed by an explicit per-year margin list.
            assumptions = _apply_axis(assumptions, key, value)
        try:
            evaluated.append(
                ScenarioResult(name, probability, 0.0, run_dcf(**assumptions))
            )
        except ValueError as exc:
            evaluated.append(ScenarioResult(name, probability, 0.0, None, str(exc)))

    valued_mass = sum(s.probability for s in evaluated if s.result is not None)
    for s in evaluated:
        s.weight = (s.probability / valued_mass) if (s.result and valued_mass > 0) else 0.0

    return WeightedValuation(
        scenarios=evaluated,
        weighted_value=sum(s.contribution for s in evaluated),
        valued_mass=valued_mass,
        probability_above_price=sum(
            s.probability for s in evaluated
            if s.result and s.result.value_per_share > priced
        ),
        current_price=priced,
    )


# --- break-even framework ---------------------------------------------------
# Damodaran's question: what would the company have to deliver to justify the
# price? Answered by reverse-solving each driver, then judged against thresholds
# that are SUBSTANTIVE rather than "is it inside the slider range" -- every
# required value below sits inside its slider range, so range membership tests
# nothing. Each threshold carries its basis so the judgment is auditable.
# Ex 2: Q1 FY2027 actual 74.9%, Q2 FY2027 guidance 74.9% +/-50bp. NOT FY2026's 71.1%,
# which is the one-off year; the current run-rate is back at 75%.
NVDA_GROSS_MARGIN = 0.75
# Ex 6: the 10-year US Treasury. A perpetual growth rate above the risk-free rate is the
# standard ceiling -- nothing grows faster than the economy forever.
MAX_TERMINAL_GROWTH = RISK_FREE
# Risk-free + ERP at a beta of 1.0. A semiconductor business cannot credibly be less
# risky than the market, so this is the floor the CAPM build-up itself implies.
MIN_CREDIBLE_WACC = round(RISK_FREE + EQUITY_RISK_PREMIUM, 4)
# Ex 8's furthest-out industry total: calendar 2027 forecast ~$1.9T (2025 was ~$795B,
# 2026F $1.51T). Still conservative as a ceiling on FY2036 revenue, which is the year
# this is compared against -- but it is the last year the exhibit sizes. The old 2025
# figure was a full decade adrift of the year it judged, and flagged the base case's
# own growth rate as demanding.
GLOBAL_SEMI_REVENUE = 1900.0

IMPOSSIBLE, DEMANDING, DEFENSIBLE = "impossible", "demanding", "defensible"

# Mass thresholds for the probability reading. Deliberately wider than the mean's
# +/-15%: a majority of probability has to agree before the verdict commits.
MASS_BUY, MASS_SELL = 0.65, 0.35


@dataclass
class BreakEven:
    """What one driver must reach, alone, for the base case to equal the price."""
    key: str
    label: str
    base: float
    required: float | None          # None when the price is unreachable on this driver
    range_lo: float
    range_hi: float
    verdict: str
    reason: str


@dataclass
class Recommendation:
    verdict: str                    # BUY / HOLD / SELL
    conviction: str                 # high / moderate / low
    mean_verdict: str               # what the weighted value alone says
    mass_verdict: str               # what the probability mass alone says
    disagreement: str | None        # set when the two readings conflict
    range_lo: float
    range_hi: float
    straddles_price: bool
    mass_below: float


#: Drivers offered in the break-even table, with the bracket used to solve them.
BREAK_EVEN_DRIVERS = [
    ("year_5_margin", "Year 5 operating margin", 0.0, 0.95),
    ("terminal_growth", "Terminal growth", 0.0, 0.0599),
    ("year_5_growth", "Year 5 revenue growth", -0.10, 0.80),
    ("year_1_growth", "Year 1 revenue growth", 0.0, 2.00),
    # 5%, not 4.01%: at a 3% terminal growth the old lower bound is a 102x multiple,
    # which the block above now rejects -- the solver would see a nan at the bracket
    # end and report the whole WACC row as unreachable.
    ("wacc", "WACC", 0.05, 0.30),
]


def solve_for_target(
    assumptions: dict,
    param: str,
    lo: float,
    hi: float,
    target: float,
    iterations: int = 60,
) -> float | None:
    """Bisect `param` for the value that makes value-per-share equal `target`.

    Returns None when `target` is not bracketed by [lo, hi]. Axis values go in
    through `_apply_axis`, so a Year-5 margin solve is not silently swallowed by
    an explicit per-year margin list.

    60 iterations halves the bracket 60 times, which is already past float
    precision; each one costs two valuations, so the old 200 was spending about
    1,400 `run_dcf` calls per driver for nothing.
    """
    def error(x: float) -> float:
        try:
            return run_dcf(**_apply_axis(assumptions, param, x)).value_per_share - target
        except ValueError:
            return float("nan")

    f_lo, f_hi = error(lo), error(hi)
    if f_lo != f_lo or f_hi != f_hi or not (f_lo < 0 < f_hi or f_hi < 0 < f_lo):
        return None

    for _ in range(iterations):
        mid = (lo + hi) / 2
        if error(lo) * error(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def current_setting(assumptions: dict, key: str) -> float:
    """The caller's present setting for a driver, however it was expressed."""
    explicit_margins = assumptions.get("operating_margins")
    explicit_growth = assumptions.get("growth_rates")
    if key == "year_5_margin" and explicit_margins is not None:
        return explicit_margins[4]
    if key == "year_5_growth" and explicit_growth is not None:
        return explicit_growth[4]
    if key == "year_1_growth" and explicit_growth is not None:
        return explicit_growth[0]

    import inspect
    default = inspect.signature(run_dcf).parameters[key].default
    value = assumptions.get(key, default)
    return default if value is None else value


def _judge(key: str, required: float, assumptions: dict) -> tuple[str, str]:
    """Is this required value something a reasonable analyst could believe?"""
    if key == "year_5_margin" and required > NVDA_GROSS_MARGIN:
        return IMPOSSIBLE, (
            "an operating margin cannot exceed the gross margin; NVIDIA's Q1 FY2027 "
            f"gross margin was {NVDA_GROSS_MARGIN:.0%}"
        )
    if key == "terminal_growth" and required > MAX_TERMINAL_GROWTH:
        return IMPOSSIBLE, "above long-run nominal GDP growth, sustained in perpetuity"
    if key == "wacc" and required < MIN_CREDIBLE_WACC:
        return DEMANDING, (
            "a discount rate this low is hard to defend given NVIDIA's customer "
            "concentration"
        )
    if key in ("year_1_growth", "year_5_growth"):
        implied = run_dcf(**_apply_axis(assumptions, key, required)).rows[-1].revenue
        if implied > GLOBAL_SEMI_REVENUE:
            return DEMANDING, (
                f"implies ${implied:,.0f}B of final-year revenue, more than the entire "
                f"global semiconductor industry is forecast to reach in 2027 "
                f"(${GLOBAL_SEMI_REVENUE:,.0f}B)"
            )
    return DEFENSIBLE, "within the range of reasonable disagreement"


def break_even(assumptions: dict, target_price: float) -> list[BreakEven]:
    """What each driver alone must deliver for the base case to equal the price."""
    rows = []
    for key, label, lo, hi in BREAK_EVEN_DRIVERS:
        base = current_setting(assumptions, key)
        required = solve_for_target(assumptions, key, lo, hi, target_price)
        if required is None:
            rows.append(BreakEven(key, label, base, None, lo, hi, IMPOSSIBLE,
                                  "no value of this driver alone reaches the price"))
            continue
        verdict, reason = _judge(key, required, assumptions)
        rows.append(BreakEven(key, label, base, required, lo, hi, verdict, reason))
    return rows


def recommend(wv: WeightedValuation, buy_above: float, sell_below: float) -> Recommendation:
    """Combine a central estimate and a probability mass into an honest verdict.

    Two readings, reported together rather than blended. A blended score would
    hide the case where the weighted mean sits near the price only because one
    fat tail drags it there -- and that conflict is the most informative thing
    the panel can say.
    """
    # Only cases you actually give weight to define the range. A scenario parked at
    # zero probability is still valued, and letting it widen the range would keep
    # reporting a straddle -- and so deny high conviction -- for a view the analyst
    # has explicitly ruled out.
    values = [s.result.value_per_share for s in wv.scenarios
              if s.result and s.probability > 0]
    lo, hi = (min(values), max(values)) if values else (0.0, 0.0)
    price = wv.current_price

    mean_verdict = ("BUY" if wv.upside > buy_above else
                    "SELL" if wv.upside < sell_below else "HOLD")
    above = wv.probability_above_price
    mass_verdict = ("BUY" if above >= MASS_BUY else
                    "SELL" if above <= MASS_SELL else "HOLD")

    straddles = lo < price < hi
    caution = {"SELL": 0, "HOLD": 1, "BUY": 2}
    disagreement = None

    if mean_verdict == mass_verdict:
        verdict = mean_verdict
        conviction = "high" if not straddles else "moderate"
    else:
        verdict = min((mean_verdict, mass_verdict), key=lambda v: caution[v])
        conviction = "low"
        driver = max((s for s in wv.scenarios if s.result),
                     key=lambda s: s.contribution, default=None)
        if driver and wv.weighted_value:
            share = driver.contribution / wv.weighted_value
            disagreement = (
                f"Your weighted average (${wv.weighted_value:,.0f}) reads {mean_verdict}, "
                f"but {1 - above:.0%} of your probability sits below the price. The "
                f"average is carried by the {driver.name} case: {share:.0%} of it from "
                f"{driver.probability:.0%} of the probability. The mean and the mass "
                f"disagree, so treat the mean with caution."
            )
        else:
            disagreement = (f"The weighted average reads {mean_verdict} but the "
                            f"probability mass reads {mass_verdict}.")

    return Recommendation(verdict, conviction, mean_verdict, mass_verdict, disagreement,
                          lo, hi, straddles, 1 - above)


def weighted_valuation_from_cases(
    cases: list[tuple[str, float, dict]],
) -> WeightedValuation:
    """Weight three *complete, independent* cases rather than overrides on a base.

    `weighted_valuation` merges overrides through `_apply_axis`, which is right for
    the break-even solver -- it genuinely perturbs one key at a time -- but wrong
    here, and silently so. A complete case dict always carries both
    `operating_margins` (None in taper mode) and `year_5_margin`, and routing that
    through the merge gives three different answers depending on order:

        year_5_margin applied first   $45.01
        operating_margins first       $38.99
        run_dcf(**case) directly      $38.16

    Applying `year_5_margin` at all materialises a margin list, which is not what
    the taper path means; and a later `operating_margins: None` wipes that list out.
    Calling `run_dcf` with the case dict is the only order-independent reading, so
    that is what this does.
    """
    priced = NVDA_DEFAULTS["current_price"]
    evaluated: list[ScenarioResult] = []
    for name, probability, assumptions in cases:
        priced = assumptions.get("current_price", priced)
        try:
            evaluated.append(
                ScenarioResult(name, probability, 0.0, run_dcf(**assumptions))
            )
        except ValueError as exc:
            evaluated.append(ScenarioResult(name, probability, 0.0, None, str(exc)))

    valued_mass = sum(s.probability for s in evaluated if s.result is not None)
    for s in evaluated:
        s.weight = (s.probability / valued_mass) if (s.result and valued_mass > 0) else 0.0

    return WeightedValuation(
        scenarios=evaluated,
        weighted_value=sum(s.contribution for s in evaluated),
        valued_mass=valued_mass,
        probability_above_price=sum(
            s.probability for s in evaluated
            if s.result and s.result.value_per_share > priced
        ),
        current_price=priced,
    )
