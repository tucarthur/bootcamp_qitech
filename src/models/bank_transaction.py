from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class BankTransaction(Base):
    __tablename__ = "bank_transaction"

    id = Column(Integer, primary_key=True)

    transaction_key = Column(
        UUID(as_uuid=True),
        nullable=False
    )

    idempotency_key = Column(
        String(200),
        nullable=False
    )

    type = Column(
        String(20),
        nullable=False
    )

    source_account_id = Column(
        Integer,
        ForeignKey("account.id"),
        nullable=True
    )

    destination_account_id = Column(
        Integer,
        ForeignKey("account.id"),
        nullable=True
    )

    amount_cents = Column(
        BigInteger,
        nullable=False
    )

    fee_cents = Column(
        BigInteger,
        nullable=False,
        default=0
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("transaction_key"),
        UniqueConstraint("idempotency_key"),
    )

    source_account = relationship(
        "Account",
        foreign_keys=[source_account_id],
        lazy="selectin"
    )

    destination_account = relationship(
        "Account",
        foreign_keys=[destination_account_id],
        lazy="selectin"
    )