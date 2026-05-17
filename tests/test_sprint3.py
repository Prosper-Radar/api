"""
Sprint 3 unit tests — Deal Memo PDF
Run: pytest tests/test_sprint3.py -v
"""
import asyncio
import pytest
from app.services.pdf import (
    _fmt_usd,
    _fmt_sqft,
    _tier_color,
    _DealMemoPDF,
    build_deal_memo,
    MODEL_VERSION,
    _GREEN, _AMBER, _RED,
)


class TestFormatters:
    def test_fmt_usd_millions(self):
        assert _fmt_usd(35_000_000) == "$35.0M"

    def test_fmt_usd_thousands(self):
        assert _fmt_usd(500_000) == "$500K"

    def test_fmt_usd_small(self):
        assert _fmt_usd(999) == "$999"

    def test_fmt_usd_none(self):
        assert _fmt_usd(None) == "—"

    def test_fmt_sqft(self):
        assert _fmt_sqft(25000) == "25,000 sqft"

    def test_fmt_sqft_none(self):
        assert _fmt_sqft(None) == "—"


class TestTierColor:
    def test_tier_a_is_green(self):
        assert _tier_color("A") == _GREEN

    def test_tier_b_is_amber(self):
        assert _tier_color("B") == _AMBER

    def test_tier_c_is_red(self):
        assert _tier_color("C") == _RED

    def test_unknown_tier_is_mid(self):
        r, g, b = _tier_color("X")
        assert isinstance(r, int)


class TestDealMemoPDFBuild:
    """Integration test — build a real PDF and check it's valid."""

    def _sample_parcel(self):
        return {
            "id": "abc-123",
            "parcel_id": "01-4138-000-0010",
            "address": "123 Brickell Ave",
            "county": "miami-dade",
            "owner_name": "BRICKELL HOLDINGS LLC",
            "land_value": 35_000_000,
            "lot_size_sqft": 25_000,
            "zoning_code": "T6-36",
            "last_sale_date": "2019-01-15",
            "last_sale_price": 22_000_000,
            "lng": -80.1918,
            "lat": 25.7617,
        }

    def _sample_score(self, tier="A", total=82.5):
        return {
            "tier": tier,
            "total": total,
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

    def test_build_returns_bytes(self):
        result = asyncio.run(build_deal_memo(
            parcel=self._sample_parcel(),
            score=self._sample_score(),
        ))
        assert isinstance(result, bytes)
        assert len(result) > 1000

    def test_pdf_starts_with_pdf_magic(self):
        result = asyncio.run(build_deal_memo(
            parcel=self._sample_parcel(),
            score=self._sample_score(),
        ))
        assert result[:4] == b"%PDF"

    def test_build_with_all_sections(self):
        owner = {
            "entity_type": "LLC",
            "entity_status": "ACTIVE",
            "filing_date": "2015-03-12",
            "registered_agent": "Registered Agents Inc",
            "principal_address": "100 Main St, Miami FL",
            "officers": [
                {"name": "John Smith", "title": "Manager"},
                {"name": "Jane Doe", "title": "Registered Agent"},
            ],
        }
        assembly = {
            "parcel_count": 3,
            "total_land_value": 92_000_000,
            "total_lot_size_sqft": 75_000,
        }
        comps = [
            {
                "address": "456 Brickell Ave",
                "zoning_code": "T6-36",
                "lot_size_sqft": 20000,
                "last_sale_date": "2023-06-01",
                "last_sale_price": 28_000_000,
            }
        ]
        result = asyncio.run(build_deal_memo(
            parcel=self._sample_parcel(),
            score=self._sample_score(),
            owner=owner,
            assembly=assembly,
            comps=comps,
            mapbox_token="",   # no aerial (no token)
        ))
        assert result[:4] == b"%PDF"
        assert len(result) > 2_000  # valid non-empty PDF

    def test_build_tier_c_deal(self):
        result = asyncio.run(build_deal_memo(
            parcel=self._sample_parcel(),
            score=self._sample_score(tier="C", total=32.0),
        ))
        assert result[:4] == b"%PDF"

    def test_build_no_comps(self):
        result = asyncio.run(build_deal_memo(
            parcel=self._sample_parcel(),
            score=self._sample_score(),
            comps=[],
        ))
        assert result[:4] == b"%PDF"

    def test_model_version_is_set(self):
        assert MODEL_VERSION.startswith("v")
