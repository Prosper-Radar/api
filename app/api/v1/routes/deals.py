"""
Deals routes — schéma unifié post-migration 0005.

parcels    : parcel_id, county, address, owner_name, land_value,
             lot_size_sqft, zoning_code, last_sale_date, geometry
deal_scores: waterfront_score…recency_score, total_score, tier,
             model_version, computed_at
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from uuid import UUID

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.session import get_db
from app.scoring.tiers import TIER_A_THRESHOLD, TIER_B_THRESHOLD

router = APIRouter(prefix="/deals", tags=["deals"])

# Seuils lus depuis tiers.py — source de vérité unique
_TIER_EXPR = f"""
    CASE
        WHEN ds.total_score >= {TIER_A_THRESHOLD} THEN 'A'
        WHEN ds.total_score >= {TIER_B_THRESHOLD} THEN 'B'
        ELSE 'C'
    END
"""

_LIST_SQL = text(f"""
SELECT
    p.id,
    p.parcel_id,
    p.county,
    p.address,
    p.owner_name,
    p.land_value,
    p.lot_size_sqft,
    p.zoning_code,
    p.last_sale_date,
    p.last_sale_price,
    ST_Y(ST_Centroid(p.geometry))   AS lat,
    ST_X(ST_Centroid(p.geometry))   AS lng,
    ds.waterfront_score,
    ds.zoning_score,
    ds.price_score,
    ds.lot_size_score,
    ds.population_score,
    ds.traffic_score,
    COALESCE(ds.recency_score, 50)  AS recency_score,
    COALESCE(ds.total_score, 0)     AS total_score,
    COALESCE(ds.tier, {_TIER_EXPR}) AS tier
FROM parcels p
JOIN deal_scores ds ON ds.parcel_id = p.id
WHERE COALESCE(ds.total_score, 0) >= :min_score
  AND (CAST(:county AS text) IS NULL OR LOWER(p.county) = LOWER(CAST(:county AS text)))
  AND (CAST(:tier AS text)   IS NULL OR COALESCE(ds.tier, {_TIER_EXPR}) = CAST(:tier AS text))
ORDER BY ds.total_score DESC
LIMIT  :limit
OFFSET :offset
""")

_GET_SQL = text(f"""
SELECT
    p.id,
    p.parcel_id,
    p.county,
    p.address,
    p.owner_name,
    p.owner_address,
    p.land_value,
    p.building_value,
    p.lot_size_sqft,
    p.zoning_code,
    p.last_sale_date,
    p.last_sale_price,
    ST_Y(ST_Centroid(p.geometry))   AS lat,
    ST_X(ST_Centroid(p.geometry))   AS lng,
    ds.waterfront_score,
    ds.zoning_score,
    ds.price_score,
    ds.lot_size_score,
    ds.population_score,
    ds.traffic_score,
    COALESCE(ds.recency_score, 50)  AS recency_score,
    COALESCE(ds.total_score, 0)     AS total_score,
    COALESCE(ds.tier, {_TIER_EXPR}) AS tier,
    ds.model_version,
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


@router.post("/{deal_id}/pipeline")
async def add_to_pipeline(
    deal_id: UUID,
    status: str = "spotted",
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Ajoute ou met à jour le statut pipeline d'un deal."""
    from app.db.models.deal_pipeline import DealPipelineItem
    item = DealPipelineItem(
        parcel_id=deal_id,
        added_by=current_user,
        status=status,
        notes=notes,
    )
    db.add(item)
    await db.commit()
    return {"status": "added", "pipeline_status": status, "id": str(item.id), "added_by": current_user}
