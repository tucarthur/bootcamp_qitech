from os import environ
from uuid import uuid4

from tests.utils import RandomGenerator, RequestGenerator

TRANSFER_FEE_CENTS = int(environ.get("TRANSFER_FEE_CENTS", "200"))


def create_account() -> str:
    customer_payload = {
        "name": "Maria da Silva",
        "email": f"maria.silva.{uuid4()}@exemplo.com.br",
        "document_number": RandomGenerator.generate_cpf(),
        "birthdate": "1990-05-17",
    }
    status, customer = RequestGenerator.POST_customer(customer_payload)
    assert status == 201

    status, account = RequestGenerator.POST_account(customer["customer_key"])
    assert status == 201
    return account["account_key"]


class TestTransactionsGet:
    def test_get_transaction_includes_ledger_entries(self):
        source_account_key = create_account()
        destination_account_key = create_account()
        status, _ = RequestGenerator.POST_deposit(
            source_account_key, str(uuid4()), 10000 + TRANSFER_FEE_CENTS
        )
        assert status == 201

        status, created = RequestGenerator.POST_transaction(
            str(uuid4()), source_account_key, destination_account_key, 3000
        )
        assert status == 201

        status, transaction = RequestGenerator.GET_transaction(created["transaction_key"])

        assert status == 200
        assert transaction["transaction_key"] == created["transaction_key"]
        assert transaction["type"] == "TRANSFER"
        assert transaction["source_account_key"] == source_account_key
        assert transaction["destination_account_key"] == destination_account_key
        assert transaction["amount_cents"] == 3000
        assert transaction["fee_cents"] == TRANSFER_FEE_CENTS
        expected_entries = [("PRINCIPAL", "DEBIT")]
        if TRANSFER_FEE_CENTS:
            expected_entries.append(("FEE", "DEBIT"))
        expected_entries.append(("PRINCIPAL", "CREDIT"))
        assert [
            (entry["kind"], entry["direction"])
            for entry in transaction["ledger_entries"]
        ] == expected_entries

    def test_get_unknown_transaction_returns_not_found(self):
        status, error = RequestGenerator.GET_transaction(str(uuid4()))

        assert status == 404