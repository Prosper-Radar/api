"""
Assembly & Skip Trace API routes.

GET  /api/v1/assembly              — list all assembled sites
GET  /api/v1/assembly/{parcel_id}  — get assembly for a specific parcel
POST /api/v1/assembly/recompute    — trigger full recompute (background)
GET  /api/v1/deals/{deal_id}/skiptrace — get owner profile for a deal
POST /api/v1/deals/{deal_id}/skiptrace — trigger skip trace for a deal
"""
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.assembled_site import AssembledSite
from app.db.models.owner_profile import OwnerProfile
from app.db.models.parcel import Parcel
from app.services.assembly import persist_assemblies
from app.services.skiptrace import skip_trace_parcel

router = APIRouter(tags=["assembly"])


# ---------------------------------------------------------------------------
# Assembly endpoints
# ---------------------------------------------------------------------------

@router.get("/assembly")
async def list_assemblies(
    min_parcels: int = Query(2, ge=2, description="Minimum number of parcels in the assembly"),
    county: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Return all assembled sites (multi-parcel same-owner groups)."""
    stmt = (
        select(AssembledSite)
        .where(AssembledSite.parcel_count >= min_parcels)
        .order_by(AssembledSite.total_land_value.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    if county:
        stmt = stmt.where(AssembledSite.county == county)

    result = await db.execute(stmt)
    sites = result.scalars().all()

    return {
        "assemblies": [
            {
                "id": str(s.id),
                "owner_name_normalized": s.owner_name_normalized,
                "parcel_count": s.parcel_count,
                "parcel_ids": s.parcel_ids,
                "total_land_value": s.total_land_value,
                "total_lot_size_sqft": float(s.total_lot_size_sqft or 0),
                "county": s.county,
                "computed_at": s.computed_at.isoformat() if s.computed_at else None,
            }
            for s in sites
        ],
        "meta": {"offset": offset, "limit": limit},
    }


@router.get("/assembly/{parcel_id}")
async def get_assembly_for_parcel(
    parcel_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the assembled site that contains a specific parcel (if any)."""
    result = await db.execute(
        select(AssembledSite).where(
            AssembledSite.parcel_ids.contains([str(parcel_id)])
        )
    )
    site = result.scalar_one_or_none()
    if not site:
        return {"assembly": None, "message": "This parcel is not part of any assembly."}

    return {
        "assembly": {
            "id": str(site.id),
            "owner_name_normalized": site.owner_name_normalized,
            "parcel_count": site.parcel_count,
            "parcel_ids": site.parcel_ids,
            "total_land_value": site.total_land_value,
            "total_lot_size_sqft": float(site.total_lot_size_sqft or 0),
            "county": site.county,
        }
    }


@router.post("/assembly/recompute")
async def recompute_assemblies(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a full parcel-assembly recompute in the background."""
    background_tasks.add_task(persist_assemblies, db)
    return {"status": "started", "task": "parcel-assembly"}


# ---------------------------------------------------------------------------
# Skip trace endpoints
# ---------------------------------------------------------------------------

@router.get("/deals/{deal_id}/skiptrace")
async def get_skiptrace(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return cached owner profile for a deal (if skip trace has been run)."""
    result = await db.execute(
        select(OwnerProfile)
        .where(OwnerProfile.parcel_id == deal_id)
        .order_by(OwnerProfile.fetched_at.desc())
        .limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No skip-trace data found. POST to this endpoint to trigger one.",
        )

    return {
        "owner_profile": {
            "parcel_id": str(profile.parcel_id),
            "owner_name_raw": profile.owner_name_raw,
            "owner_name_normalized": profile.owner_name_normalized,
            "entity_type": profile.entity_type,
            "entity_status": profile.entity_status,
            "filing_date": profile.filing_date.isoformat() if profile.filing_date else None,
            "registered_agent": profile.registered_agent,
            "principal_address": profile.principal_address,
            "officers": profile.officers or [],
            "source": profile.source,
            "fetched_at": profile.fetched_at.isoformat() if profile.fetched_at else None,
        }
    }


@router.post("/deals/{deal_id}/skiptrace")
async def trigger_skiptrace(
    deal_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger skip tracing for a specific deal. Returns immediately."""
    result = await db.execute(select(Parcel).where(Parcel.id == deal_id))
    parcel = result.scalar_one_or_none()
    if not parcel:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not parcel.owner_name:
        raise HTTPException(status_code=422, detail="Parcel has no owner name to trace")

    background_tasks.add_task(
        skip_trace_parcel,
        db=db,
        parcel_id=str(parcel.id),
        owner_name_raw=parcel.owner_name,
    )
    return {
        "status": "started",
        "parcel_id": str(parcel.id),
        "owner_name": parcel.owner_name,
    }
