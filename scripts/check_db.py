"""Quick DB health check — run with: python scripts/check_db.py"""
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def main():
    url = os.environ["DATABASE_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(url)

    async with engine.connect() as conn:
        tables = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))
        print("Tables:", [r[0] for r in tables.fetchall()])

        version = await conn.execute(text(
            "SELECT version FROM alembic_version"
        ))
        print("Alembic version:", version.scalar())

        wb_count = await conn.execute(text("SELECT COUNT(*) FROM water_bodies"))
        print("water_bodies rows:", wb_count.scalar())

    await engine.dispose()


asyncio.run(main())
