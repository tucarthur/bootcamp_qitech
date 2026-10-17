from datetime import datetime
from decimal import Decimal

from database import Context
from models import PixTransaction


class PixTransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_id(self, transaction_id: str) -> PixTransaction | None:
        return self.session.query(PixTransaction).filter(PixTransaction.id == transaction_id).first()

    def create(
        self,
        payload: dict,
        transaction_date: datetime,
        source_account_opening_date: datetime,
        destination_account_opening_date: datetime,
    ) -> PixTransaction:
        source_account = payload["source_account"]
        destination_account = payload["destination_account"]
        source = payload["source"]

        transaction = PixTransaction(
            id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            source_account_branch=source_account["branch"],
            source_account_number=source_account["account_number"],
            source_account_opening_date=source_account_opening_date,
            source_document_number=source_account["owner"]["document_number"],
            destination_participant=destination_account["participant"],
            destination_account_branch=destination_account["branch"],
            destination_account_number=destination_account["account_number"],
            destination_account_opening_date=destination_account_opening_date,
            destination_document_number=destination_account["owner"]["document_number"],
            source_device_id=source["device_id"],
            source_channel=source["channel"],
            source_ip=source["ip"],
            source_latitude=Decimal(str(source["geolocation"]["latitude"])),
            source_longitude=Decimal(str(source["geolocation"]["longitude"])),
        )

        self.session.add(transaction)
        return transaction
