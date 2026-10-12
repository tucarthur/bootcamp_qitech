from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, func

from models.base import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transaction.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=False)
    direction = Column(String(10), nullable=False)
    kind = Column(String(20), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    balance_after_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())