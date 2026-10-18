from datetime import datetime
from time import perf_counter

from sqlalchemy.exc import IntegrityError

from controllers.antifraud import POLICY, analyze
from controllers.base_controller import BaseController
from errors import InvalidPixTransactionTimestamp
from repositories import (
    PixAccountBlacklistRepository,
    PixTransactionAnalysisRepository,
    PixTransactionRepository,
)


class PixTransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_transaction_repository = PixTransactionRepository(self.context)
        self.pix_transaction_analysis_repository = PixTransactionAnalysisRepository(self.context)
        self.pix_account_blacklist_repository = PixAccountBlacklistRepository(self.context)

    def create(self, payload: dict) -> tuple[dict, bool]:
        request_started_at = perf_counter()
        transaction_id = payload["id"]
        transaction_date = self._parse_timestamp(payload["transaction_date"], "transaction_date")
        source_account_opening_date = self._parse_timestamp(
            payload["source_account"]["opening_date"],
            "source_account.opening_date",
        )
        destination_account_opening_date = self._parse_timestamp(
            payload["destination_account"]["opening_date"],
            "destination_account.opening_date",
        )

        lock_started_at = perf_counter()
        self.pix_transaction_repository.lock_for_analysis(
            transaction_id,
            payload["source_account"]["owner"]["document_number"],
            payload["source"]["device_id"],
            payload["destination_account"]["owner"]["document_number"],
        )
        lock_wait_ms = (perf_counter() - lock_started_at) * 1000

        existing_analysis = (
            self.pix_transaction_analysis_repository.get_by_transaction_id(transaction_id)
        )
        if existing_analysis is not None:
            return self._analysis_response(existing_analysis), False

        existing_transaction = self.pix_transaction_repository.get_by_id(transaction_id)
        if existing_transaction is None:
            received_at = self.pix_transaction_repository.get_database_timestamp()
            transaction_data = self.pix_transaction_repository.from_payload(
                payload,
                transaction_date,
                received_at,
                source_account_opening_date,
                destination_account_opening_date,
            )
        else:
            transaction_data = self.pix_transaction_repository.to_data(existing_transaction)

        history_started_at = perf_counter()
        history = self.pix_transaction_repository.get_history_for_analysis(transaction_data)
        tree_evasion_credits = (
            self.pix_transaction_repository.get_tree_evasion_credits(transaction_data)
        )
        history_ms = (perf_counter() - history_started_at) * 1000
        account_blacklisted = self.pix_account_blacklist_repository.is_blacklisted(
            transaction_data.source_document_number
        )
        analysis_started_at = perf_counter()
        decision = analyze(
            transaction_data,
            history,
            POLICY,
            account_blacklisted=account_blacklisted,
            context_history_counts=(
                self.pix_transaction_repository.context_history_counts
            ),
            tree_evasion_credits=tree_evasion_credits,
        )
        analysis_ms = (perf_counter() - analysis_started_at) * 1000

        persistence_started_at = perf_counter()
        if existing_transaction is None:
            self.pix_transaction_repository.create(
                payload,
                transaction_date,
                received_at,
                source_account_opening_date,
                destination_account_opening_date,
            )
        self.pix_transaction_repository.update_behavior_profile(
            transaction_data,
            decision["status"],
        )
        if decision["status"] == "rejected" and not account_blacklisted:
            self.pix_account_blacklist_repository.blacklist_account(
                transaction_data.source_document_number,
                transaction_id,
            )
        analysis = self.pix_transaction_analysis_repository.create(
            transaction_id,
            decision["status"],
            decision["metadata"],
        )

        commit_started_at = perf_counter()
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing_analysis = (
                self.pix_transaction_analysis_repository.get_by_transaction_id(transaction_id)
            )
            if existing_analysis is None:
                raise
            return self._analysis_response(existing_analysis), False
        commit_ms = (perf_counter() - commit_started_at) * 1000
        self.logger.info(
            "pix_antifraud_timing lock_wait_ms=%.2f history_ms=%.2f "
            "history_rows=%d history_source=%s analysis_ms=%.2f "
            "persistence_prepare_ms=%.2f commit_ms=%.2f total_ms=%.2f",
            lock_wait_ms,
            history_ms,
            len(history),
            self.pix_transaction_repository.history_source,
            analysis_ms,
            (commit_started_at - persistence_started_at) * 1000,
            commit_ms,
            (perf_counter() - request_started_at) * 1000,
        )

        return self._analysis_response(analysis), True

    @staticmethod
    def _analysis_response(analysis) -> dict:
        return {
            "key": str(analysis.key),
            "status": analysis.status,
            "metadata": analysis.analysis_metadata,
        }

    @staticmethod
    def _parse_timestamp(value: str, field_name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidPixTransactionTimestamp(field_name, value) from None

        if parsed.utcoffset() is None:
            raise InvalidPixTransactionTimestamp(field_name, value)

        return parsed
