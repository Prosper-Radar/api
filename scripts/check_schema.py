"""Check actual DB schema and row counts."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

DB = os.environ.get("DATABASE_URL", "").replace("postgresql://", "postgresql+asyncpg://")

async def main():
    engine = create_async_engine(DB)
    async with engine.connect() as conn:
        r = await conn.execute(text("SELECT COUNT(*) FROM parcels"))
        print(f"parcels rows: {r.scalar()}")

        r2 = await conn.execute(text("SELECT COUNT(*) FROM deal_scores"))
        print(f"deal_scores rows: {r2.scalar()}")

        r3 = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='deal_scores' AND table_schema='public' "
            "ORDER BY ordinal_position"
        ))
        print("deal_scores columns:")
        for col, dtype in r3.all():
            print(f"  {col}: {dtype}")

        r4 = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='parcels' AND table_schema='public' "
            "ORDER BY ordinal_position"
        ))
        print("parcels columns:", [row[0] for row in r4.all()])

asyncio.run(main())
