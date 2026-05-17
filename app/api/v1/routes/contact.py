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


def _deep_links(owner_name: str | None, is_individual: bool = False) -> dict[str, str]:
    """Generate context-aware search links for the owner."""
    if not owner_name or owner_name.strip().upper() in ("UNKNOWN", "N/A", ""):
        return {}
    name = owner_name.strip()
    import urllib.parse as up
    encoded = up.quote_plus(name)

    links: dict[str, str] = {
        "sunbiz": (
            "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
            f"?inquiryType=EntityName&inquiryDirectionType=BEGINS&searchTerm={encoded}"
        ),
        "opencorporates": (
            f"https://opencorporates.com/companies/us_fl?q={encoded}"
        ),
    }

    if is_individual:
        # For individuals, target people-search and LinkedIn
        links["linkedin"] = (
            f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
        )
        links["google_email"] = (
            f"https://www.google.com/search?q={up.quote_plus(f'\"{name}\" email OR contact Miami Florida')}"
        )
        links["whitepages"] = (
            f"https://www.whitepages.com/name/{up.quote(name.replace(' ', '-'))}"
        )
    else:
        # For companies, target business directories
        links["google_contact"] = (
            f"https://www.google.com/search?q={up.quote_plus(f'\"{name}\" Miami Florida real estate contact')}"
        )
        links["linkedin_company"] = (
            f"https://www.linkedin.com/search/results/companies/?keywords={encoded}"
        )
        links["bizapedia"] = (
            f"https://www.bizapedia.com/fl/{up.quote(name.lower().replace(' ', '-'))}.html"
        )

    return links


def _profile_to_dict(profile: OwnerProfile, owner_name_raw: str | None = None) -> dict[str, Any]:
    name = profile.owner_name_raw or owner_name_raw or ""
    is_individual = (profile.entity_type or "").upper() == "INDIVIDUAL"
    return {
        "found": True,
        "owner_name_raw": profile.owner_name_raw,
        "owner_name_normalized": profile.owner_name_normalized,
        "entity_type": profile.entity_type,
        "entity_status": profile.entity_status,
        "is_individual": is_individual,
        "filing_date": profile.filing_date.isoformat() if profile.filing_date else None,
        "registered_agent": profile.registered_agent,
        "principal_address": profile.principal_address,
        "officers": profile.officers or [],
        "source": profile.source,
        "fetched_at": profile.fetched_at.isoformat() if profile.fetched_at else None,
        "links": _deep_links(name, is_individual=is_individual),
        "contact_tip": (
            "This is an individual owner — search LinkedIn or Whitepages for direct contact."
            if is_individual else
            "Check the officers list above for direct contacts within this entity."
        ),
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
    # Guess if it's an individual (no LLC/CORP/etc. in name)
    from app.services.skiptrace import _detect_entity_type
    entity_type = _detect_entity_type(owner_name)
    is_individual = entity_type == "INDIVIDUAL"

    return {
        "found": False,
        "reason": (
            "Individual owner — use the links below to find contact info."
            if is_individual else
            "Entity not found in FL Sunbiz — may be registered in another state."
        ),
        "owner_name_raw": owner_name,
        "entity_type": entity_type,
        "is_individual": is_individual,
        "contact_tip": (
            "Search LinkedIn or Whitepages for direct contact with this individual."
            if is_individual else
            "This entity may be a national company. Try Google or LinkedIn to find the local contact."
        ),
        "links": _deep_links(owner_name, is_individual=is_individual),
    }
