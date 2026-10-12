from database import Context
from models import Account, BankTransaction, LedgerEntry


class LedgerEntryRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(
        self,
        transaction: BankTransaction,
        account: Account,
        direction: str,
        kind: str,
        amount_cents: int,
        balance_after_cents: int
    ) -> LedgerEntry:

        entry = LedgerEntry()

        entry.transaction = transaction
        entry.account = account
        entry.direction = direction
        entry.kind = kind
        entry.amount_cents = amount_cents
        entry.balance_after_cents = balance_after_cents

        self.session.add(entry)

        return entry

    def list_by_account(
        self,
        account_id: int,
        limit: int,
        cursor: int | None = None
    ) -> list[LedgerEntry]:

        query = (
            self.session.query(LedgerEntry)
            .filter(LedgerEntry.account_id == account_id)
        )

        if cursor is not None:
            query = query.filter(
                LedgerEntry.id < cursor
            )

        query = query.order_by(
            LedgerEntry.id.desc()
        )

        return query.limit(limit + 1).all()

    def list_by_transaction(
        self,
        transaction_id: int
    ) -> list[LedgerEntry]:

        return (
            self.session.query(LedgerEntry)
            .filter(
                LedgerEntry.transaction_id == transaction_id
            )
            .order_by(LedgerEntry.id.asc())
            .all()
        )