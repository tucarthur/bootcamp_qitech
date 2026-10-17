from datetime import datetime

from controllers.base_controller import BaseController
from errors import DuplicatePixTransaction, InvalidPixTransactionTimestamp
from repositories import PixTransactionRepository


class PixTransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_transaction_repository = PixTransactionRepository(self.context)

    def create(self, payload: dict) -> dict:
        transaction_id = payload["id"]
        if self.pix_transaction_repository.get_by_id(transaction_id) is not None:
            raise DuplicatePixTransaction(transaction_id)

        transaction_date = self._parse_timestamp(payload["transaction_date"], "transaction_date")
        source_account_opening_date = self._parse_timestamp(
            payload["source_account"]["opening_date"],
            "source_account.opening_date",
        )
        destination_account_opening_date = self._parse_timestamp(
            payload["destination_account"]["opening_date"],
            "destination_account.opening_date",
        )

        self.pix_transaction_repository.create(
            payload,
            transaction_date,
            source_account_opening_date,
            destination_account_opening_date,
        )
        self.session.commit()

        return {"id": transaction_id}

    @staticmethod
    def _parse_timestamp(value: str, field_name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidPixTransactionTimestamp(field_name, value) from None

        if parsed.utcoffset() is None:
            raise InvalidPixTransactionTimestamp(field_name, value)

        return parsed
