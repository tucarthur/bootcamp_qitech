from uuid import uuid4

from database import Context
from models import PixTransactionAnalysis


class PixTransactionAnalysisRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_transaction_id(self, transaction_id: str) -> PixTransactionAnalysis | None:
        return (
            self.session.query(PixTransactionAnalysis)
            .filter(PixTransactionAnalysis.transaction_id == transaction_id)
            .first()
        )

    def create(self, transaction_id: str, status: str, metadata: dict) -> PixTransactionAnalysis:
        analysis = PixTransactionAnalysis(
            key=uuid4(),
            transaction_id=transaction_id,
            status=status,
            analysis_metadata=metadata,
        )
        self.session.add(analysis)
        return analysis
