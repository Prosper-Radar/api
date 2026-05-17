"""
Deals routes.

Current DB uses the Drizzle seed schema:
  parcels:     id, folio, address_line, city, state, zip, county, lat, lng,
               acreage, zoning, created_at, updated_at
  deal_scores: id, parcel_id, total_score, breakdown (jsonb {momentum, location,
               value, liquidity}), model_version, computed_at

Individual score columns (waterfront_score, zoning_score, …, tier) do NOT exist
yet — they come from breakdown jsonb or are derived.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from uuid import UUID

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.watchlist import WatchlistItem

router = APIRouter(prefix="/deals", tags=["deals"])

_TIER_EXPR = """
    CASE
        WHEN ds.total_score >= 80 THEN 'A'
        WHEN ds.total_score >= 65 THEN 'B'
        ELSE 'C'
    END
"""

_LIST_SQL = text(f"""
SELECT
    p.id,
    -- prefer scraper columns; fall back to drizzle seed columns
    COALESCE(p.parcel_id, p.folio, '')                AS parcel_id,
    COALESCE(p.county, 'miami-dade')                  AS county,
    COALESCE(p.address, p.address_line, '')           AS address,
    p.owner_name,
    p.land_value,
    COALESCE(p.lot_size_sqft,
             p.acreage * 43560)                       AS lot_size_sqft,
    COALESCE(p.zoning_code, p.zoning)                 AS zoning_code,
    p.last_sale_date,
    p.last_sale_price,
    -- prefer geometry centroid, fall back to lat/lng floats
    CASE WHEN p.geometry IS NOT NULL
         THEN ST_Y(ST_Centroid(p.geometry))
         ELSE p.lat END                               AS lat,
    CASE WHEN p.geometry IS NOT NULL
         THEN ST_X(ST_Centroid(p.geometry))
         ELSE p.lng END                               AS lng,
    -- prefer individual score columns (from scraper scoring); fall back to jsonb
    COALESCE(ds.waterfront_score,
             (ds.breakdown->>'location')::numeric / 2)  AS waterfront_score,
    COALESCE(ds.zoning_score,
             (ds.breakdown->>'value')::numeric)          AS zoning_score,
    COALESCE(ds.price_score,
             (ds.breakdown->>'value')::numeric)          AS price_score,
    COALESCE(ds.lot_size_score,
             (ds.breakdown->>'momentum')::numeric)       AS lot_size_score,
    COALESCE(ds.population_score,
             (ds.breakdown->>'location')::numeric)       AS population_score,
    COALESCE(ds.traffic_score,
             (ds.breakdown->>'liquidity')::numeric)      AS traffic_score,
    COALESCE(ds.recency_score, 50)                    AS recency_score,
    COALESCE(ds.total_score, 0)                       AS total_score,
    COALESCE(ds.tier, {_TIER_EXPR})                   AS tier
FROM parcels p
JOIN deal_scores ds ON ds.parcel_id = p.id
WHERE COALESCE(ds.total_score, 0) >= :min_score
  AND (CAST(:county AS text) IS NULL OR LOWER(COALESCE(p.county, '')) = LOWER(CAST(:county AS text)))
  AND (CAST(:tier AS text)   IS NULL OR COALESCE(ds.tier, {_TIER_EXPR}) = CAST(:tier AS text))
ORDER BY ds.total_score DESC
LIMIT  :limit
OFFSET :offset
""")

_GET_SQL = text(f"""
SELECT
    p.id,
    COALESCE(p.parcel_id, p.folio, '')                AS parcel_id,
    COALESCE(p.county, 'miami-dade')                  AS county,
    COALESCE(p.address, p.address_line, '')           AS address,
    p.owner_name,
    p.owner_address,
    p.land_value,
    p.building_value,
    COALESCE(p.lot_size_sqft, p.acreage * 43560)      AS lot_size_sqft,
    COALESCE(p.zoning_code, p.zoning)                 AS zoning_code,
    p.last_sale_date,
    p.last_sale_price,
    CASE WHEN p.geometry IS NOT NULL
         THEN ST_Y(ST_Centroid(p.geometry))
         ELSE p.lat END                               AS lat,
    CASE WHEN p.geometry IS NOT NULL
         THEN ST_X(ST_Centroid(p.geometry))
         ELSE p.lng END                               AS lng,
    COALESCE(ds.waterfront_score,
             (ds.breakdown->>'location')::numeric / 2)  AS waterfront_score,
    COALESCE(ds.zoning_score,
             (ds.breakdown->>'value')::numeric)          AS zoning_score,
    COALESCE(ds.price_score,
             (ds.breakdown->>'value')::numeric)          AS price_score,
    COALESCE(ds.lot_size_score,
             (ds.breakdown->>'momentum')::numeric)       AS lot_size_score,
    COALESCE(ds.population_score,
             (ds.breakdown->>'location')::numeric)       AS population_score,
    COALESCE(ds.traffic_score,
             (ds.breakdown->>'liquidity')::numeric)      AS traffic_score,
    COALESCE(ds.recency_score, 50)                    AS recency_score,
    COALESCE(ds.total_score, 0)                       AS total_score,
    COALESCE(ds.tier, {_TIER_EXPR})                   AS tier,
    ds.computed_at
FROM parcels p
JOIN deal_scores ds ON ds.parcel_id = p.id
WHERE p.id = :deal_id
LIMIT 1
""")


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_deal(row) -> dict:
    return {
        "id":              str(row.id),
        "parcel_id":       row.parcel_id or "",
        "county":          row.county or "",
        "address":         row.address or "",
        "owner_name":      row.owner_name,
        "land_value":      row.land_value,
        "lot_size_sqft":   _f(row.lot_size_sqft) or 0.0,
        "zoning_code":     row.zoning_code,
        "last_sale_date":  row.last_sale_date.isoformat() if row.last_sale_date else None,
        "last_sale_price": row.last_sale_price,
        "lat":             _f(row.lat),
        "lng":             _f(row.lng),
        "scores": {
            "waterfront":        _f(row.waterfront_score),
            "zoning":            _f(row.zoning_score) or 0.0,
            "price_range":       _f(row.price_score) or 0.0,
            "lot_size":          _f(row.lot_size_score) or 0.0,
            "population_growth": _f(row.population_score),
            "traffic":           _f(row.traffic_score),
            "recency":           _f(row.recency_score) or 50.0,
            "total":             _f(row.total_score) or 0.0,
        },
        "tier":            row.tier or "C",
        "missing_metrics": [],
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("")
@limiter.limit("60/minute")
async def list_deals(
    request: Request,
    tier: Optional[str] = Query(None, pattern="^[ABC]$"),
    county: Optional[str] = None,
    min_score: float = 0,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_LIST_SQL, {
        "min_score": min_score,
        "county":    county,
        "tier":      tier,
        "limit":     limit,
        "offset":    offset,
    })
    rows = result.all()
    return {
        "deals": [_row_to_deal(r) for r in rows],
        "meta": {"offset": offset, "limit": limit, "total": len(rows)},
    }


@router.get("/{deal_id}")
async def get_deal(deal_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(_GET_SQL, {"deal_id": deal_id})
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal = _row_to_deal(row)
    deal["owner_address"] = getattr(row, "owner_address", None)
    deal["building_value"] = getattr(row, "building_value", None)
    deal["score_computed_at"] = row.computed_at.isoformat() if row.computed_at else None
    return deal


@router.post("/{deal_id}/watchlist")
async def add_to_watchlist(
    deal_id: UUID,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Add a deal to the watchlist. Uses JWT sub as added_by."""
    item = WatchlistItem(parcel_id=deal_id, added_by=current_user, notes=notes)
    db.add(item)
    await db.commit()
    return {"status": "added", "id": str(item.id), "added_by": current_user}
