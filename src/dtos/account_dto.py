from typing import List

from models.account import Account
from models.ledger_entry import LedgerEntry
from models.transaction import Transaction


class AccountDTO:
    @staticmethod
    def only_account_key(account: Account) -> dict:
        return {"account_key": account.account_key}

    @staticmethod
    def account_details(account: Account, customer_key: str) -> dict:
        return {
            "account_key": account.account_key,
            "customer_key": customer_key,
            "balance_cents": account.balance_cents,
            "created_at": account.created_at.isoformat(),
        }

    @staticmethod
    def accounts_for_customer(customer_key: str, accounts: List[Account]) -> dict:
        return {
            "customer_key": customer_key,
            "accounts": [
                {
                    "account_key": account.account_key,
                    "balance_cents": account.balance_cents,
                    "created_at": account.created_at.isoformat(),
                }
                for account in accounts
            ],
        }

    @staticmethod
    def transaction_result(transaction: Transaction) -> dict:
        return {
            "transaction_key": transaction.transaction_key,
            "amount_cents": transaction.amount_cents,
            "fee_cents": transaction.fee_cents,
        }

    @staticmethod
    def statement_entry(entry: LedgerEntry, transaction_key: str) -> dict:
        return {
            "transaction_key": transaction_key,
            "direction": entry.direction,
            "kind": entry.kind,
            "amount_cents": entry.amount_cents,
            "balance_after_cents": entry.balance_after_cents,
            "created_at": entry.created_at.isoformat(),
        }