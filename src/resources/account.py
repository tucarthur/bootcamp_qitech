from fastapi import Request, status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.account_controller import AccountController
from utils.schema_handler import SchemaHandler


class AccountResource:
    DEFAULT_STATEMENT_LIMIT = 10

    @SchemaHandler.validate("post_account.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = AccountController()
        account = controller.create_account(payload["customer_key"])
        return JSONResponse(
            content=jsonable_encoder(account),
            status_code=http_status.HTTP_201_CREATED,
        )

    def on_get_by_key(self, account_key: str) -> JSONResponse:
        controller = AccountController()
        account = controller.get_by_key(account_key)
        return JSONResponse(
            content=jsonable_encoder(account),
            status_code=http_status.HTTP_200_OK,
        )

    def on_get_by_customer_key(self, customer_key: str) -> JSONResponse:
        controller = AccountController()
        accounts = controller.get_by_customer_key(customer_key)
        return JSONResponse(
            content=jsonable_encoder(accounts),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate_query_params("get_statement.json")
    def on_get_statement(self, account_key: str, request: Request) -> JSONResponse:
        query_params = request.query_params
        limit = int(query_params.get("limit", self.DEFAULT_STATEMENT_LIMIT))
        cursor = query_params.get("cursor")

        controller = AccountController()
        statement = controller.get_statement(account_key, limit, cursor)
        response = {"limit": limit, **statement}
        return JSONResponse(
            content=jsonable_encoder(response),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_deposit.json")
    def on_post_deposit(self, account_key: str, payload: dict) -> JSONResponse:
        controller = AccountController()
        deposit, created = controller.deposit(account_key, payload)
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(
            content=jsonable_encoder(deposit),
            status_code=status_code,
        )

    @SchemaHandler.validate("post_withdrawal.json")
    def on_post_withdrawal(self, account_key: str, payload: dict) -> JSONResponse:
        controller = AccountController()
        withdrawal, created = controller.withdraw(account_key, payload)
        status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return JSONResponse(
            content=jsonable_encoder(withdrawal),
            status_code=status_code,
        )