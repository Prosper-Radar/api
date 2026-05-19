"""Quick test of the deals SQL query against the real DB."""
import asyncio, os, traceback
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DB = os.environ.get("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://", 1)

TIER_EXPR = """
    CASE
        WHEN ds.total_score >= 80 THEN 'A'
        WHEN ds.total_score >= 65 THEN 'B'
        ELSE 'C'
    END
"""

LIST_SQL = text(f"""
SELECT
    p.id,
    p.folio                                           AS parcel_id,
    p.county,
    p.address_line                                    AS address,
    NULL::text                                        AS owner_name,
    NULL::bigint                                      AS land_value,
    ROUND((p.acreage * 43560)::numeric, 0)            AS lot_size_sqft,
    p.zoning                                          AS zoning_code,
    NULL::date                                        AS last_sale_date,
    NULL::bigint                                      AS last_sale_price,
    p.lat,
    p.lng,
    (ds.breakdown->>'location')::float / 2            AS waterfront_score,
    (ds.breakdown->>'value')::float                   AS zoning_score,
    (ds.breakdown->>'value')::float                   AS price_score,
    (ds.breakdown->>'momentum')::float                AS lot_size_score,
    (ds.breakdown->>'location')::float                AS population_score,
    (ds.breakdown->>'liquidity')::float               AS traffic_score,
    50.0                                              AS recency_score,
    ds.total_score,
    {TIER_EXPR}                                       AS tier
FROM parcels p
JOIN deal_scores ds ON ds.parcel_id = p.id
WHERE ds.total_score >= :min_score
  AND (CAST(:county AS text) IS NULL OR LOWER(p.county) = LOWER(CAST(:county AS text)))
  AND (CAST(:tier AS text)   IS NULL OR {TIER_EXPR} = CAST(:tier AS text))
ORDER BY ds.total_score DESC
LIMIT  :limit
OFFSET :offset
""")

async def main():
    engine = create_async_engine(DB, echo=False, connect_args={"statement_cache_size": 0})
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db:
        try:
            result = await db.execute(LIST_SQL, {
                "min_score": 0,
                "county": None,
                "tier": None,
                "limit": 3,
                "offset": 0,
            })
            rows = result.all()
            print(f"SUCCESS — {len(rows)} rows")
            for r in rows:
                print(f"  {r.address} | score={r.total_score} | tier={r.tier} | lat={r.lat}")
        except Exception:
            traceback.print_exc()

asyncio.run(main())
