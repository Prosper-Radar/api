import uuid

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator

from app.core.config import get_settings

settings = get_settings()

# Supabase uses pgBouncer in transaction mode, which does not support prepared
# statements. asyncpg still prepares statements internally (e.g. for dialect
# initialization). To avoid DuplicatePreparedStatementError we:
#   1. Use NullPool — no app-level pooling, pgBouncer handles it.
#   2. Give every prepared statement a unique UUID name so different asyncpg
#      connections never collide on the same pgBouncer server-side connection.
engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
    poolclass=NullPool,
    echo=settings.debug,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
    },
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
