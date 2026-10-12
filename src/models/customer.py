from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class Customer(Base):
    __tablename__ = "customer"

    id = Column(Integer, primary_key=True)

    customer_key = Column(
        UUID(as_uuid=True),
        nullable=False
    )

    document_number = Column(
        String(11),
        nullable=False
    )

    email = Column(
        String(200),
        nullable=False
    )

    name = Column(
        String(200),
        nullable=False
    )

    birthdate = Column(
        Date,
        nullable=False
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("customer_key"),
        UniqueConstraint("document_number"),
        UniqueConstraint("email"),
    )