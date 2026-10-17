from uuid import uuid4

from database import Context
from models import Account, Customer


class AccountRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, customer: Customer) -> Account:
        account = Account()
        account.account_key = uuid4()
        account.customer = customer

        self.session.add(account)

        return account

    def get_by_key(self, account_key: str) -> Account | None:
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .first()
        )
