from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils import RequestGenerator
from tests.utils.db_utils import DbUtils


def pix_transaction_payload() -> dict:
    payer_digits = f"{uuid4().int % 10**11:011d}"
    payee_digits = f"{uuid4().int % 10**11:011d}"
    return {
        "id": f"pix-{uuid4()}",
        "amount": 150000,
        "transaction_date": "2026-10-17T22:15:00-03:00",
        "source_account": {
            "branch": "0001",
            "account_number": "88213",
            "opening_date": "2025-03-02T10:00:00-03:00",
            "owner": {
                "document_number": (
                    f"{payer_digits[:3]}.{payer_digits[3:6]}."
                    f"{payer_digits[6:9]}-{payer_digits[9:]}"
                )
            },
        },
        "destination_account": {
            "participant": "60701190",
            "branch": "3675",
            "account_number": "10442",
            "opening_date": "2026-10-10T09:00:00-03:00",
            "owner": {
                "document_number": (
                    f"{payee_digits[:3]}.{payee_digits[3:6]}."
                    f"{payee_digits[6:9]}-{payee_digits[9:]}"
                )
            },
        },
        "source": {
            "device_id": f"dvc-{uuid4()}",
            "channel": "app",
            "ip": "198.51.100.23",
            "geolocation": {"latitude": -23.56, "longitude": -46.65},
        },
    }


class TestPixTransactionCreate:
    def test_creates_transaction_and_analysis(self):
        payload = pix_transaction_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response["status"] == "two_factor_required"
        assert response["metadata"]["engine_version"] == "1"
        assert response["metadata"]["score"] == 5
        assert response["metadata"]["thresholds"] == {"two_factor": 3, "reject": 8}
        assert [item["rule"] for item in response["metadata"]["rules_triggered"]] == [
            "night_over_limit",
            "young_destination",
            "new_payee",
        ]
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                counts = connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM pix_transaction WHERE id = :transaction_id),
                            (SELECT count(*) FROM pix_analysis WHERE transaction_id = :transaction_id)
                        """
                    ),
                    {"transaction_id": payload["id"]},
                ).one()
        finally:
            engine.dispose()
        assert counts == (1, 1)

    def test_replay_returns_same_analysis_without_reprocessing(self):
        payload = pix_transaction_payload()
        status, first_response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        replay = {**payload, "amount": 5_000_001}
        status, second_response = RequestGenerator.POST_pix_transaction(replay)

        assert status == 200
        assert second_response == first_response

    def test_refuses_invalid_nested_payload(self):
        payload = pix_transaction_payload()
        del payload["source"]["device_id"]

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_refuses_impossible_timestamp(self):
        payload = pix_transaction_payload()
        payload["transaction_date"] = "2026-02-30T10:00:00-03:00"

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001009"

    def test_missing_analysis_is_not_found(self):
        status, response = RequestGenerator.GET_pix_transaction(f"missing-{uuid4()}")
        assert status == 404
        assert response["code"] == "QIT001008"

    def test_gets_analysis_by_transaction_id_and_analysis_key(self):
        payload = pix_transaction_payload()
        status, analysis = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, response = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert response == analysis

        status, response_by_key = RequestGenerator.GET_pix_transaction(analysis["key"])
        assert status == 200
        assert response_by_key == analysis

    def test_documents_are_stored_as_digits_and_cnpj_is_accepted(self):
        payload = pix_transaction_payload()
        payload["source_account"]["owner"]["document_number"] = "12.345.678/0001-95"
        payload["destination_account"]["owner"]["document_number"] = "98765432100"

        status, _response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT source_document_number, destination_document_number
                        FROM pix_transaction WHERE id = :transaction_id
                        """
                    ),
                    {"transaction_id": payload["id"]},
                ).one()
        finally:
            engine.dispose()
        assert row == ("12345678000195", "98765432100")
