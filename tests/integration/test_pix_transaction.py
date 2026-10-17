from uuid import uuid4

from tests.utils import RequestGenerator


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
