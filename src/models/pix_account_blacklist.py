from sqlalchemy import Column, DateTime, ForeignKey, String, func

from models.base import Base


class PixAccountBlacklist(Base):
    __tablename__ = "pix_account_blacklist"

    source_document_number = Column(String(14), primary_key=True)
    triggering_transaction_id = Column(
        String(200),
        ForeignKey("pix_transaction.id"),
        nullable=False,
    )
    blacklisted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    authenticated_at = Column(DateTime(timezone=True), nullable=True)
