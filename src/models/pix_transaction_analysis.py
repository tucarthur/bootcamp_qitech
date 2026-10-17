from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base


class PixTransactionAnalysis(Base):
    __tablename__ = "pix_transaction_analysis"

    key = Column(UUID(as_uuid=True), primary_key=True)
    transaction_id = Column(
        String(200),
        ForeignKey("pix_transaction.id"),
        nullable=False,
    )
    status = Column(String(50), nullable=False)
    analysis_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("transaction_id"),
    )
