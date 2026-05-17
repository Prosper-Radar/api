from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func as sa_func
from typing import Optional
from uuid import UUID

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.parcel import Parcel
from app.db.models.deal_score import DealScore
from app.db.models.watchlist import WatchlistItem

router = APIRouter(prefix="/deals", tags=["deals"])


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
    lng_expr = sa_func.ST_X(sa_func.ST_Centroid(Parcel.geometry))
    lat_expr = sa_func.ST_Y(sa_func.ST_Centroid(Parcel.geometry))

    query = (
        select(Parcel, DealScore, lng_expr.label("lng"), lat_expr.label("lat"))
        .join(DealScore, DealScore.parcel_id == Parcel.id)
        .where(DealScore.total_score >= min_score)
        .order_by(desc(DealScore.total_score))
        .limit(limit)
        .offset(offset)
    )

    if tier:
        query = query.where(DealScore.tier == tier)
    if county:
        query = query.where(Parcel.county == county)

    result = await db.execute(query)
    rows = result.all()

    deals = []
    for row in rows:
        parcel, score, lng, lat = row[0], row[1], row[2], row[3]
        deals.append({
            "id": str(parcel.id),
            "parcel_id": parcel.parcel_id,
            "county": parcel.county,
            "address": parcel.address,
            "owner_name": parcel.owner_name,
            "land_value": parcel.land_value,
            "lot_size_sqft": float(parcel.lot_size_sqft or 0),
            "zoning_code": parcel.zoning_code,
            "last_sale_date": parcel.last_sale_date.isoformat() if parcel.last_sale_date else None,
            "last_sale_price": parcel.last_sale_price,
            "lng": float(lng) if lng is not None else None,
            "lat": float(lat) if lat is not None else None,
            "scores": {
                "waterfront":        float(score.waterfront_score or 0),
                "zoning":            float(score.zoning_score or 0),
                "price_range":       float(score.price_score or 0),
                "lot_size":          float(score.lot_size_score or 0),
                "population_growth": float(score.population_score or 0),
                "traffic":           float(score.traffic_score or 0),
                "recency":           float(score.recency_score or 0),
                "total":             float(score.total_score or 0),
            },
            "tier": score.tier,
            "missing_metrics": [],  # populated after scoring engine upgrade
        })

    return {"deals": deals, "meta": {"offset": offset, "limit": limit}}


@router.get("/{deal_id}")
async def get_deal(deal_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Parcel, DealScore)
        .join(DealScore, DealScore.parcel_id == Parcel.id)
        .where(Parcel.id == deal_id)
        .order_by(desc(DealScore.computed_at))
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found")

    parcel, score = row
    return {
        "id": str(parcel.id),
        "parcel_id": parcel.parcel_id,
        "county": parcel.county,
        "address": parcel.address,
        "owner_name": parcel.owner_name,
        "owner_address": parcel.owner_address,
        "land_value": parcel.land_value,
        "building_value": parcel.building_value,
        "lot_size_sqft": float(parcel.lot_size_sqft or 0),
        "zoning_code": parcel.zoning_code,
        "last_sale_date": parcel.last_sale_date.isoformat() if parcel.last_sale_date else None,
        "last_sale_price": parcel.last_sale_price,
        "scores": {
            "waterfront":        float(score.waterfront_score or 0),
            "zoning":            float(score.zoning_score or 0),
            "price_range":       float(score.price_score or 0),
            "lot_size":          float(score.lot_size_score or 0),
            "population_growth": float(score.population_score or 0),
            "traffic":           float(score.traffic_score or 0),
            "recency":           float(score.recency_score or 0),
            "total":             float(score.total_score or 0),
        },
        "tier": score.tier,
        "score_computed_at": score.computed_at.isoformat(),
    }


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
