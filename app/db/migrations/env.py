"""
Alembic env.py — utilise psycopg2 (synchrone) pour les migrations.

Pourquoi psycopg2 et non asyncpg :
  Supabase utilise pgBouncer en mode transaction (port 6543), qui ne supporte
  pas les prepared statements asyncpg. psycopg2 n'a pas cette limitation et
  fonctionne parfaitement pour les migrations DDL synchrones.

Run migrations:
  alembic upgrade head

Generate a new revision after model changes:
  alembic revision --autogenerate -m "describe change"
"""
import os
from logging.config import fileConfig

from dotenv import load_dotenv

# Charger .env depuis la racine du repo api/
load_dotenv()

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

# Import all models so Alembic sees them for autogenerate
from app.db.base import Base  # noqa: F401
import app.db.models.parcel         # noqa: F401
import app.db.models.deal_score     # noqa: F401
import app.db.models.deal_pipeline  # noqa: F401
import app.db.models.assembled_site # noqa: F401

config = context.config

# Override sqlalchemy.url depuis l'environnement
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    # Forcer psycopg2 pour les migrations (évite les problèmes pgBouncer/asyncpg)
    sync_url = (
        database_url
        .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        .replace("postgresql://", "postgresql+psycopg2://")
    )
    config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
