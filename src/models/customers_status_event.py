from sqlalchemy import Column, ForeignKey, Integer, DateTime, func
from models.base import Base
from sqlalchemy.orm import relationship
from models import Customers, CustomersStatus


class CustomersStatusEvent(Base):
    __tablename__ = "customers_status_event"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey(Customers.id), nullable=False)
    status_id = Column(Integer, ForeignKey(CustomersStatus.id), nullable=False)
    event_datetime = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    customer = relationship(
        "Customers",
        foreign_keys=[customer_id],
        back_populates="status_events",
        lazy="selectin",
    )
    status = relationship("CustomersStatus", foreign_keys=[status_id], lazy="selectin")
