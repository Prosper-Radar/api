"""Add water_bodies table for NHD Florida hydrography data

water_bodies is populated by running:
  python scripts/load_nhd_florida.py

Revision ID: 0002
Revises: 0001
Create Date: 2025-05-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "water_bodies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("nhd_id", sa.String(), unique=True),         # NHD permanent identifier
        sa.Column("name", sa.String()),                         # water body name (nullable)
        sa.Column("ftype", sa.Integer()),                       # NHD feature type (e.g. 390 = LakePond)
        sa.Column("geom", sa.Text(), nullable=False),           # converted below
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # Convert to real PostGIS geometry
    op.execute(
        "ALTER TABLE water_bodies "
        "ALTER COLUMN geom TYPE geometry(MULTIPOLYGON, 4326) "
        "USING ST_GeomFromEWKT(geom)"
    )

    # KNN-capable GIST index — used by <-> operator in scoring query
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_water_bodies_geom "
        "ON water_bodies USING GIST (geom)"
    )


def downgrade() -> None:
    op.drop_table("water_bodies")
