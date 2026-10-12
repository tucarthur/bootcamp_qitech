from concurrent.futures import ThreadPoolExecutor
from os import environ
from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator

TRANSFER_FEE_CENTS = int(environ.get("TRANSFER_FEE_CENTS", "200"))


def create_account(balance_cents: int = 0) -> str:
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
    if balance_cents:
        status, _ = RequestGenerator.POST_deposit(account_key, str(uuid4()), balance_cents)
        assert status == 201
    return account_key


class TestTransactionsPost:
    def test_transfer_charges_fee_and_is_idempotent(self):
        source_account_key = create_account(10000)
        destination_account_key = create_account()
        idempotency_key = str(uuid4())

        status, transaction = RequestGenerator.POST_transaction(
            idempotency_key, source_account_key, destination_account_key, 3000
        )

        assert status == 201
        assert transaction["amount_cents"] == 3000
        assert transaction["fee_cents"] == TRANSFER_FEE_CENTS

        status, replay = RequestGenerator.POST_transaction(
            idempotency_key, source_account_key, destination_account_key, 3000
        )
        assert status == 200
        assert replay == transaction

        status, conflict = RequestGenerator.POST_transaction(
            idempotency_key, source_account_key, destination_account_key, 3001
        )
        assert status == 409
        assert conflict["code"] == "QIT001008"

        status, source = RequestGenerator.GET_account(source_account_key)
        assert status == 200
        assert source["balance_cents"] == 10000 - 3000 - TRANSFER_FEE_CENTS

        status, destination = RequestGenerator.GET_account(destination_account_key)
        assert status == 200
        assert destination["balance_cents"] == 3000

    def test_transfer_rejects_same_account_and_unknown_accounts(self):
        account_key = create_account()

        status, same_account_error = RequestGenerator.POST_transaction(
            str(uuid4()), account_key, account_key, 100
        )
        assert status == 422
        assert same_account_error["code"] == "QIT001010"

        status, _ = RequestGenerator.POST_transaction(
            str(uuid4()), account_key, str(uuid4()), 100
        )
        assert status == 404

    def test_transfer_rejects_non_uuid_account_keys(self):
        status, _ = RequestGenerator.POST_transaction(
            str(uuid4()), "not-a-uuid", str(uuid4()), 100
        )
        assert status == 400

        status, _ = RequestGenerator.POST_transaction(
            str(uuid4()), str(uuid4()), "not-a-uuid", 100
        )
        assert status == 400

    def test_insufficient_transfer_does_not_consume_idempotency_key(self):
        amount_cents = 900
        source_account_key = create_account(amount_cents + TRANSFER_FEE_CENTS - 1)
        destination_account_key = create_account()
        idempotency_key = str(uuid4())

        status, error = RequestGenerator.POST_transaction(
            idempotency_key, source_account_key, destination_account_key, amount_cents
        )
        assert status == 422
        assert error["code"] == "QIT001009"

        status, _ = RequestGenerator.POST_deposit(source_account_key, str(uuid4()), 1)
        assert status == 201

        status, transaction = RequestGenerator.POST_transaction(
            idempotency_key, source_account_key, destination_account_key, amount_cents
        )
        assert status == 201
        assert transaction["amount_cents"] == amount_cents
        assert transaction["fee_cents"] == TRANSFER_FEE_CENTS

    def test_concurrent_transfers_cannot_overspend_source_account(self):
        amount_cents = 700
        debit_cents = amount_cents + TRANSFER_FEE_CENTS
        source_account_key = create_account(debit_cents * 2 - 1)
        destination_account_keys = [create_account(), create_account()]

        def submit_transfer(destination_account_key: str):
            return RequestGenerator.POST_transaction(
                str(uuid4()), source_account_key, destination_account_key, amount_cents
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit_transfer, destination_account_keys))

        assert sorted(status for status, _ in results) == [201, 422]

        status, source = RequestGenerator.GET_account(source_account_key)
        assert status == 200
        assert source["balance_cents"] == debit_cents - 1