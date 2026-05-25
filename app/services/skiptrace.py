"""
Skip Tracing Service — Florida Sunbiz + OpenCorporates + Claude re-ranking.

For Tier A parcels, fetches entity info for the owner:
  1. Normalises the owner name (strips LLC/CORP/etc.)
  2. Searches Florida Sunbiz (sunbiz.org) HTML scraping
  3. Falls back to OpenCorporates API (us_fl jurisdiction)
  4. Persists an OwnerProfile row
  5. (Optional) Uses Claude to rank officers and identify the best contact

Sunbiz search URL:
  https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults
  ?inquiryType=EntityName&searchTerm=<name>

Note: Sunbiz does not require a key. HTML-only, rate-limit to ~5 req/min.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.owner_profile import OwnerProfile
from app.db.session import AsyncSessionLocal
from app.services.assembly import normalize_owner

logger = logging.getLogger(__name__)

_ENTITY_TYPE_RE = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|LTD|LP|LLP|LLLP|PA|PL|PLLC|TRUST|"
    r"INDIVIDUAL|ESTATE)\b",
    re.IGNORECASE,
)


@dataclass
class ContactCandidate:
    """Best contact identified by Claude (or heuristic fallback)."""
    name: str
    role: str
    confidence: float   # 0.0 – 1.0
    reasoning: str
    source: str         # "claude_ranked" | "heuristic"


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
# Claude re-ranking
# ---------------------------------------------------------------------------

async def rank_contacts_with_claude(
    officers: list[dict],
    owner_name: str,
    entity_name: Optional[str],
    anthropic_api_key: str,
) -> Optional[ContactCandidate]:
    """
    Use Claude to identify the single best contact from a list of officers.

    Falls back gracefully (first officer, or None) if the key is missing or
    the API call fails.
    """
    if not officers:
        return None

    def _heuristic_fallback() -> ContactCandidate:
        o = officers[0]
        return ContactCandidate(
            name=o.get("name", ""),
            role=o.get("title", ""),
            confidence=0.5,
            reasoning="First officer listed in public records (AI ranking unavailable).",
            source="heuristic",
        )

    if not anthropic_api_key:
        return _heuristic_fallback()

    try:
        import anthropic as _anthropic

        client = _anthropic.AsyncAnthropic(api_key=anthropic_api_key)

        officers_text = "\n".join(
            f"- {o.get('name', 'Unknown')} ({o.get('title', 'Unknown role')})"
            + (f" — {o.get('address', '')}" if o.get("address") else "")
            for o in officers
        )

        prompt = (
            f"You are helping a real estate acquisitions team identify who to contact "
            f"about purchasing a property.\n\n"
            f"Entity: {entity_name or owner_name}\n"
            f"Owner of record: {owner_name}\n\n"
            f"Officers listed in Florida Sunbiz:\n{officers_text}\n\n"
            f"Task: Identify the single best person to contact who is most likely the "
            f"decision-maker for selling this property. Prefer MANAGER, PRESIDENT, "
            f"MEMBER, or DIRECTOR titles.\n\n"
            f"Respond ONLY with a JSON object (no markdown) with these fields:\n"
            f"- name: the officer's full name\n"
            f"- role: their title/role\n"
            f"- confidence: float 0.0-1.0\n"
            f"- reasoning: one sentence why they are the best contact"
        )

        message = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        data = json.loads(text)
        return ContactCandidate(
            name=data.get("name", officers[0].get("name", "")),
            role=data.get("role", officers[0].get("title", "")),
            confidence=float(data.get("confidence", 0.7)),
            reasoning=data.get("reasoning", ""),
            source="claude_ranked",
        )

    except Exception as exc:
        logger.warning("Claude contact ranking failed: %s", exc)
        return _heuristic_fallback()


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
                    "searchTerm": name[:60],
                },
            )
            resp.raise_for_status()
            html = resp.text

        rows = re.findall(
            r'<tr[^>]*>\s*<td[^>]*>\s*'
            r'<a[^>]+objectId=([A-Z0-9]+)[^>]*>([^<]+)</a>\s*</td>'
            r'\s*<td[^>]*>([^<]*)</td>'
            r'\s*<td[^>]*>([^<]*)</td>'
            r'\s*<td[^>]*>([^<]*)</td>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        if not rows:
            logger.error(
                "Sunbiz returned 200 but no rows parsed for '%s'. "
                "HTML structure may have changed. First 500 chars: %s",
                name,
                html[:500],
            )
            return None

        object_id, entity_name, _doc_num, status, filed_date = rows[0]
        officers = await _sunbiz_detail(object_id.strip())

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


async def _sunbiz_detail(object_id: str) -> list[dict]:
    """Fetch officer list from Sunbiz detail page."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://search.sunbiz.org/Inquiry/CorporationSearch/GetFilingInformation",
                params={"objectId": object_id},
            )
            resp.raise_for_status()
            html = resp.text

        officers = []
        blocks = re.findall(
            r'<span[^>]*labelColumn[^>]*>([^<]+)</span>'
            r'\s*<span[^>]*dataColumn[^>]*>([^<]+)</span>',
            html,
            re.IGNORECASE,
        )
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

        return officers[:10]

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
    db: Optional[AsyncSession] = None,
) -> Optional[OwnerProfile]:
    """
    Run skip tracing for a parcel and persist the result.

    Opens its own DB session if `db` is not provided.
    Returns the OwnerProfile row (or None if all lookups failed).
    """
    if not owner_name_raw or owner_name_raw.strip().upper() in ("UNKNOWN", "N/A", ""):
        return None

    norm = normalize_owner(owner_name_raw)

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

    async with AsyncSessionLocal() as session:
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

    logger.info(
        "Skip-traced parcel %s: %s (%s, %s officers)",
        parcel_id,
        norm,
        profile.entity_type,
        len(profile.officers or []),
    )
    return profile
