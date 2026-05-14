from datetime import date
from dataclasses import dataclass
from typing import Optional


PROSPER_WEIGHTS = {
    "waterfront":         0.30,
    "zoning":             0.20,
    "price_range":        0.15,
    "lot_size":           0.10,
    "population_growth":  0.10,
    "traffic":            0.08,
    "sale_recency":       0.07,
}

ZONING_SCORES: dict[str, float] = {
    "T6-80": 100, "T6-60": 90, "T6-36": 80, "T6-24": 70,
    "MXD": 85, "CBD": 90, "BU-2": 60, "GU": 40, "RU-1": 10,
}


@dataclass
class ScoringInput:
    distance_to_water_m: float
    zoning_code: str
    land_value: int
    lot_size_sqft: float
    population_growth_rate: float  # 3-year CAGR as decimal, e.g. 0.032
    aadt: int                       # Annual Average Daily Traffic
    last_sale_date: Optional[date]


@dataclass
class ScoreBreakdown:
    waterfront: float
    zoning: float
    price_range: float
    lot_size: float
    population_growth: float
    traffic: float
    sale_recency: float
    total: float
    tier: str


def waterfront_score(distance_m: float) -> float:
    return max(0.0, 100 - (distance_m / 10))


def zoning_score(code: str) -> float:
    return ZONING_SCORES.get(code.upper(), 20)


def price_score(land_value: int) -> float:
    MIN_VAL = 10_000_000
    SWEET = 40_000_000
    MAX_VAL = 100_000_000

    if land_value < MIN_VAL or land_value > MAX_VAL:
        return 0.0
    distance = abs(land_value - SWEET)
    return max(0.0, 100 - (distance / 600_000))


def lot_size_score(sqft: float) -> float:
    MIN_SQFT = 5_000
    SWEET_SQFT = 40_000
    MAX_SQFT = 500_000

    if sqft < MIN_SQFT:
        return 0.0
    if sqft >= SWEET_SQFT:
        return 100.0
    return (sqft / SWEET_SQFT) * 100


def population_growth_score(cagr: float) -> float:
    # 0% growth = 20, 5% growth = 100
    return min(100.0, max(0.0, cagr * 1600))


def traffic_score(aadt: int) -> float:
    # 100k+ AADT = 100, 0 = 0
    return min(100.0, (aadt / 100_000) * 100)


def recency_score(last_sale: Optional[date]) -> float:
    if last_sale is None:
        return 50.0
    years_ago = (date.today() - last_sale).days / 365
    # 10+ years ago = 100 (stale = negotiable), recent = lower
    return min(100.0, years_ago * 10)


def compute_score(inp: ScoringInput) -> ScoreBreakdown:
    scores = {
        "waterfront":        waterfront_score(inp.distance_to_water_m),
        "zoning":            zoning_score(inp.zoning_code),
        "price_range":       price_score(inp.land_value),
        "lot_size":          lot_size_score(inp.lot_size_sqft),
        "population_growth": population_growth_score(inp.population_growth_rate),
        "traffic":           traffic_score(inp.aadt),
        "sale_recency":      recency_score(inp.last_sale_date),
    }

    total = sum(scores[k] * PROSPER_WEIGHTS[k] for k in PROSPER_WEIGHTS)

    if total >= 70:
        tier = "A"
    elif total >= 45:
        tier = "B"
    else:
        tier = "C"

    return ScoreBreakdown(
        waterfront=round(scores["waterfront"], 2),
        zoning=round(scores["zoning"], 2),
        price_range=round(scores["price_range"], 2),
        lot_size=round(scores["lot_size"], 2),
        population_growth=round(scores["population_growth"], 2),
        traffic=round(scores["traffic"], 2),
        sale_recency=round(scores["sale_recency"], 2),
        total=round(total, 2),
        tier=tier,
    )
