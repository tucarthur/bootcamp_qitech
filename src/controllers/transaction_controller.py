from sqlalchemy.exc import IntegrityError

from constants import TRANSFER_FEE_CENTS
from controllers.base_controller import BaseController
from dtos.account_dto import AccountDTO
from dtos.transaction_dto import TransactionDTO
from errors.base_error import NotFoundResource
from errors.custom_errors import IdempotencyConflict, InsufficientFunds, SameAccountTransfer
from repositories.account_repository import AccountRepository


class TransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)

    def get_by_key(self, transaction_key: str) -> dict:
        transaction = self.account_repository.get_transaction_by_key(transaction_key)
        if transaction is None:
            raise NotFoundResource()

        ledger_entries = self.account_repository.get_ledger_entries_for_transaction(
            transaction.id
        )
        source_account_key, destination_account_key = (
            self.account_repository.get_account_keys_for_transaction(transaction)
        )
        return TransactionDTO.details(
            transaction,
            source_account_key,
            destination_account_key,
            ledger_entries,
        )

    def transfer(self, payload: dict) -> tuple[dict, bool]:
        source_key = payload["source_account_key"]
        destination_key = payload["destination_account_key"]
        idempotency_key = payload["idempotency_key"]
        amount_cents = payload["amount_cents"]

        if source_key == destination_key:
            raise SameAccountTransfer(source_key)

        accounts = self.account_repository.get_accounts_by_keys_for_update(
            [source_key, destination_key]
        )
        if len(accounts) != 2:
            raise NotFoundResource()

        accounts_by_key = {account.account_key: account for account in accounts}
        source_account = accounts_by_key[source_key]
        destination_account = accounts_by_key[destination_key]
        source_account_id = source_account.id
        destination_account_id = destination_account.id

        existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
            idempotency_key
        )
        if existing_transaction is not None:
            return self._transfer_replay(
                existing_transaction,
                source_account_id,
                destination_account_id,
                idempotency_key,
                amount_cents,
            )

        total_debit = amount_cents + TRANSFER_FEE_CENTS
        if source_account.balance_cents < total_debit:
            raise InsufficientFunds(source_key, source_account.balance_cents, total_debit)

        try:
            transaction = self.account_repository.create_transfer(
                source_account,
                destination_account,
                idempotency_key,
                amount_cents,
                TRANSFER_FEE_CENTS,
            )
            response = AccountDTO.transaction_result(transaction)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing_transaction = self.account_repository.get_transaction_by_idempotency_key(
                idempotency_key
            )
            if existing_transaction is None:
                raise
            return self._transfer_replay(
                existing_transaction,
                source_account_id,
                destination_account_id,
                idempotency_key,
                amount_cents,
            )

        return response, True

    @staticmethod
    def _transfer_replay(
        transaction,
        source_account_id: int,
        destination_account_id: int,
        idempotency_key: str,
        amount_cents: int,
    ) -> tuple[dict, bool]:
        if (
            transaction.transaction_type != "TRANSFER"
            or transaction.source_account_id != source_account_id
            or transaction.destination_account_id != destination_account_id
            or transaction.amount_cents != amount_cents
        ):
            raise IdempotencyConflict(idempotency_key)

        return AccountDTO.transaction_result(transaction), False