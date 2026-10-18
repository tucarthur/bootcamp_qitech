from sqlalchemy import func

from database import Context
from models import PixAccountBlacklist
from repositories.antifraud_lock import lock_payer, normalize_document


class PixAccountBlacklistRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def is_blacklisted(self, source_document_number: str) -> bool:
        normalized_document = normalize_document(source_document_number)
        return (
            self.session.query(PixAccountBlacklist.source_document_number)
            .filter(
                PixAccountBlacklist.source_document_number == normalized_document,
                PixAccountBlacklist.authenticated_at.is_(None),
            )
            .first()
            is not None
        )

    def blacklist_account(
        self,
        account_document_number: str,
        triggering_transaction_id: str,
    ) -> None:
        normalized_document = normalize_document(account_document_number)
        blacklist_entry = (
            self.session.query(PixAccountBlacklist)
            .filter(
                PixAccountBlacklist.source_document_number == normalized_document
            )
            .first()
        )
        if blacklist_entry is None:
            blacklist_entry = PixAccountBlacklist(
                source_document_number=normalized_document,
                triggering_transaction_id=triggering_transaction_id,
            )
            self.session.add(blacklist_entry)
            return

        blacklist_entry.triggering_transaction_id = triggering_transaction_id
        blacklist_entry.blacklisted_at = func.clock_timestamp()
        blacklist_entry.authenticated_at = None

    def clear_after_authentication(self, source_document_number: str) -> bool:
        """Clear an active blacklist after a trusted caller verifies authentication."""
        normalized_document = normalize_document(source_document_number)
        lock_payer(self.session, normalized_document)
        updated_count = (
            self.session.query(PixAccountBlacklist)
            .filter(
                PixAccountBlacklist.source_document_number == normalized_document,
                PixAccountBlacklist.authenticated_at.is_(None),
            )
            .update(
                {PixAccountBlacklist.authenticated_at: func.clock_timestamp()},
                synchronize_session="fetch",
            )
        )
        return updated_count > 0
