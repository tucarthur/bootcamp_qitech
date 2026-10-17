from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixTransactionAnalysisController


class PixTransactionAnalysisResource:
    def on_get_by_transaction_id(self, transaction_id: str) -> JSONResponse:
        controller = PixTransactionAnalysisController()
        analysis = controller.get_by_transaction_id(transaction_id)

        return JSONResponse(
            content=jsonable_encoder(analysis),
            status_code=http_status.HTTP_200_OK,
        )
