"""
Parcel sync tasks — fetches from county scrapers and upserts into Postgres.

Deduplication strategy: ON CONFLICT (parcel_id) DO UPDATE
- Fields that should never regress (e.g. geometry) are updated only when the
  incoming value is not null, using COALESCE(excluded.col, existing.col).
- Scalar enrichment fields are always overwritten so stale data stays fresh.
"""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db.models.parcel import Parcel
from app.scrapers import miami_dade, hillsborough
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Columns that should be preserved if the new value is NULL
_COALESCE_COLS = {"geometry"}


def _build_upsert_set(row: dict[str, Any]) -> dict[str, Any]:
    """
    Build the SET clause for ON CONFLICT DO UPDATE.

    Geometry-like columns use COALESCE so a scrape that returns no geometry
    doesn't wipe out previously stored spatial data.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import literal_column, func

    set_clause: dict[str, Any] = {}
    for col, val in row.items():
        if col == "parcel_id":
            continue  # never overwrite the conflict key
        if col in _COALESCE_COLS:
            # Keep existing value when incoming is NULL
            set_clause[col] = func.coalesce(
                literal_column(f"excluded.{col}"),
                literal_column(f"parcels.{col}"),
            )
        else:
            set_clause[col] = literal_column(f"excluded.{col}")
    return set_clause


async def upsert_parcels(db: AsyncSession, normalized: list[dict[str, Any]]) -> int:
    """
    Upsert a batch of normalised parcel dicts.
    Returns the number of rows processed.
    """
    if not normalized:
        return 0

    valid = [r for r in normalized if r and r.get("parcel_id")]
    if not valid:
        logger.warning("upsert_parcels: all rows missing parcel_id — skipped")
        return 0

    stmt = (
        insert(Parcel)
        .values(valid)
        .on_conflict_do_update(
            index_elements=["parcel_id"],
            set_=_build_upsert_set(valid[0]),
        )
    )
    await db.execute(stmt)
    await db.commit()
    return len(valid)


async def run_miami_dade_sync():
    from app.db.session import AsyncSessionLocal
    settings = get_settings()
    offset = 0
    batch_size = 100
    total = 0

    while True:
        try:
            raw = await miami_dade.fetch_parcels(
                api_key=settings.miami_dade_api_key,
                offset=offset,
                limit=batch_size,
            )
        except Exception as exc:
            logger.error("Miami-Dade fetch failed at offset %d: %s", offset, exc)
            break

        if not raw:
            break

        normalized = [miami_dade.normalize_parcel(p) for p in raw]
        async with AsyncSessionLocal() as db:
            upserted = await upsert_parcels(db, normalized)
        total += upserted
        logger.info("Miami-Dade sync: offset=%d upserted=%d", offset, upserted)
        offset += batch_size

    return total


async def run_hillsborough_sync():
    from app.db.session import AsyncSessionLocal
    offset = 0
    batch_size = 100
    total = 0

    while True:
        try:
            raw = await hillsborough.fetch_parcels(offset=offset, limit=batch_size)
        except Exception as exc:
            logger.error("Hillsborough fetch failed at offset %d: %s", offset, exc)
            break

        if not raw:
            break

        normalized = [hillsborough.normalize_parcel(p) for p in raw]
        async with AsyncSessionLocal() as db:
            upserted = await upsert_parcels(db, normalized)
        total += upserted
        logger.info("Hillsborough sync: offset=%d upserted=%d", offset, upserted)
        offset += batch_size

    return total
