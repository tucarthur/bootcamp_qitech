from datetime import datetime, timedelta
from decimal import Decimal

from database import Context
from models import PixTransaction
from models.pix_transaction_analysis import PixTransactionAnalysis
from sqlalchemy import and_, case, or_, text

from controllers.antifraud import POLICY, TransactionData
from repositories.antifraud_lock import normalize_document, payer_lock_key


class PixTransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_id(self, transaction_id: str) -> PixTransaction | None:
        return self.session.query(PixTransaction).filter(PixTransaction.id == transaction_id).first()

    def lock_for_analysis(
        self,
        transaction_id: str,
        source_document_number: str,
        source_device_id: str,
        destination_document_number: str,
    ) -> None:
        source_document_number = self._normalize_document(source_document_number)
        destination_document_number = self._normalize_document(destination_document_number)
        lock_keys = {
            f"pix-antifraud:transaction:{transaction_id}",
            payer_lock_key(source_document_number),
            f"pix-antifraud:device:{source_device_id}",
            f"pix-antifraud:payee:{destination_document_number}",
        }
        for lock_key in sorted(lock_keys):
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )

    def get_database_timestamp(self) -> datetime:
        return self.session.execute(text("SELECT clock_timestamp()")).scalar_one()

    def get_history_for_analysis(self, transaction: TransactionData) -> list[TransactionData]:
        history_cutoff = transaction.transaction_date - timedelta(
            days=POLICY.history_window_days
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
            .order_by(
                case(
                    (
                        PixTransaction.source_document_number
                        == transaction.source_document_number,
                        0,
                    ),
                    else_=1,
                )
            )
            .order_by(
                case(
                    (
                        and_(
                            PixTransaction.source_document_number
                            == transaction.source_document_number,
                            PixTransaction.destination_document_number
                            == transaction.destination_document_number,
                        ),
                        0,
                    ),
                    else_=1,
                )
            )
            .order_by(PixTransaction.transaction_date.desc())
            .order_by(PixTransaction.id.desc())
            .limit(POLICY.history_max_rows)
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
        received_at: datetime,
        source_account_opening_date: datetime,
        destination_account_opening_date: datetime,
    ) -> PixTransaction:
        source_account = payload["source_account"]
        destination_account = payload["destination_account"]
        source = payload["source"]
        geolocation = source.get("geolocation")

        transaction = PixTransaction(
            id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            received_at=received_at,
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
            source_latitude=Decimal(str(geolocation["latitude"]))
            if geolocation is not None
            else None,
            source_longitude=Decimal(str(geolocation["longitude"]))
            if geolocation is not None
            else None,
        )

        self.session.add(transaction)
        return transaction

    @staticmethod
    def to_data(transaction: PixTransaction, status: str | None = None) -> TransactionData:
        return TransactionData(
            id=transaction.id,
            amount=transaction.amount,
            transaction_date=transaction.transaction_date,
            received_at=transaction.received_at,
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
        received_at: datetime,
        source_account_opening_date: datetime,
        destination_account_opening_date: datetime,
    ) -> TransactionData:
        source_account = payload["source_account"]
        destination_account = payload["destination_account"]
        source = payload["source"]
        geolocation = source.get("geolocation")
        return TransactionData(
            id=payload["id"],
            amount=payload["amount"],
            transaction_date=transaction_date,
            received_at=received_at,
            source_document_number=PixTransactionRepository._normalize_document(
                source_account["owner"]["document_number"]
            ),
            source_account_opening_date=source_account_opening_date,
            destination_document_number=PixTransactionRepository._normalize_document(
                destination_account["owner"]["document_number"]
            ),
            destination_account_opening_date=destination_account_opening_date,
            source_device_id=source["device_id"],
            source_latitude=float(geolocation["latitude"])
            if geolocation is not None
            else None,
            source_longitude=float(geolocation["longitude"])
            if geolocation is not None
            else None,
        )

    @staticmethod
    def _normalize_document(document_number: str) -> str:
        return normalize_document(document_number)
