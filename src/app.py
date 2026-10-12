from fastapi import FastAPI

from constants import check_variables
from errors import register_error_handlers
from errors.base_error import error_verification
from middlewares import (
    register_internal_token_middleware,
    register_request_context_middleware,
    register_request_logger_middleware,
    register_session_manager_middleware,
)
from resources import (
    AccountResource,
    CustomersResource,
    HealthCheckResource,
    TransactionResource,
)
from utils.logger import setup_logging


def create_app() -> FastAPI:
    

















    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )































































    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)


















    health_check_resource = HealthCheckResource()
    customers_resource = CustomersResource()
    account_resource = AccountResource()
    transaction_resource = TransactionResource()

    application.add_api_route(
        "/", 
        health_check_resource.on_get_home, 
        methods=["GET"]
    )
    application.add_api_route(
        "/health_check",
        health_check_resource.on_get_health_check,
        methods=["GET"]
    )

    application.add_api_route(
        "/customers",
        customers_resource.on_post,
        methods=["POST"],
    )
    application.add_api_route(
        "/account",
        account_resource.on_post,
        methods=["POST"],
    )
    application.add_api_route(
        "/account/{account_key}",
        account_resource.on_get_by_key,
        methods=["GET"],
    )
    application.add_api_route(
        "/account/{account_key}/deposit",
        account_resource.on_post_deposit,
        methods=["POST"],
    )
    application.add_api_route(
        "/account/{account_key}/withdrawal",
        account_resource.on_post_withdrawal,
        methods=["POST"],
    )
    application.add_api_route(
        "/account/{account_key}/statement",
        account_resource.on_get_statement,
        methods=["GET"],
    )
    application.add_api_route(
        "/transaction",
        transaction_resource.on_post,
        methods=["POST"],
    )
    application.add_api_route(
        "/transaction/{transaction_key}",
        transaction_resource.on_get_by_key,
        methods=["GET"],
    )
    application.add_api_route(
        "/accounts/{customer_key}",
        account_resource.on_get_by_customer_key,
        methods=["GET"],
    )
    application.add_api_route(
        "/customers/{customers_key}",
        customers_resource.on_get_by_key,
        methods=["GET"],
    )
    application.add_api_route(
        "/customers/{customer_document}",
        customers_resource.on_delete_by_document,
        methods=["DELETE"],
    )

    register_error_handlers(application)

    return application


def main() -> FastAPI:


    check_variables()
    error_verification()
    setup_logging()

    return create_app()


app = main()
