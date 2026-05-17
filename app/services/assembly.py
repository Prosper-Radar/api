"""
Parcel Assembly Service.

Detects contiguous parcels owned by the same entity and aggregates them
into AssembledSite records.

Algorithm:
  1. SQL: find pairs of parcels within 1 m of each other (ST_DWithin)
         AND whose normalized owner name is identical.
  2. Python: union-find to build connected components from touching pairs.
  3. Persist each component (≥2 parcels) as an AssembledSite row.

Owner normalisation strips common LLC / corporate suffixes so that
"BRICKELL LAND LLC" and "BRICKELL LAND L.L.C." are treated as the same owner.
"""
import logging
import re
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assembled_site import AssembledSite

logger = logging.getLogger(__name__)

# Suffixes to strip when normalising owner names
_ENTITY_SUFFIXES = re.compile(
    r"\b(LLC|L\.L\.C\.|L\.L\.C|INC|INCORPORATED|CORP|CORPORATION|"
    r"LTD|LIMITED|LP|L\.P\.|LLP|LLLP|PA|P\.A\.|PL|PLLC|"
    r"TR|TRUST|REVOCABLE|IRREVOCABLE|FAMILY|ET\s+AL|ETAL|"
    r"&\s+SONS|AND\s+SONS)\b\.?",
    re.IGNORECASE,
)


def normalize_owner(raw: str) -> str:
    """Strip entity suffixes and collapse whitespace for owner-name matching."""
    if not raw:
        return ""
    name = raw.upper().strip()
    name = _ENTITY_SUFFIXES.sub(" ", name)
    name = re.sub(r"[^\w\s]", " ", name)       # punctuation → space
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ---------------------------------------------------------------------------
# Union-Find (disjoint set union)
# ---------------------------------------------------------------------------

class _UF:
    def __init__(self):
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for node in self._parent:
            root = self.find(node)
            result.setdefault(root, []).append(node)
        return result


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

@dataclass
class AssemblyResult:
    owner_name_normalized: str
    parcel_ids: list[str]
    parcel_count: int
    total_land_value: Optional[int]
    total_lot_size_sqft: Optional[float]
    county: Optional[str]
    geometry_ewkt: Optional[str]  # ST_AsEWKT of the union


async def find_assemblies(db: AsyncSession) -> list[AssemblyResult]:
    """
    Return a list of AssemblyResult for every group of 2+ contiguous
    parcels that share the same normalized owner name.
    """
    # Step 1: find all touching pairs (within 1 m) — using geography cast
    #         for accurate metre-based distance check.
    pairs_sql = text("""
        SELECT
            a.id::text  AS id_a,
            b.id::text  AS id_b,
            a.owner_name AS owner_a
        FROM parcels a
        JOIN parcels b
            ON a.id < b.id           -- avoid duplicate pairs
            AND a.geometry IS NOT NULL
            AND b.geometry IS NOT NULL
            AND ST_DWithin(
                    a.geometry::geography,
                    b.geometry::geography,
                    1.0              -- 1 metre tolerance
                )
        WHERE a.owner_name IS NOT NULL
          AND b.owner_name IS NOT NULL
    """)

    result = await db.execute(pairs_sql)
    rows = result.fetchall()

    if not rows:
        logger.info("No touching parcel pairs found.")
        return []

    # Step 2: filter pairs whose normalised owner names match, then union-find
    uf = _UF()
    owner_map: dict[str, str] = {}   # parcel_id → normalised owner

    for id_a, id_b, owner_a_raw in rows:
        # We only fetched owner_a; fetch owner_b lazily if needed
        pass

    # Re-fetch with both owner names to allow cross-check
    pairs_sql2 = text("""
        SELECT
            a.id::text  AS id_a,
            b.id::text  AS id_b,
            a.owner_name AS owner_a,
            b.owner_name AS owner_b
        FROM parcels a
        JOIN parcels b
            ON a.id < b.id
            AND a.geometry IS NOT NULL
            AND b.geometry IS NOT NULL
            AND ST_DWithin(
                    a.geometry::geography,
                    b.geometry::geography,
                    1.0
                )
        WHERE a.owner_name IS NOT NULL
          AND b.owner_name IS NOT NULL
    """)

    result2 = await db.execute(pairs_sql2)
    pairs = result2.fetchall()

    for id_a, id_b, owner_a, owner_b in pairs:
        norm_a = normalize_owner(owner_a)
        norm_b = normalize_owner(owner_b)
        if norm_a and norm_b and norm_a == norm_b:
            uf.union(id_a, id_b)
            owner_map[id_a] = norm_a
            owner_map[id_b] = norm_b

    groups = {root: members for root, members in uf.groups().items()
              if len(members) >= 2}

    if not groups:
        logger.info("No multi-parcel assemblies found.")
        return []

    # Step 3: for each component, aggregate stats via PostGIS
    assemblies: list[AssemblyResult] = []

    for root, parcel_ids in groups.items():
        id_list = ", ".join(f"'{pid}'" for pid in parcel_ids)
        agg_sql = text(f"""
            SELECT
                SUM(land_value)                             AS total_land_value,
                SUM(lot_size_sqft)                          AS total_lot_sqft,
                (ARRAY_AGG(county ORDER BY land_value DESC NULLS LAST))[1] AS top_county,
                ST_AsEWKT(ST_Union(geometry))               AS union_geom
            FROM parcels
            WHERE id::text IN ({id_list})
        """)
        agg = (await db.execute(agg_sql)).fetchone()

        assemblies.append(AssemblyResult(
            owner_name_normalized=owner_map.get(root, ""),
            parcel_ids=parcel_ids,
            parcel_count=len(parcel_ids),
            total_land_value=int(agg.total_land_value) if agg.total_land_value else None,
            total_lot_size_sqft=float(agg.total_lot_sqft) if agg.total_lot_sqft else None,
            county=agg.top_county,
            geometry_ewkt=agg.union_geom,
        ))

    return assemblies


async def persist_assemblies(db: AsyncSession) -> int:
    """
    Compute and upsert all assembled sites.
    Returns the number of assemblies written.
    """
    assemblies = await find_assemblies(db)

    if not assemblies:
        return 0

    # Truncate and reinsert (full recompute strategy)
    await db.execute(text("TRUNCATE TABLE assembled_sites"))

    for a in assemblies:
        site = AssembledSite(
            id=_uuid.uuid4(),
            owner_name_normalized=a.owner_name_normalized,
            parcel_ids=a.parcel_ids,
            parcel_count=a.parcel_count,
            total_land_value=a.total_land_value,
            total_lot_size_sqft=a.total_lot_size_sqft,
            county=a.county,
            geometry=a.geometry_ewkt,
        )
        db.add(site)

    await db.commit()
    logger.info("Persisted %d assembled sites.", len(assemblies))
    return len(assemblies)
