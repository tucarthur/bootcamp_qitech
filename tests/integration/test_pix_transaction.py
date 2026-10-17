import json
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils import RequestGenerator
from tests.utils.db_utils import DbUtils


def pix_transaction_payload() -> dict:
    return {
        "id": f"pix-{uuid4()}",
        "amount": 150000,
        "transaction_date": "2026-10-17T22:15:00-03:00",
        "source_account": {
            "branch": "0001",
            "account_number": "88213",
            "opening_date": "2025-03-02T10:00:00-03:00",
            "owner": {"document_number": "123.456.789-09"},
        },
        "destination_account": {
            "participant": "60701190",
            "branch": "3675",
            "account_number": "10442",
            "opening_date": "2026-10-10T09:00:00-03:00",
            "owner": {"document_number": "987.654.321-00"},
        },
        "source": {
            "device_id": "dvc-9f2c71a8",
            "channel": "app",
            "ip": "198.51.100.23",
            "geolocation": {"latitude": -23.56, "longitude": -46.65},
        },
    }


class TestPixTransactionCreate:
    def test_creates_transaction(self):
        payload = pix_transaction_payload()

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert response == {"id": payload["id"]}

    def test_refuses_duplicate_transaction_id(self):
        payload = pix_transaction_payload()
        status, _response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 409
        assert response["code"] == "QIT001008"

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

    def test_analysis_is_not_found_until_recorded(self):
        payload = pix_transaction_payload()
        status, _response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, response = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 404
        assert response["code"] == "QIT001010"

    def test_returns_recorded_analysis(self):
        payload = pix_transaction_payload()
        status, _response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        analysis_key = str(uuid4())
        metadata = {"reason": "new_device"}
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO pix_transaction_analysis (key, transaction_id, status, metadata)
                        VALUES (:key, :transaction_id, :status, CAST(:analysis_metadata AS JSONB))
                        """
                    ),
                    {
                        "key": analysis_key,
                        "transaction_id": payload["id"],
                        "status": "two_factor_required",
                        "analysis_metadata": json.dumps(metadata),
                    },
                )
        finally:
            engine.dispose()

        status, response = RequestGenerator.GET_pix_transaction(payload["id"])

        assert status == 200
        assert response == {
            "key": analysis_key,
            "status": "two_factor_required",
            "metadata": metadata,
        }
