from fastapi import Response
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CustomersController
from utils.schema_handler import SchemaHandler

class CustomersResource:
    










































































    @SchemaHandler.validate("post_customer.json")
    def on_post(self, payload: dict) -> JSONResponse:



        controller = CustomersController()
        customer = controller.create_customer(payload)

        return JSONResponse(
            content=jsonable_encoder(customer),
            status_code=http_status.HTTP_201_CREATED,
        )

    def on_get_by_key(self, customers_key: str) -> JSONResponse:
        controller = CustomersController()
        customer = controller.get_by_key(customers_key)

        return JSONResponse(
            content=jsonable_encoder(customer),
            status_code=http_status.HTTP_200_OK,
        )

    def on_delete_by_document(self, customer_document: str) -> Response:
        controller = CustomersController()
        controller.delete_by_document_number(customer_document)
        return Response(status_code=http_status.HTTP_204_NO_CONTENT)
