"""
Contact / Skip Trace endpoint.

GET  /api/v1/deals/{deal_id}/contact
  → Returns cached OwnerProfile if available, else runs skip trace on-the-fly
    and caches the result.

The caller (Next.js webapp) shows:
  - owner name, entity type & status
  - officers with titles
  - registered agent / principal address
  - smart deep-link URLs (Sunbiz, Google, LinkedIn, OpenCorporates)
"""
import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db as get_session
from app.db.models.owner_profile import OwnerProfile
from app.services.skiptrace import skip_trace_parcel
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/deals", tags=["contact"])


def _deep_links(owner_name: str | None) -> dict[str, str]:
    """Generate ready-to-open search links for the owner."""
    if not owner_name or owner_name.strip().upper() in ("UNKNOWN", "N/A", ""):
        return {}
    name = owner_name.strip()
    import urllib.parse as up
    encoded = up.quote_plus(name)
    return {
        "sunbiz": (
            "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
            f"?inquiryType=EntityName&inquiryDirectionType=BEGINS&searchTerm={encoded}"
        ),
        "google": (
            f"https://www.google.com/search?q={up.quote_plus(f'{name} Miami contact email phone real estate')}"
        ),
        "linkedin": (
            f"https://www.linkedin.com/search/results/all/?keywords={encoded}"
        ),
        "opencorporates": (
            f"https://opencorporates.com/companies/us_fl?q={encoded}"
        ),
        "netr": (
            f"https://netr.com/search/?query={encoded}"  # NETR public records
        ),
    }


def _profile_to_dict(profile: OwnerProfile, owner_name_raw: str | None = None) -> dict[str, Any]:
    name = profile.owner_name_raw or owner_name_raw or ""
    return {
        "found": True,
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
        "links": _deep_links(name),
    }


@router.get("/{deal_id}/contact")
async def get_deal_contact(
    deal_id: str,
    refresh: bool = False,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Return owner contact intelligence for a deal.
    - Checks for a cached OwnerProfile first.
    - If none found (or refresh=true), runs the skip trace pipeline.
    - Always returns deep-link URLs for manual lookup.
    """
    # ── 1. Resolve the parcel ────────────────────────────────────────────────
    try:
        parcel_uuid = _uuid.UUID(deal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid deal ID (must be UUID)")

    row = await db.execute(
        text(
            "SELECT id, COALESCE(owner_name, '') AS owner_name "
            "FROM parcels WHERE id = :id LIMIT 1"
        ),
        {"id": str(parcel_uuid)},
    )
    parcel = row.mappings().first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Deal not found")

    owner_name: str = parcel["owner_name"] or ""

    # ── 2. Check cache ───────────────────────────────────────────────────────
    if not refresh:
        result = await db.execute(
            select(OwnerProfile)
            .where(OwnerProfile.parcel_id == parcel_uuid)
            .order_by(OwnerProfile.fetched_at.desc())
            .limit(1)
        )
        cached = result.scalars().first()
        if cached:
            return _profile_to_dict(cached, owner_name)

    # ── 3. Run skip trace ────────────────────────────────────────────────────
    if not owner_name or owner_name.strip().upper() in ("UNKNOWN", "N/A", ""):
        return {
            "found": False,
            "reason": "No owner name available for this parcel",
            "links": {},
        }

    try:
        oc_token = getattr(get_settings(), "opencorporates_api_key", "")
        profile = await skip_trace_parcel(
            db=db,
            parcel_id=str(parcel_uuid),
            owner_name_raw=owner_name,
            oc_api_token=oc_token,
        )
    except Exception as exc:
        logger.warning("Skip trace failed for %s: %s", deal_id, exc)
        profile = None

    if profile:
        return _profile_to_dict(profile, owner_name)

    # ── 4. Fallback — links only ─────────────────────────────────────────────
    return {
        "found": False,
        "reason": "No entity data found in Sunbiz or OpenCorporates",
        "owner_name_raw": owner_name,
        "links": _deep_links(owner_name),
    }
