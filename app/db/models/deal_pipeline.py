"""Modèle pour deal_pipeline — remplace watchlist."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base

PIPELINE_STATUSES = [
    "spotted",
    "reviewing",
    "loi_submitted",
    "under_contract",
    "closed",
    "dead",
]


class DealPipelineItem(Base):
    __tablename__ = "deal_pipeline"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id = Column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="spotted")
    notes = Column(Text)
    assigned_to = Column(String)
    added_by = Column(String, nullable=False, default="demo")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
