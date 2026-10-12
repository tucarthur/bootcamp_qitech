from models.ledger_entry import LedgerEntry
from models.transaction import Transaction


class TransactionDTO:
    @staticmethod
    def details(
        transaction: Transaction,
        source_account_key: str | None,
        destination_account_key: str | None,
        ledger_entries: list[tuple[LedgerEntry, str]],
    ) -> dict:
        return {
            "transaction_key": transaction.transaction_key,
            "type": transaction.transaction_type,
            "source_account_key": source_account_key,
            "destination_account_key": destination_account_key,
            "amount_cents": transaction.amount_cents,
            "fee_cents": transaction.fee_cents,
            "created_at": transaction.created_at.isoformat(),
            "ledger_entries": [
                {
                    "account_key": account_key,
                    "direction": entry.direction,
                    "kind": entry.kind,
                    "amount_cents": entry.amount_cents,
                    "balance_after_cents": entry.balance_after_cents,
                    "created_at": entry.created_at.isoformat(),
                }
                for entry, account_key in ledger_entries
            ],
        }