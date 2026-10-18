from sqlalchemy import Column, DateTime, LargeBinary, String, func

from models.base import Base


class PixPayerBehaviorProfile(Base):
    __tablename__ = "pix_payer_behavior_profile"

    source_document_number = Column(String(14), primary_key=True)
    history_snapshot = Column(LargeBinary, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )
