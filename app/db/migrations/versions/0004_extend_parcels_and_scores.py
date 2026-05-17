"""Extend parcels and deal_scores to be compatible with the Python API scraper schema.

The existing tables were created by Drizzle ORM with different column names:
  parcels:     folio, address_line, lat, lng, acreage, zoning  (no geometry, no owner info)
  deal_scores: total_score, breakdown (jsonb)  (no individual score columns, no tier)

This migration adds the columns the Python API expects so the scraper can write
real data and the scoring engine can store detailed breakdowns.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── parcels: add columns the Python Parcel model expects ─────────────────
    parcels_cols = {
        "parcel_id":       "TEXT",
        "address":         "TEXT",
        "owner_name":      "TEXT",
        "owner_address":   "TEXT",
        "land_value":      "BIGINT",
        "building_value":  "BIGINT",
        "total_value":     "BIGINT",
        "lot_size_sqft":   "NUMERIC",
        "zoning_code":     "TEXT",
        "last_sale_date":  "DATE",
        "last_sale_price": "BIGINT",
        "raw_data":        "TEXT",
    }
    for col, dtype in parcels_cols.items():
        conn.execute(sa.text(
            f"ALTER TABLE parcels ADD COLUMN IF NOT EXISTS {col} {dtype}"
        ))

    # geometry column needs PostGIS
    conn.execute(sa.text(
        "ALTER TABLE parcels ADD COLUMN IF NOT EXISTS geometry geometry(GEOMETRY, 4326)"
    ))

    # Unique index on parcel_id (the scraper deduplication key)
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS parcels_parcel_id_uidx ON parcels (parcel_id)"
    ))

    # Backfill: copy existing Drizzle data into the new columns so nothing disappears
    conn.execute(sa.text(
        "UPDATE parcels SET parcel_id = folio WHERE parcel_id IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE parcels SET address = address_line WHERE address IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE parcels SET lot_size_sqft = acreage * 43560 WHERE lot_size_sqft IS NULL AND acreage IS NOT NULL"
    ))
    conn.execute(sa.text(
        "UPDATE parcels SET zoning_code = zoning WHERE zoning_code IS NULL"
    ))

    # ── deal_scores: add individual score columns + tier ─────────────────────
    score_cols = {
        "waterfront_score":  "NUMERIC(5,2)",
        "zoning_score":      "NUMERIC(5,2)",
        "price_score":       "NUMERIC(5,2)",
        "lot_size_score":    "NUMERIC(5,2)",
        "population_score":  "NUMERIC(5,2)",
        "traffic_score":     "NUMERIC(5,2)",
        "recency_score":     "NUMERIC(5,2)",
        "tier":              "TEXT",
        "missing_metrics":   "JSONB",
    }
    for col, dtype in score_cols.items():
        conn.execute(sa.text(
            f"ALTER TABLE deal_scores ADD COLUMN IF NOT EXISTS {col} {dtype}"
        ))

    # Backfill tier from existing total_score
    conn.execute(sa.text("""
        UPDATE deal_scores
        SET tier = CASE
            WHEN total_score >= 80 THEN 'A'
            WHEN total_score >= 65 THEN 'B'
            ELSE 'C'
        END
        WHERE tier IS NULL
    """))

    # Backfill individual scores from breakdown jsonb where present
    conn.execute(sa.text("""
        UPDATE deal_scores
        SET
            waterfront_score = (breakdown->>'location')::numeric / 2,
            zoning_score     = (breakdown->>'value')::numeric,
            price_score      = (breakdown->>'value')::numeric,
            lot_size_score   = (breakdown->>'momentum')::numeric,
            population_score = (breakdown->>'location')::numeric,
            traffic_score    = (breakdown->>'liquidity')::numeric,
            recency_score    = 50
        WHERE breakdown IS NOT NULL
          AND waterfront_score IS NULL
    """))


def downgrade():
    conn = op.get_bind()

    for col in [
        "parcel_id", "address", "owner_name", "owner_address",
        "land_value", "building_value", "total_value", "lot_size_sqft",
        "zoning_code", "last_sale_date", "last_sale_price", "raw_data", "geometry",
    ]:
        conn.execute(sa.text(f"ALTER TABLE parcels DROP COLUMN IF EXISTS {col}"))

    conn.execute(sa.text("DROP INDEX IF EXISTS parcels_parcel_id_uidx"))

    for col in [
        "waterfront_score", "zoning_score", "price_score", "lot_size_score",
        "population_score", "traffic_score", "recency_score", "tier", "missing_metrics",
    ]:
        conn.execute(sa.text(f"ALTER TABLE deal_scores DROP COLUMN IF EXISTS {col}"))
