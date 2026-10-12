from os import environ

from tests.utils.requisition import ClientRequisition, BaseConnectorResponse


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    @staticmethod
    def POST_account(customer_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/account",
            payload={"customer_key": customer_key},
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_account(account_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/account/{account_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_accounts_by_customer(customer_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/accounts/{customer_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_deposit(
        account_key: str,
        idempotency_key: str,
        amount_cents: int,
    ) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            f"/account/{account_key}/deposit",
            payload={
                "idempotency_key": idempotency_key,
                "amount_cents": amount_cents,
            },
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_withdrawal(
        account_key: str,
        idempotency_key: str,
        amount_cents: int,
    ) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            f"/account/{account_key}/withdrawal",
            payload={
                "idempotency_key": idempotency_key,
                "amount_cents": amount_cents,
            },
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_statement(account_key: str, params: dict = None) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/account/{account_key}/statement",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
            query_params=params,
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_transaction(
        idempotency_key: str,
        source_account_key: str,
        destination_account_key: str,
        amount_cents: int,
    ) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/transaction",
            payload={
                "idempotency_key": idempotency_key,
                "source_account_key": source_account_key,
                "destination_account_key": destination_account_key,
                "amount_cents": amount_cents,
            },
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_transaction(transaction_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/transaction/{transaction_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_customer(customer_payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/customers",
            payload=customer_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_customer(customer_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/customers/{customer_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def DELETE_customer(customer_document: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "DELETE",
            f"/customers/{customer_document}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

