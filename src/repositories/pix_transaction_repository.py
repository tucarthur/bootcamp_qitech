import json
import zlib
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from database import Context
from models import PixPayerBehaviorProfile, PixTransaction
from models.pix_transaction_analysis import PixTransactionAnalysis
from sqlalchemy import and_, case, or_, text

from controllers.antifraud import (
    ContextHistoryCounts,
    POLICY,
    TransactionData,
    TreeEvasionCredit,
)
from repositories.antifraud_lock import normalize_document, payer_lock_key


class PixTransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.history_source = "uninitialized"
        self.context_history_counts: ContextHistoryCounts | None = None
        self.tree_evasion_credits: list[TreeEvasionCredit] = []
        self._behavior_profile: PixPayerBehaviorProfile | None = None
        self._profile_snapshot: list[dict] = []

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

    def get_tree_evasion_credits(
        self,
        transaction: TransactionData,
    ) -> list[TreeEvasionCredit]:
        if len(transaction.destination_document_number) != POLICY.cpf_digits:
            self.tree_evasion_credits = []
            return self.tree_evasion_credits

        window = timedelta(seconds=POLICY.tree_evasion_window_seconds)
        received_at = transaction.received_at
        rows = self.session.execute(
            text(
                """
                SELECT
                    incoming.amount,
                    incoming.received_at,
                    COALESCE(SUM(outgoing.amount), 0) AS prior_outgoing_amount,
                    COALESCE(
                        ARRAY_AGG(DISTINCT outgoing.destination_document_number)
                            FILTER (WHERE outgoing.id IS NOT NULL),
                        ARRAY[]::VARCHAR[]
                    ) AS prior_cpf_documents
                FROM pix_transaction AS incoming
                JOIN pix_analysis AS incoming_analysis
                    ON incoming_analysis.transaction_id = incoming.id
                    AND incoming_analysis.status != 'rejected'
                LEFT JOIN (
                    SELECT
                        transfer.id,
                        transfer.amount,
                        transfer.received_at,
                        transfer.destination_document_number
                    FROM pix_transaction AS transfer
                    JOIN pix_analysis AS transfer_analysis
                        ON transfer_analysis.transaction_id = transfer.id
                        AND transfer_analysis.status != 'rejected'
                    WHERE transfer.source_document_number = :source_document_number
                        AND transfer.destination_document_number ~ '^[0-9]{11}$'
                        AND transfer.destination_document_number
                            != :source_document_number
                        AND transfer.received_at >= :window_cutoff
                        AND transfer.received_at < :received_at
                ) AS outgoing
                    ON outgoing.received_at >= incoming.received_at
                    AND outgoing.received_at < incoming.received_at
                        + make_interval(secs => :window_seconds)
                    AND outgoing.received_at < :received_at
                WHERE incoming.destination_document_number = :source_document_number
                    AND incoming.received_at
                        > :received_at - make_interval(secs => :window_seconds)
                    AND incoming.received_at < :received_at
                GROUP BY incoming.id, incoming.amount, incoming.received_at
                """
            ),
            {
                "source_document_number": transaction.source_document_number,
                "received_at": received_at,
                "window_cutoff": received_at - window,
                "window_seconds": POLICY.tree_evasion_window_seconds,
            },
        ).all()
        self.tree_evasion_credits = [
            TreeEvasionCredit(
                amount=row.amount,
                received_at=row.received_at,
                prior_outgoing_amount=row.prior_outgoing_amount,
                prior_cpf_documents=tuple(row.prior_cpf_documents),
            )
            for row in rows
        ]
        return self.tree_evasion_credits

    def get_history_for_analysis(self, transaction: TransactionData) -> list[TransactionData]:
        payer_document = transaction.source_document_number
        self._behavior_profile = (
            self.session.query(PixPayerBehaviorProfile)
            .filter(
                PixPayerBehaviorProfile.source_document_number == payer_document
            )
            .first()
        )

        if self._behavior_profile is None:
            self.history_source = "cold"
            history = self._query_history(transaction)
            self._profile_snapshot = self._load_payer_snapshot(transaction)
            return history

        self._profile_snapshot = self._decode_snapshot(
            self._behavior_profile.history_snapshot
        )
        snapshot_transactions = [
            self._from_snapshot(row) for row in self._profile_snapshot
        ]
        newest_snapshot_date = max(
            (item.transaction_date for item in snapshot_transactions),
            default=None,
        )
        if (
            newest_snapshot_date is not None
            and transaction.transaction_date <= newest_snapshot_date
        ):
            self.history_source = "out_of_order_fallback"
            history = self._query_history(transaction)
            self._profile_snapshot = self._merge_snapshots(
                self._profile_snapshot,
                self._payer_snapshot(history, payer_document),
            )
            return history

        self.history_source = "profile"
        recent_cutoff = transaction.transaction_date - timedelta(
            days=POLICY.history_window_days
        )
        self.context_history_counts = self._query_context_history_counts(transaction)
        payer_history = [
            item
            for item in snapshot_transactions
            if item.id != transaction.id and item.transaction_date < transaction.transaction_date
        ]
        payer_payee_history = self._query_history(
            transaction,
            payer_payee_only=True,
        )
        payer_by_id = {item.id: item for item in payer_history}
        payer_by_id.update({item.id: item for item in payer_payee_history})
        payer_history = sorted(
            payer_by_id.values(),
            key=lambda item: (
                item.destination_document_number == transaction.destination_document_number,
                item.transaction_date,
                item.id,
            ),
            reverse=True,
        )[: POLICY.history_max_rows]

        history = payer_history
        self._profile_snapshot = self._payer_snapshot(history, payer_document)
        return history

    def update_behavior_profile(
        self,
        transaction: TransactionData,
        status: str,
    ) -> None:
        profile = self._behavior_profile
        if profile is None:
            profile = PixPayerBehaviorProfile(
                source_document_number=transaction.source_document_number,
                history_snapshot=[],
            )
            self.session.add(profile)
            self._behavior_profile = profile

        current_transaction = replace(transaction, status=status)
        snapshot_by_id = {
            row["id"]: row
            for row in self._profile_snapshot
            if row["id"] != current_transaction.id
        }
        snapshot_by_id[current_transaction.id] = self._to_snapshot(current_transaction)
        retained = sorted(
            snapshot_by_id.values(),
            key=lambda row: (row["transaction_date"], row["id"]),
            reverse=True,
        )[: POLICY.history_max_rows]
        profile.history_snapshot = self._encode_snapshot(retained)

    def _query_history(
        self,
        transaction: TransactionData,
        *,
        payer_payee_only: bool = False,
        context_only: bool = False,
        recent_cutoff: datetime | None = None,
        limit: int = POLICY.history_max_rows,
    ) -> list[TransactionData]:
        history_cutoff = transaction.transaction_date - timedelta(
            days=POLICY.history_window_days
        )
        if payer_payee_only:
            query_filter = and_(
                PixTransaction.source_document_number
                == transaction.source_document_number,
                PixTransaction.destination_document_number
                == transaction.destination_document_number,
                PixTransaction.transaction_date < transaction.transaction_date,
                PixTransaction.id != transaction.id,
            )
        elif context_only:
            query_filter = and_(
                PixTransaction.source_document_number
                != transaction.source_document_number,
                PixTransaction.transaction_date
                >= (recent_cutoff or history_cutoff),
                PixTransaction.transaction_date < transaction.transaction_date,
                or_(
                    PixTransaction.source_device_id == transaction.source_device_id,
                    PixTransaction.destination_document_number
                    == transaction.destination_document_number,
                ),
            )
        else:
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
            query_filter = and_(
                PixTransaction.id != transaction.id,
                PixTransaction.transaction_date < transaction.transaction_date,
                or_(recent_history, all_time_payee_history),
            )

        query = self._history_query().filter(query_filter)
        if payer_payee_only:
            query = query.order_by(PixTransaction.transaction_date.desc()).order_by(
                PixTransaction.id.desc()
            )
        elif context_only:
            query = query.order_by(PixTransaction.transaction_date.desc()).order_by(
                PixTransaction.id.desc()
            )
        else:
            query = (
                query.order_by(
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
            )

        return [
            self._history_row_to_data(row)
            for row in query.limit(max(0, limit)).all()
        ]

    def _query_context_history_counts(
        self,
        transaction: TransactionData,
    ) -> ContextHistoryCounts:
        payee_window_cutoff = transaction.transaction_date - timedelta(
            hours=POLICY.mule_fan_in_window_hours
        )
        device_window_cutoff = transaction.transaction_date - timedelta(
            hours=POLICY.shared_device_window_hours
        )
        counts = self.session.execute(
            text(
                """
                SELECT
                    (
                        SELECT count(DISTINCT source_document_number)
                        FROM pix_transaction
                        WHERE destination_document_number = :destination_document_number
                            AND source_document_number != :source_document_number
                            AND transaction_date >= :payee_window_cutoff
                            AND transaction_date < :transaction_date
                    ) AS distinct_payee_payers,
                    (
                        SELECT count(DISTINCT source_document_number)
                        FROM pix_transaction
                        WHERE source_device_id = :source_device_id
                            AND source_document_number != :source_document_number
                            AND transaction_date >= :device_window_cutoff
                            AND transaction_date < :transaction_date
                    ) AS distinct_device_payers
                """
            ),
            {
                "destination_document_number": transaction.destination_document_number,
                "source_document_number": transaction.source_document_number,
                "source_device_id": transaction.source_device_id,
                "payee_window_cutoff": payee_window_cutoff,
                "device_window_cutoff": device_window_cutoff,
                "transaction_date": transaction.transaction_date,
            },
        ).one()
        return ContextHistoryCounts(
            distinct_payee_payers=counts.distinct_payee_payers,
            distinct_device_payers=counts.distinct_device_payers,
        )

    @classmethod
    def _payer_snapshot(
        cls,
        history: list[TransactionData],
        payer_document: str,
    ) -> list[dict]:
        payer_history = [
            item for item in history if item.source_document_number == payer_document
        ]
        payer_history.sort(
            key=lambda item: (item.transaction_date, item.id),
            reverse=True,
        )
        return [
            cls._to_snapshot(item)
            for item in payer_history[: POLICY.history_max_rows]
        ]

    def _load_payer_snapshot(self, transaction: TransactionData) -> list[dict]:
        rows = (
            self._history_query()
            .filter(
                PixTransaction.source_document_number
                == transaction.source_document_number,
                PixTransaction.id != transaction.id,
            )
            .order_by(PixTransaction.transaction_date.desc())
            .order_by(PixTransaction.id.desc())
            .limit(POLICY.history_max_rows)
            .all()
        )
        history = [self._history_row_to_data(row) for row in rows]
        return self._payer_snapshot(history, transaction.source_document_number)

    def _history_query(self):
        return self.session.query(
            PixTransaction.id,
            PixTransaction.amount,
            PixTransaction.transaction_date,
            PixTransaction.received_at,
            PixTransaction.source_document_number,
            PixTransaction.source_account_opening_date,
            PixTransaction.destination_document_number,
            PixTransaction.destination_account_opening_date,
            PixTransaction.source_device_id,
            PixTransaction.source_latitude,
            PixTransaction.source_longitude,
            PixTransactionAnalysis.status,
        ).outerjoin(
            PixTransactionAnalysis,
            PixTransactionAnalysis.transaction_id == PixTransaction.id,
        )

    @staticmethod
    def _history_row_to_data(row) -> TransactionData:
        return TransactionData(
            id=row[0],
            amount=row[1],
            transaction_date=row[2],
            received_at=row[3],
            source_document_number=row[4],
            source_account_opening_date=row[5],
            destination_document_number=row[6],
            destination_account_opening_date=row[7],
            source_device_id=row[8],
            source_latitude=float(row[9]) if row[9] is not None else None,
            source_longitude=float(row[10]) if row[10] is not None else None,
            status=row[11],
        )

    @staticmethod
    def _merge_snapshots(*snapshots: list[dict]) -> list[dict]:
        rows_by_id = {
            row["id"]: row
            for snapshot in snapshots
            for row in snapshot
        }
        return sorted(
            rows_by_id.values(),
            key=lambda row: (row["transaction_date"], row["id"]),
            reverse=True,
        )[: POLICY.history_max_rows]

    @staticmethod
    def _encode_snapshot(snapshot: list[dict]) -> bytes:
        payload = json.dumps(
            {"version": 1, "rows": snapshot},
            separators=(",", ":"),
        ).encode("utf-8")
        return zlib.compress(payload, level=3)

    @staticmethod
    def _decode_snapshot(snapshot: bytes | bytearray | memoryview) -> list[dict]:
        payload = json.loads(zlib.decompress(bytes(snapshot)).decode("utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("rows"), list):
            raise ValueError("Unsupported payer behavior profile format")
        return payload["rows"]

    @staticmethod
    def _to_snapshot(transaction: TransactionData) -> dict:
        return {
            "id": transaction.id,
            "amount": transaction.amount,
            "transaction_date": transaction.transaction_date.isoformat(),
            "received_at": transaction.received_at.isoformat(),
            "source_document_number": transaction.source_document_number,
            "source_account_opening_date": (
                transaction.source_account_opening_date.isoformat()
            ),
            "destination_document_number": transaction.destination_document_number,
            "destination_account_opening_date": (
                transaction.destination_account_opening_date.isoformat()
            ),
            "source_device_id": transaction.source_device_id,
            "source_latitude": transaction.source_latitude,
            "source_longitude": transaction.source_longitude,
            "status": transaction.status,
        }

    @staticmethod
    def _from_snapshot(row: dict) -> TransactionData:
        return TransactionData(
            id=row["id"],
            amount=row["amount"],
            transaction_date=datetime.fromisoformat(row["transaction_date"]),
            received_at=datetime.fromisoformat(row["received_at"]),
            source_document_number=row["source_document_number"],
            source_account_opening_date=datetime.fromisoformat(
                row["source_account_opening_date"]
            ),
            destination_document_number=row["destination_document_number"],
            destination_account_opening_date=datetime.fromisoformat(
                row["destination_account_opening_date"]
            ),
            source_device_id=row["source_device_id"],
            source_latitude=row["source_latitude"],
            source_longitude=row["source_longitude"],
            status=row["status"],
        )

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
