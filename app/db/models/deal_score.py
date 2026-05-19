from sqlalchemy import Column, Numeric, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base
from app.scoring.version import MODEL_VERSION


class DealScore(Base):
    __tablename__ = "deal_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id = Column(UUID(as_uuid=True), ForeignKey("parcels.id"), nullable=False)
    waterfront_score = Column(Numeric(5, 2))
    zoning_score = Column(Numeric(5, 2))
    price_score = Column(Numeric(5, 2))
    lot_size_score = Column(Numeric(5, 2))
    population_score = Column(Numeric(5, 2))
    traffic_score = Column(Numeric(5, 2))
    recency_score = Column(Numeric(5, 2))
    total_score = Column(Numeric(5, 2))
    tier = Column(String(1))  # 'A' | 'B' | 'C'
    model_version = Column(String, nullable=False, server_default=MODEL_VERSION)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    parcel = relationship("Parcel", backref="scores")
