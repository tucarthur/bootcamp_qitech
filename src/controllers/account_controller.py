import base64
import binascii

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos.account_dto import AccountDTO
from errors.base_error import InvalidParameter, NotFoundResource
from errors.custom_errors import IdempotencyConflict, InsufficientFunds
from repositories.account_repository import AccountRepository


class AccountController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)

    def create_account(self, customer_key: str) -> dict:
        customer = self.account_repository.get_customer_by_key(customer_key)
        if customer is None:
            raise NotFoundResource()

        account = self.account_repository.create_account(customer)
        self.session.commit()
        return AccountDTO.only_account_key(account)

    def get_by_key(self, account_key: str) -> dict:
        account_and_customer = self.account_repository.get_account_with_customer_by_key(account_key)
        if account_and_customer is None:
            raise NotFoundResource()

        account, customer = account_and_customer
        return AccountDTO.account_details(account, customer.customer_key)

    def get_by_customer_key(self, customer_key: str) -> dict:
        customer = self.account_repository.get_customer_by_key(customer_key)
        if customer is None:
            raise NotFoundResource()

        accounts = self.account_repository.get_accounts_by_customer_id(customer.id)
        return AccountDTO.accounts_for_customer(customer.customer_key, accounts)

    def get_statement(self, account_key: str, limit: int, cursor: str | None) -> dict:
        account_and_customer = self.account_repository.get_account_with_customer_by_key(account_key)
        if account_and_customer is None:
            raise NotFoundResource()

        account, _ = account_and_customer
        cursor_id = self._decode_statement_cursor(cursor) if cursor is not None else None
        rows = self.account_repository.get_statement_page(account.id, cursor_id, limit + 1)
        is_last_page = len(rows) <= limit
        if not is_last_page:
            rows = rows[:limit]

        data = [
            AccountDTO.statement_entry(entry, transaction_key)
            for entry, transaction_key in rows
        ]
        next_cursor = None
        if not is_last_page and rows:
            next_cursor = self._encode_statement_cursor(rows[-1][0].id)

        return {
            "data": data,
            "next_cursor": next_cursor,
            "is_last_page": is_last_page,
        }

    @staticmethod
    def _encode_statement_cursor(entry_id: int) -> str:
        encoded = base64.urlsafe_b64encode(str(entry_id).encode("ascii"))
        return encoded.decode("ascii").rstrip("=")

    @staticmethod
    def _decode_statement_cursor(cursor: str) -> int:
        try:
            padding = "=" * (-len(cursor) % 4)
            decoded = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
            decoded_id = decoded.decode("ascii")
            entry_id = int(decoded_id)
            if entry_id < 1 or str(entry_id) != decoded_id:
                raise ValueError
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise InvalidParameter("cursor is malformed") from None

        return entry_id

    def deposit(self, account_key: str, payload: dict) -> tuple[dict, bool]:
        account = self.account_repository.get_account_by_key_for_update(account_key)
        if account is None:
            raise NotFoundResource()

        idempotency_key = payload["idempotency_key"]
        amount_cents = payload["amount_cents"]
        existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
            idempotency_key
        )
        if existing_transaction is not None:
            return self._transaction_replay(
                existing_transaction, account, idempotency_key, amount_cents, "DEPOSIT"
            )

        try:
            transaction = self.account_repository.create_deposit(
                account, idempotency_key, amount_cents
            )
            deposit_response = AccountDTO.transaction_result(transaction)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
                idempotency_key
            )
            if existing_transaction is None:
                raise
            return self._transaction_replay(
                existing_transaction, account, idempotency_key, amount_cents, "DEPOSIT"
            )

        return deposit_response, True

    def withdraw(self, account_key: str, payload: dict) -> tuple[dict, bool]:
        account = self.account_repository.get_account_by_key_for_update(account_key)
        if account is None:
            raise NotFoundResource()

        idempotency_key = payload["idempotency_key"]
        amount_cents = payload["amount_cents"]
        existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
            idempotency_key
        )
        if existing_transaction is not None:
            return self._transaction_replay(
                existing_transaction, account, idempotency_key, amount_cents, "WITHDRAWAL"
            )

        if account.balance_cents < amount_cents:
            raise InsufficientFunds(account_key, account.balance_cents, amount_cents)

        try:
            transaction = self.account_repository.create_withdrawal(
                account, idempotency_key, amount_cents
            )
            withdrawal_response = AccountDTO.transaction_result(transaction)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
                idempotency_key
            )
            if existing_transaction is None:
                raise
            return self._transaction_replay(
                existing_transaction, account, idempotency_key, amount_cents, "WITHDRAWAL"
            )

        return withdrawal_response, True

    @staticmethod
    def _transaction_replay(
        transaction,
        account,
        idempotency_key: str,
        amount_cents: int,
        transaction_type: str,
    ) -> tuple[dict, bool]:
        account_id = (
            transaction.destination_account_id
            if transaction_type == "DEPOSIT"
            else transaction.source_account_id
        )
        if (
            transaction.transaction_type != transaction_type
            or account_id != account.id
            or transaction.amount_cents != amount_cents
        ):
            raise IdempotencyConflict(idempotency_key)

        return AccountDTO.transaction_result(transaction), False