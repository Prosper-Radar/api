"""
Unit tests for app/scoring/engine.py

Run: pytest tests/test_scoring_engine.py -v
"""
import pytest
from datetime import date, timedelta

from app.scoring.engine import (
    ScoreBreakdown,
    ScoringInput,
    compute_score,
    waterfront_score,
    zoning_score,
    price_score,
    lot_size_score,
    population_growth_score,
    traffic_score,
    recency_score,
    PROSPER_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------

class TestWaterfrontScore:
    def test_waterfront_at_zero(self):
        assert waterfront_score(0) == 100.0

    def test_waterfront_one_km(self):
        assert waterfront_score(1_000) == 0.0

    def test_waterfront_500m(self):
        assert waterfront_score(500) == 50.0

    def test_waterfront_clamps_at_zero(self):
        assert waterfront_score(2_000) == 0.0


class TestZoningScore:
    def test_known_high_tier(self):
        assert zoning_score("T6-80") == 100

    def test_known_residential(self):
        assert zoning_score("RU-1") == 10

    def test_case_insensitive(self):
        assert zoning_score("t6-80") == 100

    def test_unknown_zoning_default(self):
        assert zoning_score("UNKNOWN") == 20.0


class TestPriceScore:
    def test_sweet_spot(self):
        score = price_score(40_000_000)
        assert score > 90

    def test_too_cheap_returns_zero(self):
        assert price_score(5_000_000) == 0.0

    def test_too_expensive_returns_zero(self):
        assert price_score(150_000_000) == 0.0

    def test_within_range_is_positive(self):
        assert price_score(25_000_000) > 0


class TestLotSizeScore:
    def test_large_lot_full_score(self):
        assert lot_size_score(50_000) == 100.0

    def test_small_lot_zero(self):
        assert lot_size_score(3_000) == 0.0

    def test_boundary(self):
        assert lot_size_score(5_000) > 0


class TestPopGrowthScore:
    def test_flat_population(self):
        score = population_growth_score(0.0)
        assert score == 20.0

    def test_high_growth(self):
        score = population_growth_score(0.05)
        assert score == 100.0

    def test_decline_clamps_at_zero(self):
        score = population_growth_score(-0.10)
        assert score == 0.0


class TestTrafficScore:
    def test_no_traffic(self):
        assert traffic_score(0) == 0.0

    def test_high_traffic(self):
        assert traffic_score(100_000) == 100.0

    def test_mid_traffic(self):
        score = traffic_score(50_000)
        assert abs(score - 50.0) < 0.1


class TestRecencyScore:
    def test_no_sale_date_neutral(self):
        assert recency_score(None) == 50.0

    def test_very_old_sale_max(self):
        old_date = date.today() - timedelta(days=365 * 15)
        assert recency_score(old_date) == 100.0

    def test_recent_sale_low(self):
        recent = date.today() - timedelta(days=30)
        score = recency_score(recent)
        assert score < 5.0


# ---------------------------------------------------------------------------
# Engine integration — full compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:
    def _base_input(self, **kwargs) -> ScoringInput:
        defaults = dict(
            distance_to_water_m=500.0,
            zoning_code="T6-36",
            land_value=35_000_000,
            lot_size_sqft=25_000.0,
            population_growth_rate=0.03,
            aadt=60_000,
            last_sale_date=date(2010, 6, 1),
        )
        defaults.update(kwargs)
        return ScoringInput(**defaults)

    def test_returns_score_breakdown(self):
        result = compute_score(self._base_input())
        assert isinstance(result, ScoreBreakdown)

    def test_total_in_range(self):
        result = compute_score(self._base_input())
        assert 0.0 <= result.total <= 100.0

    def test_tier_a_high_score(self):
        result = compute_score(self._base_input(distance_to_water_m=0))
        assert result.tier == "A"
        assert result.total >= 70

    def test_tier_c_bad_parcel(self):
        result = compute_score(self._base_input(
            distance_to_water_m=3_000,
            zoning_code="RU-1",
            land_value=1_000_000,    # too cheap → 0
            lot_size_sqft=1_000,     # too small → 0
            population_growth_rate=-0.02,
            aadt=500,
        ))
        assert result.tier == "C"

    def test_weights_renormalise_when_water_missing(self):
        """Score with no water data should still produce a valid total."""
        result_with = compute_score(self._base_input(distance_to_water_m=100.0))
        result_without = compute_score(self._base_input(distance_to_water_m=None))

        assert result_without.waterfront is None
        assert "waterfront" in result_without.missing_metrics
        assert 0.0 <= result_without.total <= 100.0

    def test_weights_renormalise_when_all_optional_missing(self):
        """No water, no census, no FDOT — should still score gracefully."""
        result = compute_score(self._base_input(
            distance_to_water_m=None,
            population_growth_rate=None,
            aadt=None,
        ))
        assert len(result.missing_metrics) == 3
        assert 0.0 <= result.total <= 100.0
        # Active weight sum (zoning+price+lot+recency) = 0.20+0.15+0.10+0.07 = 0.52

    def test_weights_sum_check(self):
        """All declared weights must sum to exactly 1.0."""
        total = sum(PROSPER_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9
