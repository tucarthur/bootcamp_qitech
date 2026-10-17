from datetime import datetime, timedelta
from decimal import Decimal

from database import Context
from models import PixTransaction
from models.pix_transaction_analysis import PixTransactionAnalysis
from sqlalchemy import and_, or_

from controllers.antifraud import POLICY, TransactionData


class PixTransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_id(self, transaction_id: str) -> PixTransaction | None:
        return self.session.query(PixTransaction).filter(PixTransaction.id == transaction_id).first()

    def get_history_for_analysis(self, transaction: TransactionData) -> list[TransactionData]:
        history_cutoff = transaction.transaction_date - timedelta(
            days=POLICY.amount_median_window_days
        )
        recent_history = and_(
            PixTransaction.transaction_date >= history_cutoff,
            or_(
                PixTransaction.source_document_number == transaction.source_document_number,
                PixTransaction.source_device_id == transaction.source_device_id,
                PixTransaction.destination_document_number
                == transaction.destination_document_number,
            ),
        )
        all_time_payee_history = and_(
            PixTransaction.source_document_number == transaction.source_document_number,
            PixTransaction.destination_document_number
            == transaction.destination_document_number,
        )
        rows = (
            self.session.query(PixTransaction, PixTransactionAnalysis.status)
            .outerjoin(
                PixTransactionAnalysis,
                PixTransactionAnalysis.transaction_id == PixTransaction.id,
            )
            .filter(
                PixTransaction.id != transaction.id,
                PixTransaction.transaction_date < transaction.transaction_date,
                or_(recent_history, all_time_payee_history),
            )
            .order_by(PixTransaction.transaction_date.desc())
            .order_by(PixTransaction.id.desc())
            .all()
        )
        return [
            self.to_data(pix_transaction, status)
            for pix_transaction, status in rows
        ]

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
            source_document_number=self._normalize_document(
                source_account["owner"]["document_number"]
            ),
            destination_participant=destination_account["participant"],
            destination_account_branch=destination_account["branch"],
            destination_account_number=destination_account["account_number"],
            destination_account_opening_date=destination_account_opening_date,
            destination_document_number=self._normalize_document(
                destination_account["owner"]["document_number"]
            ),
            source_device_id=source["device_id"],
            source_channel=source["channel"],
            source_ip=source["ip"],
            source_latitude=Decimal(str(source["geolocation"]["latitude"])),
            source_longitude=Decimal(str(source["geolocation"]["longitude"])),
        )

        self.session.add(transaction)
        return transaction

    @staticmethod
    def to_data(transaction: PixTransaction, status: str | None = None) -> TransactionData:
        return TransactionData(
            id=transaction.id,
            amount=transaction.amount,
            transaction_date=transaction.transaction_date,
            source_document_number=transaction.source_document_number,
            source_account_opening_date=transaction.source_account_opening_date,
            destination_document_number=transaction.destination_document_number,
            destination_account_opening_date=transaction.destination_account_opening_date,
            source_device_id=transaction.source_device_id,
            source_latitude=float(transaction.source_latitude)
            if transaction.source_latitude is not None
            else None,
            source_longitude=float(transaction.source_longitude)
            if transaction.source_longitude is not None
            else None,
            status=status,
        )

    @staticmethod
    def from_payload(
        payload: dict,
        transaction_date: datetime,
        source_account_opening_date: datetime,
        destination_account_opening_date: datetime,
    ) -> TransactionData:
        source_account = payload["source_account"]
        destination_account = payload["destination_account"]
        source = payload["source"]
        return TransactionData(
            id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            source_document_number=PixTransactionRepository._normalize_document(
                source_account["owner"]["document_number"]
            ),
            source_account_opening_date=source_account_opening_date,
            destination_document_number=PixTransactionRepository._normalize_document(
                destination_account["owner"]["document_number"]
            ),
            destination_account_opening_date=destination_account_opening_date,
            source_device_id=source["device_id"],
            source_latitude=float(source["geolocation"]["latitude"]),
            source_longitude=float(source["geolocation"]["longitude"]),
        )

    @staticmethod
    def _normalize_document(document_number: str) -> str:
        return "".join(character for character in document_number if character.isdigit())
