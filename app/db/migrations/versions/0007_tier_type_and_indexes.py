"""Aligner le type de colonne tier + créer les index de performance.

Problème :
  - migration 0001 créait tier comme VARCHAR(1)
  - migration 0004 ajoutait tier comme TEXT (IF NOT EXISTS, donc n'override pas)
  - Résultat incohérent selon l'ordre de migration
  - Pas d'index sur total_score → seq scan à chaque GET /deals

Ce que cette migration fait :
  1. Force tier en VARCHAR(1) avec contrainte CHECK ('A','B','C').
  2. Crée les index manquants pour les requêtes courantes.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. Normaliser la colonne tier ────────────────────────────────────────
    # Corriger les valeurs hors-grille avant d'appliquer le CHECK
    conn.execute(sa.text("""
        UPDATE deal_scores
        SET tier = 'C'
        WHERE tier NOT IN ('A', 'B', 'C') OR tier IS NULL
    """))

    # Caster en VARCHAR(1)
    conn.execute(sa.text("""
        ALTER TABLE deal_scores
        ALTER COLUMN tier TYPE VARCHAR(1) USING tier::varchar(1)
    """))

    # Ajouter le CHECK si absent
    conn.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'deal_scores'
                  AND constraint_name = 'deal_scores_tier_check'
            ) THEN
                ALTER TABLE deal_scores
                ADD CONSTRAINT deal_scores_tier_check CHECK (tier IN ('A', 'B', 'C'));
            END IF;
        END $$;
    """))

    # ── 2. Index de tri principal (GET /deals ORDER BY total_score DESC) ──────
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_deal_scores_total_desc
        ON deal_scores (total_score DESC NULLS LAST)
    """))

    # ── 3. Index de filtrage fréquents ────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_deal_scores_tier
        ON deal_scores (tier)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_parcels_county
        ON parcels (county)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_deal_scores_model_version
        ON deal_scores (model_version)
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_deal_pipeline_status
        ON deal_pipeline (status)
    """))

    # ── 4. Index spatial (PostGIS) ────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_parcels_geometry
        ON parcels USING GIST (geometry)
    """))
    # Index spatial water_bodies — seulement si la colonne geom existe
    # (table peut être vide avant chargement des données NHD)
    has_geom = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = 'water_bodies'
              AND column_name  = 'geom'
        )
    """)).scalar()
    if has_geom:
        conn.execute(sa.text("""
            CREATE INDEX IF NOT EXISTS idx_water_bodies_geom
            ON water_bodies USING GIST (geom)
        """))
    # UNIQUE — requis par l'upsert différentiel dans assembly.py
    conn.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_assembled_sites_owner_unique
        ON assembled_sites (owner_name_normalized)
    """))


def downgrade():
    conn = op.get_bind()

    for idx in [
        "idx_deal_scores_total_desc",
        "idx_deal_scores_tier",
        "idx_parcels_county",
        "idx_deal_scores_model_version",
        "idx_deal_pipeline_status",
        "idx_parcels_geometry",
        "idx_water_bodies_geom",
        "idx_assembled_sites_owner_unique",
    ]:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx}"))

    conn.execute(sa.text(
        "ALTER TABLE deal_scores DROP CONSTRAINT IF EXISTS deal_scores_tier_check"
    ))
