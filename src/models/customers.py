from sqlalchemy import CHAR, Column, Date, DateTime, Integer, String, UniqueConstraint, func
from models.base import Base


class Customers(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    customer_key = Column(CHAR(36), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    document_number = Column(CHAR(14), nullable=False)
    birthdate = Column(Date, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("customer_key"),
        UniqueConstraint("document_number"),
        UniqueConstraint("email"),
    )








