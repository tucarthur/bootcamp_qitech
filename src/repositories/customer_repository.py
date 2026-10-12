from datetime import date
from uuid import uuid4

from database import Context
from models import Customer


class CustomerRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, customer_data: dict) -> Customer:
        customer = Customer()

        customer.customer_key = uuid4()
        customer.name = customer_data["name"]
        customer.email = customer_data["email"]
        customer.document_number = customer_data["document_number"]
        customer.birthdate = date.fromisoformat(customer_data["birthdate"])

        self.session.add(customer)

        return customer

    def get_by_key(self, customer_key: str) -> Customer:
        return (
            self.session.query(Customer)
            .filter(Customer.customer_key == customer_key)
            .first()
        )

    def get_by_document_number(self, document_number: str) -> Customer:
        return (
            self.session.query(Customer)
            .filter(Customer.document_number == document_number)
            .first()
        )

    def get_by_email(self, email: str) -> Customer:
        return (
            self.session.query(Customer)
            .filter(Customer.email == email)
            .first()
        )