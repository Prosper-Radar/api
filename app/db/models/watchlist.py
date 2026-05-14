from sqlalchemy import Column, String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id = Column(UUID(as_uuid=True), ForeignKey("parcels.id"), nullable=False)
    added_by = Column(String)
    notes = Column(Text)
    status = Column(String, default="watching")  # watching | contacted | LOI | closed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
