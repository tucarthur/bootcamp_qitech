from uuid import uuid4

from database import Context
from models.account import Account
from models.customers import Customers
from models.ledger_entry import LedgerEntry
from models.transaction import Transaction


class AccountRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_customer_by_key(self, customer_key: str) -> Customers:
        return self.session.query(Customers).filter(Customers.customer_key == customer_key).first()

    def create_account(self, customer: Customers) -> Account:
        account = Account(account_key=str(uuid4()), customer_id=customer.id, balance_cents=0)
        self.session.add(account)
        return account

    def get_account_with_customer_by_key(self, account_key: str):
        return (
            self.session.query(Account, Customers)
            .join(Customers, Account.customer_id == Customers.id)
            .filter(Account.account_key == account_key)
            .first()
        )

    def get_accounts_by_customer_id(self, customer_id: int) -> list[Account]:
        return (
            self.session.query(Account)
            .filter(Account.customer_id == customer_id)
            .order_by(Account.id)
            .all()
        )

    def get_account_by_key_for_update(self, account_key: str) -> Account:
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .with_for_update()
            .first()
        )

    def get_accounts_by_keys_for_update(self, account_keys: list[str]) -> list[Account]:
        return (
            self.session.query(Account)
            .filter(Account.account_key.in_(account_keys))
            .order_by(Account.id)
            .with_for_update()
            .all()
        )

    def get_transaction_by_idempotency_key(self, idempotency_key: str) -> Transaction:
        return (
            self.session.query(Transaction)
            .filter(Transaction.idempotency_key == idempotency_key)
            .first()
        )

    def get_transaction_by_key(self, transaction_key: str) -> Transaction:
        return (
            self.session.query(Transaction)
            .filter(Transaction.transaction_key == transaction_key)
            .first()
        )

    def get_account_keys_for_transaction(
        self, transaction: Transaction
    ) -> tuple[str | None, str | None]:
        account_ids = [
            account_id
            for account_id in (transaction.source_account_id, transaction.destination_account_id)
            if account_id is not None
        ]
        account_keys = dict(
            self.session.query(Account.id, Account.account_key)
            .filter(Account.id.in_(account_ids))
            .all()
        )
        return (
            account_keys.get(transaction.source_account_id),
            account_keys.get(transaction.destination_account_id),
        )

    def get_ledger_entries_for_transaction(self, transaction_id: int):
        return (
            self.session.query(LedgerEntry, Account.account_key)
            .join(Account, LedgerEntry.account_id == Account.id)
            .filter(LedgerEntry.transaction_id == transaction_id)
            .order_by(LedgerEntry.id)
            .all()
        )

    def get_statement_page(
        self,
        account_id: int,
        cursor_id: int | None,
        page_size: int,
    ):
        query = (
            self.session.query(LedgerEntry, Transaction.transaction_key)
            .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
            .filter(LedgerEntry.account_id == account_id)
        )
        if cursor_id is not None:
            query = query.filter(LedgerEntry.id < cursor_id)

        return query.order_by(LedgerEntry.id.desc()).limit(page_size).all()

    def create_deposit(
        self,
        account: Account,
        idempotency_key: str,
        amount_cents: int,
    ) -> Transaction:
        balance_after_cents = account.balance_cents + amount_cents
        account.balance_cents = balance_after_cents

        transaction = Transaction(
            transaction_key=str(uuid4()),
            idempotency_key=idempotency_key,
            transaction_type="DEPOSIT",
            destination_account_id=account.id,
            amount_cents=amount_cents,
            fee_cents=0,
        )
        self.session.add(transaction)
        self.session.flush()

        self.session.add(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=account.id,
                direction="CREDIT",
                kind="PRINCIPAL",
                amount_cents=amount_cents,
                balance_after_cents=balance_after_cents,
            )
        )
        return transaction

    def create_withdrawal(
        self,
        account: Account,
        idempotency_key: str,
        amount_cents: int,
    ) -> Transaction:
        balance_after_cents = account.balance_cents - amount_cents
        account.balance_cents = balance_after_cents

        transaction = Transaction(
            transaction_key=str(uuid4()),
            idempotency_key=idempotency_key,
            transaction_type="WITHDRAWAL",
            source_account_id=account.id,
            amount_cents=amount_cents,
            fee_cents=0,
        )
        self.session.add(transaction)
        self.session.flush()

        self.session.add(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=account.id,
                direction="DEBIT",
                kind="PRINCIPAL",
                amount_cents=amount_cents,
                balance_after_cents=balance_after_cents,
            )
        )
        return transaction

    def create_transfer(
        self,
        source_account: Account,
        destination_account: Account,
        idempotency_key: str,
        amount_cents: int,
        fee_cents: int,
    ) -> Transaction:
        source_balance = source_account.balance_cents - amount_cents
        source_account.balance_cents = source_balance - fee_cents
        destination_balance = destination_account.balance_cents + amount_cents
        destination_account.balance_cents = destination_balance

        transaction = Transaction(
            transaction_key=str(uuid4()),
            idempotency_key=idempotency_key,
            transaction_type="TRANSFER",
            source_account_id=source_account.id,
            destination_account_id=destination_account.id,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
        )
        self.session.add(transaction)
        self.session.flush()

        entries = [
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=source_account.id,
                direction="DEBIT",
                kind="PRINCIPAL",
                amount_cents=amount_cents,
                balance_after_cents=source_balance,
            ),
        ]
        if fee_cents > 0:
            entries.append(
                LedgerEntry(
                    transaction_id=transaction.id,
                    account_id=source_account.id,
                    direction="DEBIT",
                    kind="FEE",
                    amount_cents=fee_cents,
                    balance_after_cents=source_balance - fee_cents,
                )
            )
        entries.append(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=destination_account.id,
                direction="CREDIT",
                kind="PRINCIPAL",
                amount_cents=amount_cents,
                balance_after_cents=destination_balance,
            )
        )
        self.session.add_all(entries)
        return transaction