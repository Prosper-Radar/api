"""
Deal Memo routes.

GET /api/v1/deals/{deal_id}/memo.pdf   — download PDF
GET /api/v1/deals/{deal_id}/memo.html  — preview HTML (browser-friendly)
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.assembled_site import AssembledSite
from app.db.models.deal_score import DealScore
from app.db.models.owner_profile import OwnerProfile
from app.db.models.parcel import Parcel
from app.db.session import get_db
from app.services.pdf import build_deal_memo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["memo"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _load_deal(db: AsyncSession, deal_id: UUID):
    result = await db.execute(
        select(Parcel, DealScore)
        .join(DealScore, DealScore.parcel_id == Parcel.id)
        .where(Parcel.id == deal_id)
        .order_by(desc(DealScore.computed_at))
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found or not yet scored")
    return row[0], row[1]


async def _load_owner(db: AsyncSession, parcel_id: UUID) -> dict | None:
    result = await db.execute(
        select(OwnerProfile)
        .where(OwnerProfile.parcel_id == parcel_id)
        .order_by(desc(OwnerProfile.fetched_at))
        .limit(1)
    )
    p = result.scalar_one_or_none()
    if not p:
        return None
    return {
        "entity_type": p.entity_type,
        "entity_status": p.entity_status,
        "filing_date": str(p.filing_date) if p.filing_date else None,
        "registered_agent": p.registered_agent,
        "principal_address": p.principal_address,
        "officers": p.officers or [],
    }


async def _load_assembly(db: AsyncSession, parcel_id: str) -> dict | None:
    result = await db.execute(
        select(AssembledSite).where(
            AssembledSite.parcel_ids.contains([parcel_id])
        )
    )
    s = result.scalar_one_or_none()
    if not s or s.parcel_count < 2:
        return None
    return {
        "parcel_count": s.parcel_count,
        "total_land_value": s.total_land_value,
        "total_lot_size_sqft": float(s.total_lot_size_sqft or 0),
    }


async def _load_comps(
    db: AsyncSession,
    parcel: Parcel,
    score: DealScore,
) -> list[dict]:
    """
    Find comparable sales:
    - Same county, same or adjacent zoning
    - Sold within the last 3 years
    - Within 1.6 km (~1 mile) via PostGIS ST_DWithin
    - Scored (has a DealScore row)
    - Exclude the subject parcel itself
    """
    if parcel.geometry is None:
        return []

    from sqlalchemy import text
    sql = text("""
        SELECT
            p.address,
            p.zoning_code,
            p.lot_size_sqft,
            p.last_sale_date,
            p.last_sale_price
        FROM parcels p
        WHERE
            p.id != :self_id
            AND p.county = :county
            AND p.last_sale_date >= CURRENT_DATE - INTERVAL '3 years'
            AND p.last_sale_price > 0
            AND p.geometry IS NOT NULL
            AND ST_DWithin(
                p.geometry::geography,
                (SELECT geometry FROM parcels WHERE id = :self_id)::geography,
                1609.0   -- 1 mile in metres
            )
        ORDER BY p.last_sale_date DESC
        LIMIT 6
    """)
    result = await db.execute(sql, {
        "self_id": str(parcel.id),
        "county": parcel.county,
    })
    rows = result.fetchall()
    return [
        {
            "address": r.address,
            "zoning_code": r.zoning_code,
            "lot_size_sqft": float(r.lot_size_sqft or 0),
            "last_sale_date": str(r.last_sale_date) if r.last_sale_date else None,
            "last_sale_price": int(r.last_sale_price or 0),
        }
        for r in rows
    ]


def _parcel_to_dict(p: Parcel, s: DealScore, lng: float | None, lat: float | None) -> dict:
    return {
        "id": str(p.id),
        "parcel_id": p.parcel_id,
        "address": p.address,
        "county": p.county,
        "owner_name": p.owner_name,
        "land_value": p.land_value,
        "lot_size_sqft": float(p.lot_size_sqft or 0),
        "zoning_code": p.zoning_code,
        "last_sale_date": str(p.last_sale_date) if p.last_sale_date else None,
        "last_sale_price": p.last_sale_price,
        "lng": lng,
        "lat": lat,
    }


def _score_to_dict(s: DealScore) -> dict:
    return {
        "tier": s.tier,
        "total": float(s.total_score or 0),
        "scores": {
            "waterfront":        float(s.waterfront_score) if s.waterfront_score is not None else None,
            "zoning":            float(s.zoning_score or 0),
            "price_range":       float(s.price_score or 0),
            "lot_size":          float(s.lot_size_score or 0),
            "population_growth": float(s.population_score) if s.population_score is not None else None,
            "traffic":           float(s.traffic_score) if s.traffic_score is not None else None,
            "recency":           float(s.recency_score or 0),
        },
    }


async def _get_centroid(db: AsyncSession, parcel_id: str):
    from sqlalchemy import text
    r = await db.execute(text("""
        SELECT ST_X(ST_Centroid(geometry)) AS lng, ST_Y(ST_Centroid(geometry)) AS lat
        FROM parcels WHERE id = :id
    """), {"id": parcel_id})
    row = r.fetchone()
    if row:
        return row.lng, row.lat
    return None, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/deals/{deal_id}/memo.pdf")
async def get_deal_memo_pdf(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and download the Deal Memo PDF for a scored deal.
    Includes aerial imagery (Mapbox), score breakdown, owner profile,
    assembly info, and comparable sales.
    """
    settings = get_settings()
    parcel, score = await _load_deal(db, deal_id)
    lng, lat = await _get_centroid(db, str(parcel.id))

    owner    = await _load_owner(db, deal_id)
    assembly = await _load_assembly(db, str(parcel.id))
    comps    = await _load_comps(db, parcel, score)

    parcel_dict = _parcel_to_dict(parcel, score, lng, lat)
    score_dict  = _score_to_dict(score)

    pdf_bytes = await build_deal_memo(
        parcel=parcel_dict,
        score=score_dict,
        owner=owner,
        assembly=assembly,
        comps=comps,
        mapbox_token=settings.mapbox_token or settings.next_public_mapbox_token,
    )

    safe_addr = (parcel.address or "deal").replace(" ", "_").replace("/", "-")[:40]
    filename  = f"DealMemo_{safe_addr}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get("/deals/{deal_id}/memo.html")
async def get_deal_memo_html(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Return a browser-viewable HTML preview of the deal memo.
    Useful for debugging layout before generating the PDF.
    """
    settings = get_settings()
    parcel, score = await _load_deal(db, deal_id)
    lng, lat = await _get_centroid(db, str(parcel.id))

    owner    = await _load_owner(db, deal_id)
    assembly = await _load_assembly(db, str(parcel.id))
    comps    = await _load_comps(db, parcel, score)

    parcel_dict = _parcel_to_dict(parcel, score, lng, lat)
    score_dict  = _score_to_dict(score)

    # Reuse the email alert renderer for the HTML preview
    from app.services.email_alerts import _render_html
    html = _render_html(
        parcel=parcel_dict,
        score=score_dict,
        assembly=assembly,
        owner=owner,
        dashboard_url=settings.app_url,
    )
    return Response(content=html, media_type="text/html; charset=utf-8")
