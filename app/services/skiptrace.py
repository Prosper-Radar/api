"""
Skip Tracing Service — Florida Sunbiz + OpenCorporates.

For Tier A parcels, fetches entity info for the owner:
  1. Normalises the owner name (strips LLC/CORP/etc.)
  2. Searches Florida Sunbiz (sunbiz.org) HTML scraping
  3. Falls back to OpenCorporates API (us_fl jurisdiction)
  4. Persists an OwnerProfile row

Sunbiz search URL:
  https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults
  ?inquiryType=EntityName&searchTerm=<name>

Note: Sunbiz does not require a key. HTML-only, rate-limit to ~5 req/min.
"""
import logging
import re
from datetime import date
from typing import Optional

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.owner_profile import OwnerProfile
from app.db.session import AsyncSessionLocal
from app.services.assembly import normalize_owner

logger = logging.getLogger(__name__)

_SUNBIZ_SEARCH = (
    "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
    "?inquiryType=EntityName&inquiryDirectionType=BEGINS&searchTerm={name}"
)
_SUNBIZ_DETAIL = (
    "https://search.sunbiz.org/Inquiry/CorporationSearch/"
    "GetFilingInformation?objectId={object_id}"
)
_OC_SEARCH = (
    "https://api.opencorporates.com/v0.4/companies/search"
    "?q={name}&jurisdiction_code=us_fl&per_page=1"
)

_ENTITY_TYPE_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|LTD|LP|LLP|LLLP|PA|PL|PLLC|TRUST|"
    r"INDIVIDUAL|ESTATE)\b",
    re.IGNORECASE,
)


def _detect_entity_type(name: str) -> str:
    m = _ENTITY_TYPE_RE.search(name or "")
    if m:
        return m.group(1).upper().replace(".", "")
    return "INDIVIDUAL"


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Sunbiz scraper
# ---------------------------------------------------------------------------

async def _sunbiz_search(name: str) -> Optional[dict]:
    """
    Search Sunbiz by entity name. Returns parsed entity dict or None.
    Sunbiz returns an HTML table of results; we grab the first match.
    """
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "DealScout/1.0 (prosper-group.com)"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults",
                params={
                    "inquiryType": "EntityName",
                    "inquiryDirectionType": "BEGINS",
                    "searchTerm": name[:60],  # Sunbiz truncates long names
                },
            )
            resp.raise_for_status()
            html = resp.text

        # Parse the results table — Sunbiz uses a simple <table> structure
        # Row format: <td>EntityName</td><td>DocNum</td><td>Status</td><td>Date</td>
        rows = re.findall(
            r'<tr[^>]*>\s*<td[^>]*>\s*'
            r'<a[^>]+objectId=([A-Z0-9]+)[^>]*>([^<]+)</a>\s*</td>'   # link + name
            r'\s*<td[^>]*>([^<]*)</td>'                                  # doc number
            r'\s*<td[^>]*>([^<]*)</td>'                                  # status
            r'\s*<td[^>]*>([^<]*)</td>',                                 # date filed
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if not rows:
            # HTTP 200 mais parsing vide → structure HTML probablement changée
            logger.error(
                "Sunbiz returned 200 but no rows parsed for '%s'. "
                "HTML structure may have changed. First 500 chars: %s",
                name,
                html[:500],
            )
            return None

        # Take the first (most relevant) result
        object_id, entity_name, doc_num, status, filed_date = rows[0]

        # Fetch the detail page for officers
        officers = await _sunbiz_detail(object_id.strip(), client if False else None)

        return {
            "entity_name": entity_name.strip(),
            "entity_type": _detect_entity_type(entity_name),
            "entity_status": status.strip().upper() or "UNKNOWN",
            "filing_date": _parse_date(filed_date.strip()),
            "officers": officers,
            "source": "sunbiz",
        }

    except httpx.HTTPStatusError as exc:
        logger.warning("Sunbiz HTTP error %s for '%s'", exc.response.status_code, name)
        return None
    except Exception as exc:
        logger.warning("Sunbiz search failed for '%s': %s", name, exc)
        return None


async def _sunbiz_detail(object_id: str, _client=None) -> list[dict]:
    """Fetch officer list from Sunbiz detail page."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://search.sunbiz.org/Inquiry/CorporationSearch/GetFilingInformation",
                params={"objectId": object_id},
            )
            resp.raise_for_status()
            html = resp.text

        # Officers section: <span class="labelColumn">Title</span>
        #                   <span class="dataColumn">MANAGER</span>
        officers = []
        blocks = re.findall(
            r'<span[^>]*labelColumn[^>]*>([^<]+)</span>'
            r'\s*<span[^>]*dataColumn[^>]*>([^<]+)</span>',
            html,
            re.IGNORECASE,
        )
        # Group into officer records
        current: dict = {}
        for label, value in blocks:
            label = label.strip().upper()
            value = value.strip()
            if label == "TITLE":
                if current:
                    officers.append(current)
                current = {"title": value}
            elif label == "NAME" and current:
                current["name"] = value
            elif label == "ADDRESS" and current:
                current["address"] = value

        if current:
            officers.append(current)

        return officers[:10]  # cap at 10 officers

    except Exception as exc:
        logger.debug("Sunbiz detail fetch failed for %s: %s", object_id, exc)
        return []


# ---------------------------------------------------------------------------
# OpenCorporates fallback
# ---------------------------------------------------------------------------

async def _opencorporates_search(name: str, api_token: str = "") -> Optional[dict]:
    """Search OpenCorporates for a Florida entity."""
    params = {"q": name[:80], "jurisdiction_code": "us_fl", "per_page": 1}
    if api_token:
        params["api_token"] = api_token

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params=params,
            )
            r.raise_for_status()
            data = r.json()

        companies = data.get("results", {}).get("companies", [])
        if not companies:
            return None

        co = companies[0]["company"]
        return {
            "entity_name": co.get("name", ""),
            "entity_type": _detect_entity_type(co.get("company_type", "")),
            "entity_status": "ACTIVE" if co.get("inactive") is False else "INACTIVE",
            "filing_date": _parse_date(co.get("incorporation_date")),
            "registered_agent": co.get("registered_address", {}).get("street_address"),
            "principal_address": co.get("registered_address", {}).get("locality"),
            "officers": [
                {"name": o["officer"].get("name", ""), "title": o["officer"].get("position", "")}
                for o in co.get("officers", [])[:5]
            ],
            "source": "opencorporates",
        }
    except Exception as exc:
        logger.debug("OpenCorporates search failed for '%s': %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def skip_trace_parcel(
    parcel_id: str,
    owner_name_raw: str,
    oc_api_token: str = "",
) -> Optional[OwnerProfile]:
    """
    Run skip tracing for a parcel and persist the result.

    Ouvre sa propre session DB (ne partage pas la session de la task parente).
    Returns the OwnerProfile row (or None if all lookups failed).
    """
    if not owner_name_raw or owner_name_raw.strip().upper() in ("UNKNOWN", "N/A", ""):
        return None

    norm = normalize_owner(owner_name_raw)

    # Try Sunbiz first, then OpenCorporates
    info = await _sunbiz_search(norm) or await _opencorporates_search(norm, oc_api_token)

    if info is None:
        logger.info("No skip-trace data found for owner '%s' (parcel %s)", norm, parcel_id)
        return None

    profile = OwnerProfile(
        parcel_id=parcel_id,
        owner_name_raw=owner_name_raw,
        owner_name_normalized=norm,
        entity_type=info.get("entity_type", _detect_entity_type(owner_name_raw)),
        entity_status=info.get("entity_status"),
        filing_date=info.get("filing_date"),
        registered_agent=info.get("registered_agent"),
        principal_address=info.get("principal_address"),
        officers=info.get("officers", []),
        source=info.get("source", "unknown"),
    )

    async with AsyncSessionLocal() as db:
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    logger.info(
        "Skip-traced parcel %s: %s (%s, %s officers)",
        parcel_id,
        norm,
        profile.entity_type,
        len(profile.officers or []),
    )
    return profile
