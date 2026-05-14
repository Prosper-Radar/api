from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.parcel import Parcel
from app.db.models.deal_score import DealScore
from app.scoring.engine import compute_score, ScoringInput


async def run_score_computation(db: AsyncSession):
    result = await db.execute(select(Parcel))
    parcels = result.scalars().all()

    for parcel in parcels:
        inp = ScoringInput(
            distance_to_water_m=0,  # populated by PostGIS in v1
            zoning_code=parcel.zoning_code or "",
            land_value=parcel.land_value or 0,
            lot_size_sqft=float(parcel.lot_size_sqft or 0),
            population_growth_rate=0.025,  # default until Census integration
            aadt=50_000,                   # default until FDOT integration
            last_sale_date=parcel.last_sale_date,
        )

        breakdown = compute_score(inp)

        score = DealScore(
            parcel_id=parcel.id,
            waterfront_score=breakdown.waterfront,
            zoning_score=breakdown.zoning,
            price_score=breakdown.price_range,
            lot_size_score=breakdown.lot_size,
            population_score=breakdown.population_growth,
            traffic_score=breakdown.traffic,
            recency_score=breakdown.sale_recency,
            total_score=breakdown.total,
            tier=breakdown.tier,
        )
        db.add(score)

    await db.commit()
    return len(parcels)
