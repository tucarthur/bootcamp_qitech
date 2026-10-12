from datetime import datetime
from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator


class TestAccountsPost:
    def test_create_account_for_customer(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201

        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])

        assert status == 201
        assert "account_key" in account_response

        status, account_details = RequestGenerator.GET_account(account_response["account_key"])

        assert status == 200
        assert account_details["account_key"] == account_response["account_key"]
        assert account_details["customer_key"] == customer_response["customer_key"]
        assert account_details["balance_cents"] == 0
        datetime.fromisoformat(account_details["created_at"])

    def test_create_account_for_unknown_customer(self):
        status, _ = RequestGenerator.POST_account(str(uuid4()))

        assert status == 404

    def test_get_unknown_account(self):
        status, _ = RequestGenerator.GET_account(str(uuid4()))

        assert status == 404

    def test_get_all_accounts_for_customer(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201
        customer_key = customer_response["customer_key"]

        status, empty_response = RequestGenerator.GET_accounts_by_customer(customer_key)
        assert status == 200
        assert empty_response == {"customer_key": customer_key, "accounts": []}

        status, first_account = RequestGenerator.POST_account(customer_key)
        assert status == 201
        status, second_account = RequestGenerator.POST_account(customer_key)
        assert status == 201

        status, accounts_response = RequestGenerator.GET_accounts_by_customer(customer_key)

        assert status == 200
        assert accounts_response["customer_key"] == customer_key
        account_details = accounts_response["accounts"]
        assert [account["account_key"] for account in account_details] == [
            first_account["account_key"],
            second_account["account_key"],
        ]
        assert all(account["balance_cents"] == 0 for account in account_details)
        for account in account_details:
            datetime.fromisoformat(account["created_at"])

    def test_get_accounts_for_unknown_customer(self):
        status, _ = RequestGenerator.GET_accounts_by_customer(str(uuid4()))

        assert status == 404

    def test_deposit_is_idempotent_and_updates_balance_once(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201

        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])
        assert status == 201
        account_key = account_response["account_key"]
        idempotency_key = str(uuid4())

        status, deposit_response = RequestGenerator.POST_deposit(
            account_key, idempotency_key, 12500
        )
        assert status == 201
        assert deposit_response["amount_cents"] == 12500
        assert deposit_response["fee_cents"] == 0

        status, replay_response = RequestGenerator.POST_deposit(
            account_key, idempotency_key, 12500
        )
        assert status == 200
        assert replay_response == deposit_response

        status, conflict_response = RequestGenerator.POST_deposit(
            account_key, idempotency_key, 13000
        )
        assert status == 409
        assert conflict_response["code"] == "QIT001008"

        status, account_details = RequestGenerator.GET_account(account_key)
        assert status == 200
        assert account_details["balance_cents"] == 12500

    def test_deposit_to_unknown_account(self):
        status, _ = RequestGenerator.POST_deposit(str(uuid4()), str(uuid4()), 100)

        assert status == 404

    def test_withdrawal_is_idempotent_and_updates_balance_once(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201

        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])
        assert status == 201
        account_key = account_response["account_key"]

        status, _ = RequestGenerator.POST_deposit(account_key, str(uuid4()), 10000)
        assert status == 201

        idempotency_key = str(uuid4())
        status, withdrawal_response = RequestGenerator.POST_withdrawal(
            account_key, idempotency_key, 4000
        )
        assert status == 201
        assert withdrawal_response["amount_cents"] == 4000
        assert withdrawal_response["fee_cents"] == 0

        status, replay_response = RequestGenerator.POST_withdrawal(
            account_key, idempotency_key, 4000
        )
        assert status == 200
        assert replay_response == withdrawal_response

        status, conflict_response = RequestGenerator.POST_withdrawal(
            account_key, idempotency_key, 5000
        )
        assert status == 409
        assert conflict_response["code"] == "QIT001008"

        status, account_details = RequestGenerator.GET_account(account_key)
        assert status == 200
        assert account_details["balance_cents"] == 6000

    def test_insufficient_funds_does_not_consume_idempotency_key(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201

        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])
        assert status == 201
        account_key = account_response["account_key"]
        idempotency_key = str(uuid4())

        status, error_response = RequestGenerator.POST_withdrawal(
            account_key, idempotency_key, 100
        )
        assert status == 422
        assert error_response["code"] == "QIT001009"

        status, _ = RequestGenerator.POST_deposit(account_key, str(uuid4()), 500)
        assert status == 201

        status, withdrawal_response = RequestGenerator.POST_withdrawal(
            account_key, idempotency_key, 100
        )
        assert status == 201
        assert withdrawal_response["amount_cents"] == 100

        status, account_details = RequestGenerator.GET_account(account_key)
        assert status == 200
        assert account_details["balance_cents"] == 400

    def test_withdrawal_from_unknown_account(self):
        status, _ = RequestGenerator.POST_withdrawal(str(uuid4()), str(uuid4()), 100)

        assert status == 404

    def test_statement_uses_cursor_pagination(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201
        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])
        assert status == 201
        account_key = account_response["account_key"]

        transaction_keys = []
        for amount_cents in (100, 200, 300, 400):
            status, deposit_response = RequestGenerator.POST_deposit(
                account_key, str(uuid4()), amount_cents
            )
            assert status == 201
            transaction_keys.append(deposit_response["transaction_key"])

        status, first_page = RequestGenerator.GET_statement(account_key, {"limit": "2"})
        assert status == 200
        assert first_page["limit"] == 2
        assert first_page["is_last_page"] is False
        assert first_page["next_cursor"]
        assert [entry["transaction_key"] for entry in first_page["data"]] == [
            transaction_keys[3],
            transaction_keys[2],
        ]
        assert [entry["balance_after_cents"] for entry in first_page["data"]] == [
            1000,
            600,
        ]

        status, second_page = RequestGenerator.GET_statement(
            account_key,
            {"limit": "2", "cursor": first_page["next_cursor"]},
        )
        assert status == 200
        assert second_page["is_last_page"] is True
        assert second_page["next_cursor"] is None
        assert [entry["transaction_key"] for entry in second_page["data"]] == [
            transaction_keys[1],
            transaction_keys[0],
        ]

    def test_statement_rejects_malformed_cursor(self):
        customer_payload = {
            "name": "Maria da Silva",
            "email": f"maria.silva.{uuid4()}@exemplo.com.br",
            "document_number": RandomGenerator.generate_cpf(),
            "birthdate": "1990-05-17",
        }
        status, customer_response = RequestGenerator.POST_customer(customer_payload)
        assert status == 201
        status, account_response = RequestGenerator.POST_account(customer_response["customer_key"])
        assert status == 201

        status, error_response = RequestGenerator.GET_statement(
            account_response["account_key"], {"cursor": "AAAA"}
        )

        assert status == 400
        assert error_response["code"] == "QIT000010"