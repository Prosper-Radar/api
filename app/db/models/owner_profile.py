from sqlalchemy import Column, String, Date, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

from app.db.base import Base


class OwnerProfile(Base):
    """
    Skip-trace result for a parcel owner — fetched from Florida Sunbiz
    and/or OpenCorporates. One row per (parcel, scrape run).
    """
    __tablename__ = "owner_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id = Column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_name_raw = Column(String)
    owner_name_normalized = Column(String, index=True)

    # Entity metadata from Sunbiz / OpenCorporates
    entity_type = Column(String)        # "LLC" | "CORP" | "INDIVIDUAL" | "TRUST" etc.
    entity_status = Column(String)      # "ACTIVE" | "INACTIVE" | "DISSOLVED"
    filing_date = Column(Date)
    registered_agent = Column(String)
    principal_address = Column(String)

    # Officers / beneficial owners as JSON array
    # [{"name": "...", "title": "...", "address": "..."}, ...]
    officers = Column(JSONB, default=list)

    source = Column(String)             # "sunbiz" | "opencorporates" | "manual"
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
