from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db.models.parcel import Parcel
from app.scrapers import miami_dade, hillsborough
from app.core.config import get_settings


async def run_miami_dade_sync(db: AsyncSession):
    settings = get_settings()
    offset = 0
    batch_size = 100
    total = 0

    while True:
        raw_parcels = await miami_dade.fetch_parcels(
            api_key=settings.miami_dade_api_key,
            offset=offset,
            limit=batch_size,
        )
        if not raw_parcels:
            break

        normalized = [miami_dade.normalize_parcel(p) for p in raw_parcels]
        stmt = insert(Parcel).values(normalized).on_conflict_do_update(
            index_elements=["parcel_id"],
            set_={k: v for k, v in normalized[0].items() if k != "parcel_id"},
        )
        await db.execute(stmt)
        await db.commit()

        total += len(normalized)
        offset += batch_size

    return total


async def run_hillsborough_sync(db: AsyncSession):
    offset = 0
    batch_size = 100
    total = 0

    while True:
        raw_parcels = await hillsborough.fetch_parcels(offset=offset, limit=batch_size)
        if not raw_parcels:
            break

        normalized = [hillsborough.normalize_parcel(p) for p in raw_parcels]
        stmt = insert(Parcel).values(normalized).on_conflict_do_update(
            index_elements=["parcel_id"],
            set_={k: v for k, v in normalized[0].items() if k != "parcel_id"},
        )
        await db.execute(stmt)
        await db.commit()

        total += len(normalized)
        offset += batch_size

    return total
