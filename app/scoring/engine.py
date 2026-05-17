from datetime import date
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Weights — must sum to 1.0
# When a metric has no real data its weight is redistributed proportionally.
# ---------------------------------------------------------------------------
PROSPER_WEIGHTS: dict[str, float] = {
    "waterfront":        0.30,
    "zoning":            0.20,
    "price_range":       0.15,
    "lot_size":          0.10,
    "population_growth": 0.10,
    "traffic":           0.08,
    "sale_recency":      0.07,
}

ZONING_SCORES: dict[str, float] = {
    # Miami-Dade transect zones
    "T6-80": 100, "T6-60": 95, "T6-36": 85, "T6-24": 75, "T6-12": 65,
    "T5-O": 60, "T5-L": 55, "T5-R": 50,
    "T4-O": 40, "T4-L": 35, "T4-R": 30,
    # Mixed use / commercial
    "MXD": 85, "CBD": 90,
    "BU-2": 60, "BU-1": 50,
    # Industrial
    "IU-2": 45, "IU-1": 35,
    # Residential / estate
    "GU": 40, "EU-M": 25, "EU-S": 20, "EU-1": 15, "EU-2": 12,
    "RU-1": 10, "RU-2": 8, "RES-1": 5,
    # Hillsborough / generic
    "RM-2": 55, "RM-3": 70, "RM-4": 80,
    "CBD-1": 90,
    "CG": 65, "CN": 45,
}


@dataclass
class ScoringInput:
    """
    All optional data fields accept None to signal "not yet available".
    The engine renormalises weights so missing metrics don't collapse the score.
    """
    # Geographic (PostGIS-derived)
    distance_to_water_m: Optional[float]     # None → waterfront excluded

    # Parcel basics
    zoning_code: str
    land_value: int                          # USD
    lot_size_sqft: float

    # External API data
    population_growth_rate: Optional[float]  # 3-yr CAGR decimal; None → excluded
    aadt: Optional[int]                      # Annual Avg Daily Traffic; None → excluded

    # Transaction history
    last_sale_date: Optional[date]


@dataclass
class ScoreBreakdown:
    waterfront: Optional[float]
    zoning: float
    price_range: float
    lot_size: float
    population_growth: Optional[float]
    traffic: Optional[float]
    sale_recency: float
    total: float
    tier: str
    # flags — tell consumers what was computed vs missing
    missing_metrics: list[str]


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------

def waterfront_score(distance_m: float) -> float:
    """Linear decay: 0m = 100, 1 km = 0. Capped."""
    return max(0.0, 100.0 - distance_m / 10.0)


def zoning_score(code: str) -> float:
    return ZONING_SCORES.get(code.upper().strip(), 20.0)


def price_score(land_value: int) -> float:
    """
    Sweet spot $10–100M, peak at $40M.
    Outside range = 0 (too cheap = too risky / speculative;
    too expensive = Prosper can't close).
    """
    MIN_VAL = 10_000_000
    SWEET   = 40_000_000
    MAX_VAL = 100_000_000
    if land_value < MIN_VAL or land_value > MAX_VAL:
        return 0.0
    return max(0.0, 100.0 - abs(land_value - SWEET) / 600_000.0)


def lot_size_score(sqft: float) -> float:
    """< 5k sqft = discard. Sweet spot ≥ 40k sqft = 100."""
    MIN_SQFT  = 5_000
    SWEET_SQFT = 40_000
    if sqft < MIN_SQFT:
        return 0.0
    if sqft >= SWEET_SQFT:
        return 100.0
    return (sqft / SWEET_SQFT) * 100.0


def population_growth_score(cagr: float) -> float:
    """0% = 20 pts (flat is neutral), 5% = 100 pts."""
    return min(100.0, max(0.0, 20.0 + cagr * 1_600.0))


def traffic_score(aadt: int) -> float:
    """0 AADT = 0, 100k AADT = 100. Linear."""
    return min(100.0, (aadt / 100_000.0) * 100.0)


def recency_score(last_sale) -> float:
    """
    Older sale = more negotiable = higher score.
    No sale date = neutral 50 (could be long-held family land).
    Accepts date objects or ISO-format strings.
    """
    if last_sale is None:
        return 50.0
    if isinstance(last_sale, str):
        try:
            last_sale = date.fromisoformat(last_sale[:10])
        except ValueError:
            return 50.0
    years_ago = (date.today() - last_sale).days / 365.25
    return min(100.0, years_ago * 10.0)


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_score(inp: ScoringInput) -> ScoreBreakdown:
    """
    Compute deal score with dynamic weight renormalisation.
    Metrics with None input are excluded and their weights redistributed.
    """
    available: dict[str, float] = {}
    missing: list[str] = []

    # --- always-present metrics ---
    available["zoning"]       = zoning_score(inp.zoning_code)
    available["price_range"]  = price_score(inp.land_value)
    available["lot_size"]     = lot_size_score(inp.lot_size_sqft)
    available["sale_recency"] = recency_score(inp.last_sale_date)

    # --- conditionally-present metrics ---
    if inp.distance_to_water_m is not None:
        available["waterfront"] = waterfront_score(inp.distance_to_water_m)
    else:
        missing.append("waterfront")

    if inp.population_growth_rate is not None:
        available["population_growth"] = population_growth_score(inp.population_growth_rate)
    else:
        missing.append("population_growth")

    if inp.aadt is not None:
        available["traffic"] = traffic_score(inp.aadt)
    else:
        missing.append("traffic")

    # --- renormalise weights to sum=1 over available metrics ---
    active_weight_sum = sum(PROSPER_WEIGHTS[k] for k in available)
    total = sum(
        available[k] * (PROSPER_WEIGHTS[k] / active_weight_sum)
        for k in available
    )

    if total >= 70:
        tier = "A"
    elif total >= 45:
        tier = "B"
    else:
        tier = "C"

    return ScoreBreakdown(
        waterfront=round(available.get("waterfront"), 2) if "waterfront" in available else None,
        zoning=round(available["zoning"], 2),
        price_range=round(available["price_range"], 2),
        lot_size=round(available["lot_size"], 2),
        population_growth=round(available.get("population_growth"), 2) if "population_growth" in available else None,
        traffic=round(available.get("traffic"), 2) if "traffic" in available else None,
        sale_recency=round(available["sale_recency"], 2),
        total=round(total, 2),
        tier=tier,
        missing_metrics=missing,
    )
