"""
Sprint 2 unit tests — assembly + skiptrace + email alerts
Run: pytest tests/test_sprint2.py -v
"""
import pytest
from app.services.assembly import normalize_owner
from app.services.skiptrace import _detect_entity_type, _parse_date
from app.services.email_alerts import _render_html, _score_bar, _tier_color


# ---------------------------------------------------------------------------
# normalize_owner
# ---------------------------------------------------------------------------

class TestNormalizeOwner:
    def test_strips_llc(self):
        assert normalize_owner("BRICKELL LAND LLC") == "BRICKELL LAND"

    def test_strips_dotted_llc(self):
        assert normalize_owner("BRICKELL LAND L.L.C.") == "BRICKELL LAND"

    def test_strips_inc(self):
        assert normalize_owner("MIAMI TOWER INC.") == "MIAMI TOWER"

    def test_strips_trust(self):
        assert normalize_owner("JOHN SMITH REVOCABLE TRUST") == "JOHN SMITH"

    def test_collapses_whitespace(self):
        result = normalize_owner("  SMITH   JOHN  LLC  ")
        assert "  " not in result
        assert result == result.strip()

    def test_empty_returns_empty(self):
        assert normalize_owner("") == ""

    def test_individual_unchanged(self):
        result = normalize_owner("JOHN DOE")
        assert result == "JOHN DOE"

    def test_same_entity_different_suffix(self):
        """Both representations should produce the same normalised name."""
        a = normalize_owner("PROSPER HOLDINGS LLC")
        b = normalize_owner("PROSPER HOLDINGS L.L.C.")
        assert a == b


# ---------------------------------------------------------------------------
# _detect_entity_type
# ---------------------------------------------------------------------------

class TestDetectEntityType:
    def test_llc(self):
        assert _detect_entity_type("BRICKELL LAND LLC") == "LLC"

    def test_corp(self):
        assert _detect_entity_type("MIAMI CORP INC") in ("CORP", "INC")

    def test_individual(self):
        assert _detect_entity_type("JOHN DOE") == "INDIVIDUAL"

    def test_trust(self):
        assert _detect_entity_type("FAMILY TRUST") == "TRUST"


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_slash_format(self):
        from datetime import date
        assert _parse_date("01/15/2020") == date(2020, 1, 15)

    def test_iso_format(self):
        from datetime import date
        assert _parse_date("2020-01-15") == date(2020, 1, 15)

    def test_none_input(self):
        assert _parse_date(None) is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# email_alerts helpers
# ---------------------------------------------------------------------------

class TestEmailHelpers:
    def test_tier_color_a(self):
        assert _tier_color("A") == "#10b981"

    def test_tier_color_b(self):
        assert _tier_color("B") == "#f59e0b"

    def test_tier_color_c(self):
        assert _tier_color("C") == "#6b7280"

    def test_score_bar_produces_html(self):
        html = _score_bar(75.0)
        assert "<div" in html
        assert "75%" in html

    def test_score_bar_clamps_over_100(self):
        html = _score_bar(150.0)
        assert "100%" in html

    def test_score_bar_clamps_below_0(self):
        html = _score_bar(-10.0)
        assert "0%" in html

    def test_render_html_contains_address(self):
        parcel = {
            "id": "abc-123",
            "address": "123 Brickell Ave",
            "county": "miami-dade",
            "owner_name": "SMITH LLC",
            "land_value": 25_000_000,
            "lot_size_sqft": 15_000,
            "zoning_code": "T6-36",
        }
        score = {
            "tier": "A",
            "total": 82.5,
            "scores": {
                "waterfront": 90.0,
                "zoning": 85.0,
                "price_range": 75.0,
                "lot_size": 60.0,
                "population_growth": None,
                "traffic": None,
                "recency": 70.0,
            },
        }
        html = _render_html(parcel, score)
        assert "123 Brickell Ave" in html
        assert "Tier A" in html
        assert "82" in html  # total score

    def test_render_html_skips_none_metrics(self):
        parcel = {
            "id": "xyz",
            "address": "555 Miami St",
            "county": "broward",
            "owner_name": "TEST",
            "land_value": 10_000_000,
            "lot_size_sqft": 5_000,
            "zoning_code": "GU",
        }
        score = {
            "tier": "B",
            "total": 55.0,
            "scores": {
                "waterfront": None,
                "zoning": 50.0,
                "price_range": 60.0,
                "lot_size": 40.0,
                "population_growth": None,
                "traffic": None,
                "recency": 55.0,
            },
        }
        html = _render_html(parcel, score)
        # None metrics should not appear as rows
        assert "Waterfront" not in html
        assert "Pop. growth" not in html
        # Present metrics should appear
        assert "Zoning" in html

    def test_render_html_with_assembly(self):
        parcel = {"id": "p1", "address": "100 Biscayne", "county": "miami-dade",
                  "owner_name": "X LLC", "land_value": 50_000_000,
                  "lot_size_sqft": 30_000, "zoning_code": "T6-80"}
        score = {"tier": "A", "total": 90.0, "scores": {
            "waterfront": 95.0, "zoning": 100.0, "price_range": 80.0,
            "lot_size": 100.0, "population_growth": None, "traffic": None, "recency": 80.0}}
        assembly = {"parcel_count": 3, "total_land_value": 120_000_000}
        html = _render_html(parcel, score, assembly=assembly)
        assert "Assembled Site" in html
        assert "3 contiguous" in html
