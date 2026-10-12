from datetime import date
from typing import Optional
from uuid import uuid4

from database import Context
from models.customers import Customers


class CustomersRepository:
    
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create_customer(self, customer_data: dict) -> Customers:
        customer = Customers(
            customer_key=str(uuid4()),
            name=customer_data["name"],
            email=customer_data["email"],
            document_number=customer_data["document_number"],
            birthdate=date.fromisoformat(customer_data["birthdate"]),
        )

        self.session.add(customer)
        return customer

    def get_customer_by_document_number(self, document_number: str) -> Optional[Customers]:
        return self.session.query(Customers).filter(Customers.document_number == document_number).first()

    def get_customer_by_email(self, email: str) -> Optional[Customers]:
        return self.session.query(Customers).filter(Customers.email == email).first()

    def get_customer_by_key(self, customer_key: str) -> Optional[Customers]:
        return self.session.query(Customers).filter(Customers.customer_key == customer_key).first()

    def delete_customer(self, customer: Customers) -> None:
        self.session.delete(customer)











