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
    gross_profit: float
    opex: float
    operating_income: float
    nopat: float
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

    def as_dict(self) -> dict:
        return asdict(self)


def growth_schedule(
    year_1_growth: float,
    year_5_growth: float,
    terminal_growth: float,
    horizon: int,
) -> list[float]:
    """Growth rate for each forecast year.

    Years 1-5 glide linearly from `year_1_growth` to `year_5_growth`. Any years
    beyond that glide linearly from `year_5_growth` to `terminal_growth`, so the
    final forecast year lands on the long-run rate and the terminal value formula
    does not have to absorb a sudden drop.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1 year")

    rates = []
    for year in range(1, horizon + 1):
        if year <= 5:
            # Interpolate across the 4 steps between year 1 and year 5.
            fraction = (year - 1) / 4
            rates.append(year_1_growth + (year_5_growth - year_1_growth) * fraction)
        else:
            # Interpolate across the remaining steps between year 5 and the horizon.
            steps = horizon - 5
            fraction = (year - 5) / steps
            rates.append(year_5_growth + (terminal_growth - year_5_growth) * fraction)
    return rates


def run_dcf(
    revenue: float = NVDA_DEFAULTS["revenue"],
    year_1_growth: float = 0.50,
    year_5_growth: float = 0.15,
    terminal_growth: float = 0.03,
    gross_margin: float = 0.75,
    opex_pct: float = 0.25,
    tax_rate: float = 0.15,
    wacc: float = 0.10,
    horizon: int = 10,
    fcf_conversion: float = 0.90,
    cash: float = NVDA_DEFAULTS["cash"],
    debt: float = NVDA_DEFAULTS["debt"],
    shares: float = NVDA_DEFAULTS["shares"],
    current_price: float = NVDA_DEFAULTS["current_price"],
) -> DCFResult:
    """Value the company and return the full year-by-year build-up.

    Growth, margin, tax and WACC inputs are decimals (0.10 == 10%).
    """
    if wacc <= terminal_growth:
        raise ValueError(
            f"WACC ({wacc:.1%}) must exceed terminal growth ({terminal_growth:.1%}); "
            "otherwise the terminal value is infinite or negative."
        )
    if shares <= 0:
        raise ValueError("shares outstanding must be positive")

    rates = growth_schedule(year_1_growth, year_5_growth, terminal_growth, horizon)

    rows: list[YearRow] = []
    prior_revenue = revenue
    for year, growth in enumerate(rates, start=1):
        rev = prior_revenue * (1 + growth)
        gross_profit = rev * gross_margin
        opex = rev * opex_pct
        operating_income = gross_profit - opex
        nopat = operating_income * (1 - tax_rate)
        fcf = nopat * fcf_conversion
        discount_factor = 1 / (1 + wacc) ** year

        rows.append(
            YearRow(
                year=year,
                growth_rate=growth,
                revenue=rev,
                gross_profit=gross_profit,
                opex=opex,
                operating_income=operating_income,
                nopat=nopat,
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
