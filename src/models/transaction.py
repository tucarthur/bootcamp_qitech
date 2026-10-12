from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, Integer, String, func

from models.base import Base


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(Integer, primary_key=True)
    transaction_key = Column(CHAR(36), nullable=False, unique=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)
    transaction_type = Column("type", String(20), nullable=False)
    source_account_id = Column(Integer, ForeignKey("account.id"))
    destination_account_id = Column(Integer, ForeignKey("account.id"))
    amount_cents = Column(BigInteger, nullable=False)
    fee_cents = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
