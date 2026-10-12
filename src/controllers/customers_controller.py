from datetime import date

from controllers.base_controller import BaseController
from dtos.customers_dto import CustomersDTO
from errors import (
    DuplicatedDocumentNumber,
    DuplicatedEmail,
    InvalidBirthdate,
    InvalidDocumentNumber,
    NotFoundCustomer,
    UnderageCustomer,
)
from errors.base_error import NotFoundResource
from repositories.customers_repository import CustomersRepository
from utils.document_number import is_valid_cpf




MINIMUM_AGE = 18
class CustomersController(BaseController):
    

    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomersRepository(self.context)

    def create_customer(self, customer_data: dict) -> dict:
        document_number = customer_data["document_number"]
        email = customer_data["email"]
        birthdate = self._parse_birthdate(customer_data["birthdate"])

        if not is_valid_cpf(document_number):
            raise InvalidDocumentNumber(document_number)

        if self.customer_repository.get_customer_by_document_number(document_number) is not None:
            raise DuplicatedDocumentNumber(document_number)

        if self.customer_repository.get_customer_by_email(email) is not None:
            raise DuplicatedEmail(email)

        age = self._age_in_years(birthdate)
        if age < MINIMUM_AGE:
            raise UnderageCustomer(age, MINIMUM_AGE)

        customer = self.customer_repository.create_customer(customer_data)
        self.session.commit()

        return CustomersDTO.only_customer_key(customer)

    def get_by_key(self, customer_key: str) -> dict:
        self.logger.debug(f"Buscando a entidade de chave {customer_key}")

        customer = self.customer_repository.get_customer_by_key(customer_key)

        if customer is None:
            raise NotFoundCustomer(customer_key)

        return CustomersDTO.only_customer_key(customer)

    def delete_by_document_number(self, customer_document: str) -> None:
        customer = self.customer_repository.get_customer_by_document_number(customer_document)

        if customer is None:
            raise NotFoundResource()

        self.customer_repository.delete_customer(customer)
        self.session.commit()

    def _parse_birthdate(self, raw_birthdate: str) -> date:
        






        try:
            return date.fromisoformat(raw_birthdate)
        except ValueError:
            raise InvalidBirthdate(raw_birthdate)

    def _age_in_years(self, birthdate: date) -> int:
        today = date.today()
        age = today.year - birthdate.year



        if (today.month, today.day) < (birthdate.month, birthdate.day):
            age = age - 1

        return age
