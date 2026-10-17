from uuid import uuid4

from database import Context
from models import Account, BankTransaction


class BankTransactionRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        idempotency_key: str,
        transaction_type: str,
        amount_cents: int,
        source_account: Account | None = None,
        destination_account: Account | None = None,
        fee_cents: int = 0,
    ) -> BankTransaction:
        transaction = BankTransaction()
        transaction.transaction_key = uuid4()
        transaction.idempotency_key = idempotency_key
        transaction.type = transaction_type
        transaction.amount_cents = amount_cents
        transaction.fee_cents = fee_cents
        transaction.source_account = source_account
        transaction.destination_account = destination_account

        self.session.add(transaction)

        return transaction

    def get_by_idempotency_key(self, idempotency_key: str) -> BankTransaction | None:
        return (
            self.session.query(BankTransaction)
            .filter(BankTransaction.idempotency_key == idempotency_key)
            .first()
        )