"""Initial schema — parcels, deal_scores

Revision ID: 0001
Revises:
Create Date: 2025-05-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "parcels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", sa.String(), nullable=False, unique=True),
        sa.Column("county", sa.String(), nullable=False),
        sa.Column("owner_name", sa.String()),
        sa.Column("owner_address", sa.String()),
        sa.Column("address", sa.String()),
        sa.Column("land_value", sa.BigInteger()),
        sa.Column("building_value", sa.BigInteger()),
        sa.Column("total_value", sa.BigInteger()),
        sa.Column("lot_size_sqft", sa.Numeric()),
        sa.Column("zoning_code", sa.String()),
        sa.Column("last_sale_date", sa.Date()),
        sa.Column("last_sale_price", sa.BigInteger()),
        # PostGIS geometry column: POLYGON in WGS-84
        sa.Column(
            "geometry",
            sa.Text(),   # stored as WKT; PostGIS converts on INSERT via ST_GeomFromEWKT
        ),
        sa.Column("raw_data", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )

    # Convert geometry column to a proper PostGIS GEOMETRY type after creation
    op.execute(
        "ALTER TABLE parcels "
        "ALTER COLUMN geometry TYPE geometry(POLYGON, 4326) "
        "USING ST_GeomFromEWKT(geometry)"
    )

    # GIST index for spatial queries
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_parcels_geometry "
        "ON parcels USING GIST (geometry)"
    )

    op.create_table(
        "deal_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parcel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parcels.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,  # one score row per parcel
        ),
        sa.Column("waterfront_score", sa.Numeric(5, 2)),
        sa.Column("zoning_score", sa.Numeric(5, 2)),
        sa.Column("price_score", sa.Numeric(5, 2)),
        sa.Column("lot_size_score", sa.Numeric(5, 2)),
        sa.Column("population_score", sa.Numeric(5, 2)),
        sa.Column("traffic_score", sa.Numeric(5, 2)),
        sa.Column("recency_score", sa.Numeric(5, 2)),
        sa.Column("total_score", sa.Numeric(5, 2)),
        sa.Column("tier", sa.String(1)),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("deal_scores")
    op.drop_table("parcels")
