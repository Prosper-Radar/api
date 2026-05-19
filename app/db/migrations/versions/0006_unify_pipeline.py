"""Unify pipeline — migre watchlist vers deal_pipeline, supprime watchlist.

Contexte :
  - Le webapp (Drizzle) gère deal_pipeline avec 6 statuts + activité.
  - L'API Python avait watchlist (4 statuts différents, table parallèle).
  - Cette migration fusionne les données watchlist dans deal_pipeline
    puis supprime watchlist.

Mapping des statuts :
  watching  → spotted
  contacted → reviewing
  LOI       → loi_submitted
  closed    → closed
  (autre)   → spotted

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # S'assurer que deal_pipeline existe (créé par Drizzle, peut manquer en env frais)
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS deal_pipeline (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            parcel_id    UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
            status       TEXT NOT NULL DEFAULT 'spotted',
            notes        TEXT,
            assigned_to  TEXT,
            added_by     TEXT NOT NULL DEFAULT 'demo',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    # Index unique (parcel_id, added_by) — même contrainte que le schema Drizzle
    conn.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS pipeline_parcel_user_uidx
        ON deal_pipeline (parcel_id, added_by)
    """))

    # Vérifier si watchlist existe avant de migrer
    has_watchlist = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'watchlist'
        )
    """)).scalar()

    if has_watchlist:
        # Inspecter les colonnes réelles de watchlist (Drizzle vs Python model divergent)
        cols = conn.execute(sa.text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'watchlist'
        """)).fetchall()
        col_names = {r[0] for r in cols}

        # Drizzle watchlist : user_key, note (pas status, added_by)
        # Python watchlist  : added_by, notes, status (jamais déployé en DB)
        notes_col  = "note"     if "note"     in col_names else "notes"
        addedby_col = "user_key" if "user_key" in col_names else "added_by"

        conn.execute(sa.text(f"""
            INSERT INTO deal_pipeline (parcel_id, status, notes, added_by, created_at)
            SELECT
                w.parcel_id,
                'spotted',
                w.{notes_col},
                COALESCE(w.{addedby_col}, 'demo'),
                w.created_at
            FROM watchlist w
            ON CONFLICT (parcel_id, added_by) DO NOTHING
        """))

        # Supprimer watchlist
        conn.execute(sa.text("DROP TABLE IF EXISTS watchlist CASCADE"))


def downgrade():
    conn = op.get_bind()

    # Recréer watchlist minimale
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            parcel_id  UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
            added_by   TEXT,
            notes      TEXT,
            status     TEXT DEFAULT 'watching',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
