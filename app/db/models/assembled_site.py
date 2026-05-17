from sqlalchemy import Column, String, BigInteger, Numeric, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from geoalchemy2 import Geometry
import uuid

from app.db.base import Base


class AssembledSite(Base):
    """
    A group of contiguous parcels owned (effectively) by the same entity.
    Computed by assembly.py via PostGIS ST_DWithin + union-find.
    """
    __tablename__ = "assembled_sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_name_normalized = Column(String, nullable=False, index=True)
    parcel_ids = Column(JSONB, nullable=False)          # ["uuid1", "uuid2", ...]
    parcel_count = Column(Integer, nullable=False)
    total_land_value = Column(BigInteger)               # USD
    total_lot_size_sqft = Column(Numeric)
    county = Column(String)                              # county of the largest parcel
    geometry = Column(Geometry("GEOMETRY", srid=4326))  # ST_Union of constituents
    computed_at = Column(DateTime(timezone=True), server_default=func.now())
