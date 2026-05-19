"""Unify DB schema — supprime les colonnes Drizzle redondantes.

Contexte :
  - Drizzle ORM avait créé parcels avec : folio, address_line, city, state,
    zip, lat, lng, acreage, zoning — colonnes incompatibles avec le Python API.
  - La migration 0004 a ajouté les vraies colonnes (parcel_id, address, etc.)
    et backfillé les données.
  - deal_scores avait breakdown (jsonb à 4 dimensions) + model_version string.

Ce que cette migration fait :
  1. Supprime les colonnes Drizzle redondantes de parcels (données préservées
     dans parcel_id, address, lot_size_sqft, zoning_code).
  2. Supprime la colonne breakdown de deal_scores (données bidon car mapping
     arbitraire 4-dim → 7-dim dans 0004, cf. QA_GUIDELINES §8).
  3. Ajoute model_version à deal_scores avec valeur courante comme défaut.
  4. Invalide tous les scores produits avant le scoring engine réel
     (model_version NULL ou 'v0-demo') → ils seront recomputed au prochain run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Colonnes Drizzle à supprimer de parcels
_PARCEL_DRIZZLE_COLS = [
    "folio",
    "address_line",
    "city",
    "state",
    "zip",
    "lat",
    "lng",
    "acreage",
    "zoning",
]


def upgrade():
    conn = op.get_bind()

    # ── 1. Nettoyer parcels ───────────────────────────────────────────────────
    for col in _PARCEL_DRIZZLE_COLS:
        conn.execute(sa.text(
            f"ALTER TABLE parcels DROP COLUMN IF EXISTS {col}"
        ))

    # ── 2. Supprimer breakdown de deal_scores ─────────────────────────────────
    conn.execute(sa.text(
        "ALTER TABLE deal_scores DROP COLUMN IF EXISTS breakdown"
    ))

    # ── 3. Ajouter model_version à deal_scores (si absent) ───────────────────
    conn.execute(sa.text(
        "ALTER TABLE deal_scores ADD COLUMN IF NOT EXISTS "
        "model_version TEXT NOT NULL DEFAULT '1.0.0'"
    ))

    # Supprimer l'ancien missing_metrics jsonb (non utilisé par le Python model)
    conn.execute(sa.text(
        "ALTER TABLE deal_scores DROP COLUMN IF EXISTS missing_metrics"
    ))

    # ── 4. Invalider les scores bidon (backfill arbitraire de 0004) ──────────
    # On remet total_score=0 et tier=NULL pour forcer un recompute propre.
    conn.execute(sa.text("""
        UPDATE deal_scores
        SET
            total_score       = 0,
            tier              = 'C',
            waterfront_score  = NULL,
            zoning_score      = NULL,
            price_score       = NULL,
            lot_size_score    = NULL,
            population_score  = NULL,
            traffic_score     = NULL,
            recency_score     = NULL,
            model_version     = 'invalidated-by-0005'
        WHERE model_version IN ('v0-demo', 'invalidated-by-0005')
           OR model_version = '1.0.0'
              AND waterfront_score IS NULL
              AND zoning_score IS NULL
    """))
    # Note : après avoir appliqué cette migration, lancer run_score_computation()
    # pour recalculer tous les scores avec le vrai engine.


def downgrade():
    conn = op.get_bind()

    # Remettre les colonnes Drizzle (valeurs nulles, c'est acceptable en downgrade)
    drizzle_cols = {
        "folio":        "TEXT",
        "address_line": "TEXT",
        "city":         "TEXT",
        "state":        "TEXT",
        "zip":          "TEXT",
        "lat":          "DOUBLE PRECISION",
        "lng":          "DOUBLE PRECISION",
        "acreage":      "DOUBLE PRECISION",
        "zoning":       "TEXT",
    }
    for col, dtype in drizzle_cols.items():
        conn.execute(sa.text(
            f"ALTER TABLE deal_scores ADD COLUMN IF NOT EXISTS {col} {dtype}"
        ))

    conn.execute(sa.text(
        "ALTER TABLE deal_scores ADD COLUMN IF NOT EXISTS breakdown JSONB"
    ))
    conn.execute(sa.text(
        "ALTER TABLE deal_scores DROP COLUMN IF EXISTS model_version"
    ))
