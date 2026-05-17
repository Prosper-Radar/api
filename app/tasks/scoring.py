"""
Scoring task — runs for all parcels, wires the 3 real-data services.

Per-parcel pipeline:
  1. PostGIS  → distance_to_water_m   (water.py)
  2. Census   → population_growth_rate (census.py)
  3. FDOT GIS → aadt                  (fdot.py)
  4. engine   → ScoreBreakdown        (scoring/engine.py)

Each service returns Optional; the engine renormalises weights so missing
metrics don't collapse the score (no more hardcoded 0 / 0.025 / 50_000).
"""
import asyncio
import logging
from typing import Optional

from geoalchemy2.shape import to_shape
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.deal_score import DealScore
from app.db.models.parcel import Parcel
from app.scoring.engine import ScoreBreakdown, ScoringInput, compute_score
from app.services import census as census_svc
from app.services import fdot as fdot_svc
from app.services import water as water_svc
from app.services import skiptrace as skiptrace_svc
from app.services import email_alerts as alert_svc

logger = logging.getLogger(__name__)


async def _get_centroid(parcel: Parcel) -> Optional[tuple[float, float]]:
    """Extract (lon, lat) from the parcel's PostGIS geometry using Shapely."""
    if parcel.geometry is None:
        return None
    try:
        shape = to_shape(parcel.geometry)
        centroid = shape.centroid
        return centroid.x, centroid.y
    except Exception as exc:
        logger.warning("Cannot extract centroid for parcel %s: %s", parcel.parcel_id, exc)
        return None


async def _gather_metrics(
    db: AsyncSession,
    parcel: Parcel,
    census_api_key: str,
) -> tuple[Optional[float], Optional[float], Optional[int]]:
    """
    Fetch all external metrics concurrently per parcel.
    Returns (distance_to_water_m, population_growth_rate, aadt).
    """
    centroid = await _get_centroid(parcel)

    water_coro = water_svc.get_distance_to_water(db, parcel.parcel_id)

    if centroid is not None:
        lon, lat = centroid
        census_coro = census_svc.get_population_growth_rate(lon, lat, census_api_key)
        fdot_coro = fdot_svc.get_aadt(lon, lat)
    else:
        # No geometry → skip external services
        census_coro = asyncio.coroutine(lambda: None)()
        fdot_coro = asyncio.coroutine(lambda: None)()

    results = await asyncio.gather(water_coro, census_coro, fdot_coro, return_exceptions=True)

    def _unwrap(val):
        if isinstance(val, Exception):
            return None
        return val

    return _unwrap(results[0]), _unwrap(results[1]), _unwrap(results[2])


async def score_parcel(
    db: AsyncSession,
    parcel: Parcel,
    census_api_key: str,
) -> ScoreBreakdown:
    """Score a single parcel and upsert its DealScore row."""
    dist_water, pop_growth, aadt = await _gather_metrics(db, parcel, census_api_key)

    inp = ScoringInput(
        distance_to_water_m=dist_water,
        zoning_code=parcel.zoning_code or "",
        land_value=parcel.land_value or 0,
        lot_size_sqft=float(parcel.lot_size_sqft or 0),
        population_growth_rate=pop_growth,
        aadt=aadt,
        last_sale_date=parcel.last_sale_date,
    )

    breakdown = compute_score(inp)

    if breakdown.missing_metrics:
        logger.info(
            "Parcel %s — missing metrics: %s (weights redistributed)",
            parcel.parcel_id,
            ", ".join(breakdown.missing_metrics),
        )

    stmt = (
        insert(DealScore)
        .values(
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
        .on_conflict_do_update(
            index_elements=["parcel_id"],
            set_={
                "waterfront_score": breakdown.waterfront,
                "zoning_score": breakdown.zoning,
                "price_score": breakdown.price_range,
                "lot_size_score": breakdown.lot_size,
                "population_score": breakdown.population_growth,
                "traffic_score": breakdown.traffic,
                "recency_score": breakdown.sale_recency,
                "total_score": breakdown.total,
                "tier": breakdown.tier,
            },
        )
    )
    await db.execute(stmt)

    # --- Sprint 2 post-scoring hooks for Tier A deals ---
    if breakdown.tier == "A":
        settings = get_settings()

        # 1. Skip tracing (fire-and-forget — don't block scoring)
        if parcel.owner_name:
            asyncio.create_task(skiptrace_svc.skip_trace_parcel(
                db=db,
                parcel_id=str(parcel.id),
                owner_name_raw=parcel.owner_name,
            ))

        # 2. Email alert
        if settings.resend_api_key and settings.alert_email_to:
            parcel_dict = {
                "id": str(parcel.id),
                "address": parcel.address,
                "county": parcel.county,
                "owner_name": parcel.owner_name,
                "land_value": parcel.land_value or 0,
                "lot_size_sqft": float(parcel.lot_size_sqft or 0),
                "zoning_code": parcel.zoning_code,
            }
            score_dict = {
                "tier": breakdown.tier,
                "total": breakdown.total,
                "scores": {
                    "waterfront": breakdown.waterfront,
                    "zoning": breakdown.zoning,
                    "price_range": breakdown.price_range,
                    "lot_size": breakdown.lot_size,
                    "population_growth": breakdown.population_growth,
                    "traffic": breakdown.traffic,
                    "recency": breakdown.sale_recency,
                },
            }
            asyncio.create_task(alert_svc.send_tier_a_alert(
                api_key=settings.resend_api_key,
                from_email=settings.alert_email_from,
                to_emails=[e.strip() for e in settings.alert_email_to.split(",") if e.strip()],
                parcel=parcel_dict,
                score=score_dict,
                dashboard_url=settings.app_url,
            ))

    return breakdown


async def run_score_computation(db: AsyncSession) -> int:
    """Recompute scores for all parcels. Called as a background task."""
    settings = get_settings()
    result = await db.execute(select(Parcel))
    parcels = result.scalars().all()

    scored = 0
    errors = 0

    for parcel in parcels:
        try:
            await score_parcel(db, parcel, settings.census_api_key)
            scored += 1
        except Exception as exc:
            errors += 1
            logger.error("Failed to score parcel %s: %s", parcel.parcel_id, exc)

    await db.commit()
    logger.info("Score computation done: %d scored, %d errors", scored, errors)
    return scored
