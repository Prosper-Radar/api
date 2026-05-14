from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models.parcel import Parcel
from app.db.models.deal_score import DealScore
from app.db.models.watchlist import WatchlistItem

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("")
async def list_deals(
    tier: Optional[str] = Query(None, regex="^[ABC]$"),
    county: Optional[str] = None,
    min_score: float = 0,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Parcel, DealScore)
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
    for parcel, score in rows:
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
):
    item = WatchlistItem(parcel_id=deal_id, added_by="jay", notes=notes)
    db.add(item)
    await db.commit()
    return {"status": "added", "id": str(item.id)}
