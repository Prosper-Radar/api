"""Add assembled_sites and owner_profiles tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assembled_sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_name_normalized", sa.String(), nullable=False),
        sa.Column("parcel_ids", postgresql.JSONB(), nullable=False),
        sa.Column("parcel_count", sa.Integer(), nullable=False),
        sa.Column("total_land_value", sa.BigInteger()),
        sa.Column("total_lot_size_sqft", sa.Numeric()),
        sa.Column("county", sa.String()),
        sa.Column("geometry", sa.Text()),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "ALTER TABLE assembled_sites "
        "ALTER COLUMN geometry TYPE geometry(GEOMETRY, 4326) "
        "USING ST_GeomFromEWKT(geometry)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_assembled_sites_owner "
        "ON assembled_sites (owner_name_normalized)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_assembled_sites_geom "
        "ON assembled_sites USING GIST (geometry)"
    )

    op.create_table(
        "owner_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parcel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parcels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_name_raw", sa.String()),
        sa.Column("owner_name_normalized", sa.String()),
        sa.Column("entity_type", sa.String()),
        sa.Column("entity_status", sa.String()),
        sa.Column("filing_date", sa.Date()),
        sa.Column("registered_agent", sa.String()),
        sa.Column("principal_address", sa.String()),
        sa.Column("officers", postgresql.JSONB(), server_default="[]"),
        sa.Column("source", sa.String()),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_profiles_parcel "
        "ON owner_profiles (parcel_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_profiles_name "
        "ON owner_profiles (owner_name_normalized)"
    )


def downgrade() -> None:
    op.drop_table("owner_profiles")
    op.drop_table("assembled_sites")
