from sqlalchemy import Column, String, BigInteger, Numeric, Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
import uuid

from app.db.base import Base


class Parcel(Base):
    __tablename__ = "parcels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id = Column(String, unique=True, nullable=False)
    county = Column(String, nullable=False)  # 'miami-dade' | 'hillsborough' | 'broward' | 'palm-beach'
    owner_name = Column(String)
    owner_address = Column(String)
    address = Column(String)
    land_value = Column(BigInteger)
    building_value = Column(BigInteger)
    total_value = Column(BigInteger)
    lot_size_sqft = Column(Numeric)
    zoning_code = Column(String)
    last_sale_date = Column(Date)
    last_sale_price = Column(BigInteger)
    geometry = Column(Geometry("POLYGON", srid=4326))
    raw_data = Column(Text)  # original JSON from source
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
