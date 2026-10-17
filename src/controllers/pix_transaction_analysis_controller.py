from controllers.base_controller import BaseController
from errors import NotFoundPixTransactionAnalysis
from repositories import PixTransactionAnalysisRepository


class PixTransactionAnalysisController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_transaction_analysis_repository = PixTransactionAnalysisRepository(self.context)

    def get_by_transaction_id(self, transaction_id: str) -> dict:
        analysis = self.pix_transaction_analysis_repository.get_by_transaction_id(transaction_id)
        if analysis is None:
            raise NotFoundPixTransactionAnalysis(transaction_id)

        return {
            "key": analysis.key,
            "status": analysis.status,
            "metadata": analysis.analysis_metadata,
        }
