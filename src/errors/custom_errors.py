from errors import QIException


class NotFoundCustomer(QIException):
    code = "QIT001001"

    def __init__(self, customer_key) -> None:
        title = "Customer not Found"
        http_status = 404
        description = f"Customer with key {customer_key} was not found."
        translation = f"O cliente com chave {customer_key} não foi encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDocumentNumber(QIException):
    







    code = "QIT001003"

    def __init__(self, document_number) -> None:
        title = "Invalid Document Number"
        http_status = 422
        description = f"The document number {document_number} is not a valid CPF."
        translation = "O CPF informado não é válido."
        super().__init__(title, self.code, http_status, description, translation)


class DuplicatedDocumentNumber(QIException):
    





    code = "QIT001004"

    def __init__(self, document_number) -> None:
        title = "Document Number already registered"
        http_status = 409
        description = f"There is already a customer with the document number {document_number}."
        translation = "Já existe um cadastro com este CPF."
        super().__init__(title, self.code, http_status, description, translation)


class DuplicatedEmail(QIException):
    code = "QIT001005"

    def __init__(self, email) -> None:
        title = "Email already registered"
        http_status = 409
        description = f"There is already an entity with the email {email}."
        translation = "Já existe um cadastro com este e-mail."
        super().__init__(title, self.code, http_status, description, translation)


class UnderageCustomer(QIException):
    code = "QIT001006"

    def __init__(self, age, minimum_age) -> None:
        title = "Customer is underage"
        http_status = 422
        description = f"The customer is {age} years old, and the minimum is {minimum_age}."
        translation = f"É preciso ter pelo menos {minimum_age} anos."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidBirthdate(QIException):
    







    code = "QIT001007"

    def __init__(self, birthdate) -> None:
        title = "Invalid Birthdate"
        http_status = 422
        description = f"The birthdate {birthdate} is not a real date."
        translation = "A data de nascimento informada não existe."
        super().__init__(title, self.code, http_status, description, translation)


class IdempotencyConflict(QIException):
    code = "QIT001008"

    def __init__(self, idempotency_key) -> None:
        title = "Idempotency key conflict"
        http_status = 409
        description = f"The idempotency key {idempotency_key} was already used with different content."
        translation = "A chave de idempotência já foi usada com conteúdo diferente."
        super().__init__(title, self.code, http_status, description, translation)


class InsufficientFunds(QIException):
    code = "QIT001009"

    def __init__(self, account_key: str, balance_cents: int, amount_cents: int) -> None:
        title = "Insufficient funds"
        http_status = 422
        description = (
            f"Account {account_key} has {balance_cents} cents, "
            f"which is insufficient for a debit of {amount_cents} cents."
        )
        translation = "Saldo insuficiente para realizar a operação."
        super().__init__(title, self.code, http_status, description, translation)


class SameAccountTransfer(QIException):
    code = "QIT001010"

    def __init__(self, account_key: str) -> None:
        title = "Invalid transfer"
        http_status = 422
        description = f"Source and destination account cannot be the same: {account_key}."
        translation = "A conta de origem e destino devem ser diferentes."
        super().__init__(title, self.code, http_status, description, translation)
