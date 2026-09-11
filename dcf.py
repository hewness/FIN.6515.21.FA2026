"""Discounted cash flow model.

Pure valuation math -- no UI imports, so it can be tested on its own.
All money figures are in billions of USD unless noted; per-share figures are in dollars.
"""

from dataclasses import dataclass, asdict

# NVIDIA starting figures (FY2025 actuals, $B except shares and price).
NVDA_DEFAULTS = {
    "revenue": 130.5,
    "cash": 43.2,
    "debt": 8.5,
    "shares": 24.5,
    "current_price": 180.0,
}


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
    year_1_growth: float = 0.50,
    year_5_growth: float = 0.15,
    growth_rates: list[float] | None = None,
    year_1_margin: float = 0.624,
    year_5_margin: float = 0.55,
    operating_margins: list[float] | None = None,
    terminal_growth: float = 0.03,
    tax_rate: float = 0.15,
    net_capex_pct: float = 0.015,
    nwc_pct_of_growth: float = 0.10,
    wacc: float = 0.10,
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
    )


def sensitivity_grid(
    wacc_values: list[float],
    terminal_values: list[float],
    **assumptions,
) -> list[list[DCFResult | None]]:
    """Value the company at every (terminal growth, WACC) pair.

    Rows are terminal growth rates, columns are WACCs. A pair where WACC does
    not exceed terminal growth has no finite value; that cell comes back None.
    """
    grid = []
    for g in terminal_values:
        row = []
        for w in wacc_values:
            try:
                row.append(run_dcf(wacc=w, terminal_growth=g, **assumptions))
            except ValueError:
                row.append(None)
        grid.append(row)
    return grid
