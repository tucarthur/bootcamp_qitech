from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func
)
from sqlalchemy.orm import relationship

from models.base import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"

    id = Column(
        BigInteger,
        primary_key=True
    )

    transaction_id = Column(
        Integer,
        ForeignKey("bank_transaction.id"),
        nullable=False
    )

    account_id = Column(
        Integer,
        ForeignKey("account.id"),
        nullable=False
    )

    direction = Column(
        String(10),
        nullable=False
    )

    kind = Column(
        String(20),
        nullable=False
    )

    amount_cents = Column(
        BigInteger,
        nullable=False
    )

    balance_after_cents = Column(
        BigInteger,
        nullable=False
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    transaction = relationship(
        "BankTransaction",
        foreign_keys=[transaction_id],
        lazy="selectin"
    )

    account = relationship(
        "Account",
        foreign_keys=[account_id],
        lazy="selectin"
    )