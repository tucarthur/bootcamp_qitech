from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class Account(Base):
    __tablename__ = "account"

    id = Column(Integer, primary_key=True)

    account_key = Column(
        UUID(as_uuid=True),
        nullable=False
    )

    customer_id = Column(
        Integer,
        ForeignKey("customer.id"),
        nullable=False
    )

    balance_cents = Column(
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
        UniqueConstraint("account_key"),
    )

    customer = relationship(
        "Customer",
        foreign_keys=[customer_id],
        lazy="selectin"
    )