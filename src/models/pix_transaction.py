from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    func,
)

from models.base import Base


class PixTransaction(Base):
    __tablename__ = "pix_transaction"

    id = Column(String(200), primary_key=True)

    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_account_branch = Column(String(20), nullable=False)
    source_account_number = Column(String(50), nullable=False)
    source_account_opening_date = Column(DateTime(timezone=True), nullable=False)
    source_document_number = Column(String(14), nullable=False)

    destination_participant = Column(String(20), nullable=False)
    destination_account_branch = Column(String(20), nullable=False)
    destination_account_number = Column(String(50), nullable=False)
    destination_account_opening_date = Column(DateTime(timezone=True), nullable=False)
    destination_document_number = Column(String(14), nullable=False)

    source_device_id = Column(String(200), nullable=False)
    source_channel = Column(String(50), nullable=False)
    source_ip = Column(String(45), nullable=False)
    source_latitude = Column(Numeric(10, 7), nullable=True)
    source_longitude = Column(Numeric(10, 7), nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_pix_transaction_amount"),
        CheckConstraint(
            "source_latitude >= -90 AND source_latitude <= 90",
            name="chk_pix_transaction_latitude",
        ),
        CheckConstraint(
            "source_longitude >= -180 AND source_longitude <= 180",
            name="chk_pix_transaction_longitude",
        ),
        Index(
            "idx_pix_transaction_source_document_date",
            "source_document_number",
            "transaction_date",
        ),
        Index(
            "idx_pix_transaction_destination_document_date",
            "destination_document_number",
            "transaction_date",
        ),
        Index(
            "idx_pix_transaction_source_received_at",
            "source_document_number",
            "received_at",
        ),
        Index(
            "idx_pix_transaction_destination_received_at",
            "destination_document_number",
            "received_at",
        ),
        Index(
            "idx_pix_transaction_payer_payee",
            "source_document_number",
            "destination_document_number",
        ),
        Index(
            "idx_pix_transaction_device_date",
            "source_device_id",
            "transaction_date",
        ),
    )
