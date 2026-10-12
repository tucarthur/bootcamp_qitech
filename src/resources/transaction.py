from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.transaction_controller import TransactionController
from utils.schema_handler import SchemaHandler


class TransactionResource:
    def on_get_by_key(self, transaction_key: str) -> JSONResponse:
        controller = TransactionController()
        transaction = controller.get_by_key(transaction_key)
        return JSONResponse(
            content=jsonable_encoder(transaction),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = TransactionController()
        transaction, created = controller.transfer(payload)
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(
            content=jsonable_encoder(transaction),
            status_code=status_code,
        )