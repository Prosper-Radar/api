"""
Water-body proximity service.

Uses a PostGIS `water_bodies` table populated from the USGS National
Hydrography Dataset (NHD) — Florida extract.

Data loading: see scripts/load_nhd_florida.py (or run the make target).
If the table is empty the function returns None and the scoring engine
gracefully excludes the waterfront metric from the weighted sum.
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def get_distance_to_water(
    db: AsyncSession,
    parcel_id: str,
) -> Optional[float]:
    """
    Returns the shortest distance in metres from the parcel boundary to the
    nearest NHD water-body polygon.

    Returns None when:
    - the water_bodies table is empty / doesn't exist yet
    - the parcel geometry is NULL
    - any DB error occurs (logged as WARNING)

    The KNN operator (<->) makes this index-friendly even over millions of rows.
    """
    sql = text("""
        SELECT
            ST_Distance(
                p.geometry::geography,
                wb.geom::geography
            ) AS dist_m
        FROM parcels p
        CROSS JOIN LATERAL (
            SELECT geom
            FROM water_bodies
            ORDER BY p.geometry::geography <-> geom::geography
            LIMIT 1
        ) wb
        WHERE p.parcel_id = :parcel_id
          AND p.geometry IS NOT NULL
    """)

    try:
        result = await db.execute(sql, {"parcel_id": parcel_id})
        row = result.fetchone()
        if row is None:
            return None
        return float(row.dist_m)
    except Exception as exc:  # table missing / geom null / SRID mismatch
        logger.warning("water-distance unavailable for parcel %s: %s", parcel_id, exc)
        return None
