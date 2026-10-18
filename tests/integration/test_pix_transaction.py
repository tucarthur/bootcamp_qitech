from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, text

from controllers.antifraud.constants import POLICY
from database import Context
from repositories import PixAccountBlacklistRepository
from tests.utils import RequestGenerator
from tests.utils.db_utils import DbUtils


def pix_transaction_payload() -> dict:
    payer_digits = f"{uuid4().int % 10**11:011d}"
    payee_digits = f"{uuid4().int % 10**11:011d}"
    transaction_date = datetime.now(timezone(timedelta(hours=-3))).replace(
        hour=14,
        minute=0,
        second=0,
        microsecond=0,
    )
    return {
        "id": f"pix-{uuid4()}",
        "amount": 150000,
        "transaction_date": transaction_date.isoformat(),
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
            "opening_date": (
                datetime.now(timezone.utc) - timedelta(days=8)
            ).isoformat(),
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
        assert response["metadata"]["engine_version"] == "8"
        assert response["metadata"]["score"] == 3
        assert response["metadata"]["thresholds"] == {
            "two_factor": 3,
            "reject": 8,
            "warn_z": 3.0,
            "critical_z": 6.0,
        }
        assert [item["rule"] for item in response["metadata"]["rules_triggered"]] == [
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
                            (SELECT count(*) FROM pix_analysis WHERE transaction_id = :transaction_id),
                            (
                                SELECT octet_length(history_snapshot)
                                FROM pix_payer_behavior_profile
                                WHERE source_document_number = (
                                    SELECT source_document_number
                                    FROM pix_transaction
                                    WHERE id = :transaction_id
                                )
                            )
                        """
                    ),
                    {"transaction_id": payload["id"]},
                ).one()
                timestamps = connection.execute(
                    text(
                        """
                        SELECT transaction_date, received_at
                        FROM pix_transaction
                        WHERE id = :transaction_id
                        """
                    ),
                    {"transaction_id": payload["id"]},
                ).one()
        finally:
            engine.dispose()
        assert counts[:2] == (1, 1)
        assert counts[2] > 0
        assert timestamps.received_at.utcoffset() is not None
        assert timestamps.received_at != timestamps.transaction_date

    def test_replay_returns_same_analysis_without_reprocessing(self):
        payload = pix_transaction_payload()
        status, first_response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        replay = {**payload, "amount": 5_000_001}
        status, second_response = RequestGenerator.POST_pix_transaction(replay)

        assert status == 200
        assert second_response == first_response

    def test_concurrent_transactions_serialize_shared_payer_history(self):
        first = pix_transaction_payload()
        payer_document = first["source_account"]["owner"]["document_number"]
        device_id = first["source"]["device_id"]
        payloads = []
        for index in range(10):
            payload = pix_transaction_payload()
            payload["amount"] = 1_000
            payload["transaction_date"] = (
                datetime.fromisoformat(payload["transaction_date"])
                + timedelta(seconds=index)
            ).isoformat()
            payload["source_account"]["owner"]["document_number"] = payer_document
            payload["source"]["device_id"] = device_id
            payloads.append(payload)

        with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
            responses = list(executor.map(RequestGenerator.POST_pix_transaction, payloads))

        assert all(status == 201 for status, _response in responses)
        response_by_id = {
            payload["id"]: response["status"]
            for payload, (_status, response) in zip(payloads, responses)
        }
        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT t.id, t.transaction_date, t.received_at, a.status
                        FROM pix_transaction t
                        JOIN pix_analysis a ON a.transaction_id = t.id
                        WHERE t.id = ANY(:transaction_ids)
                        ORDER BY t.received_at, t.id
                        """
                    ),
                    {"transaction_ids": [payload["id"] for payload in payloads]},
                ).all()
        finally:
            engine.dispose()

        prior_event_dates = []
        for row in rows:
            recent_prior_count = sum(
                row.transaction_date - timedelta(minutes=10) < event_date < row.transaction_date
                for event_date in prior_event_dates
            )
            attempt_count = recent_prior_count + 1
            expected_status = (
                "rejected"
                if attempt_count >= 10
                else "two_factor_required"
                if attempt_count >= 5
                else "approved"
            )
            assert row.status == expected_status
            assert response_by_id[row.id] == expected_status
            prior_event_dates.append(row.transaction_date)

    def test_non_counterpart_rejection_does_not_blacklist_payer(self):
        first = pix_transaction_payload()
        payer_document = first["source_account"]["owner"]["document_number"]
        device_id = first["source"]["device_id"]
        last_date = datetime.fromisoformat(first["transaction_date"])

        for index in range(10):
            payload = pix_transaction_payload()
            payload["amount"] = 1_000
            payload["transaction_date"] = (
                last_date + timedelta(seconds=index)
            ).isoformat()
            payload["source_account"]["owner"]["document_number"] = payer_document
            payload["source"]["device_id"] = device_id

            status, response = RequestGenerator.POST_pix_transaction(payload)
            assert status == 201
            if index == 9:
                assert response["status"] == "rejected"

        follow_up = pix_transaction_payload()
        follow_up["amount"] = 1_000
        follow_up["source_account"]["owner"]["document_number"] = payer_document
        follow_up["source"]["device_id"] = device_id
        follow_up["transaction_date"] = (last_date + timedelta(seconds=10)).isoformat()

        status, response = RequestGenerator.POST_pix_transaction(follow_up)
        assert status == 201
        assert response["status"] == "rejected"
        assert all(
            item["rule"] != "account_blacklist"
            for item in response["metadata"]["rules_triggered"]
        )

    def test_mule_fan_in_blacklists_flagged_destination_until_authenticated(self):
        first = pix_transaction_payload()
        flagged_document = first["destination_account"]["owner"]["document_number"]
        device_id = f"dvc-{uuid4()}"
        base_date = datetime.fromisoformat(first["transaction_date"])

        for index in range(POLICY.mule_fan_in_block_count):
            payload = pix_transaction_payload()
            payload["transaction_date"] = (
                base_date + timedelta(seconds=index)
            ).isoformat()
            payload["destination_account"]["owner"]["document_number"] = (
                flagged_document
            )

            status, response = RequestGenerator.POST_pix_transaction(payload)
            assert status == 201

        assert response["status"] == "rejected"
        mule_rule = next(
            item
            for item in response["metadata"]["rules_triggered"]
            if item["rule"] == "mule_fan_in"
        )
        assert mule_rule["block"] is True

        blocked_payload = pix_transaction_payload()
        blocked_payload["source_account"]["owner"]["document_number"] = flagged_document
        blocked_payload["source"]["device_id"] = device_id
        blocked_payload["transaction_date"] = (
            base_date + timedelta(seconds=POLICY.mule_fan_in_block_count)
        ).isoformat()
        status, blocked_response = RequestGenerator.POST_pix_transaction(blocked_payload)
        assert status == 201
        assert blocked_response["status"] == "rejected"
        assert any(
            item["rule"] == "account_blacklist"
            and item["requires_authentication"] is True
            for item in blocked_response["metadata"]["rules_triggered"]
        )

        context = Context()
        try:
            context.get_or_create_session()
            blacklist_repository = PixAccountBlacklistRepository(context)
            assert blacklist_repository.clear_after_authentication(flagged_document)
            context.db_session.commit()
        finally:
            if context.db_session is not None:
                context.db_session.close()

        authenticated_payload = pix_transaction_payload()
        authenticated_payload["source_account"]["owner"]["document_number"] = (
            flagged_document
        )
        authenticated_payload["source"]["device_id"] = device_id
        authenticated_payload["transaction_date"] = (
            base_date + timedelta(minutes=11)
        ).isoformat()
        status, authenticated_response = RequestGenerator.POST_pix_transaction(
            authenticated_payload
        )
        assert status == 201
        assert authenticated_response["status"] != "rejected"
        assert all(
            item["rule"] != "account_blacklist"
            for item in authenticated_response["metadata"]["rules_triggered"]
        )

    def test_tree_evasion_blocks_exact_balance_sweep_to_three_cpfs(self):
        incoming = pix_transaction_payload()
        payer_document = incoming["source_account"]["owner"]["document_number"]
        base_date = datetime.fromisoformat(incoming["transaction_date"])
        incoming["amount"] = 300_000
        incoming["destination_account"]["owner"]["document_number"] = payer_document

        status, _response = RequestGenerator.POST_pix_transaction(incoming)
        assert status == 201

        response = None
        for index, payee_document in enumerate(
            ("98765432100", "98765432101", "98765432102"),
            start=1,
        ):
            outgoing = pix_transaction_payload()
            outgoing["amount"] = 100_000
            outgoing["transaction_date"] = (
                base_date + timedelta(seconds=index)
            ).isoformat()
            outgoing["source_account"]["owner"]["document_number"] = payer_document
            outgoing["destination_account"]["owner"]["document_number"] = (
                payee_document
            )

            status, response = RequestGenerator.POST_pix_transaction(outgoing)
            assert status == 201

        assert response["status"] == "rejected"
        tree_rule = next(
            item
            for item in response["metadata"]["rules_triggered"]
            if item["rule"] == "tree_evasion"
        )
        assert tree_rule["block"] is True

    def test_refuses_invalid_nested_payload(self):
        payload = pix_transaction_payload()
        del payload["source"]["device_id"]

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 400
        assert response["code"] == "QIT000001"

    def test_geolocation_is_optional_and_travel_rule_is_skipped(self):
        payload = pix_transaction_payload()
        del payload["source"]["geolocation"]

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 201
        assert any(
            item["rule"] == "impossible_travel"
            for item in response["metadata"]["rules_skipped"]
        )

    def test_refuses_impossible_timestamp(self):
        payload = pix_transaction_payload()
        payload["transaction_date"] = "2026-02-30T10:00:00-03:00"

        status, response = RequestGenerator.POST_pix_transaction(payload)

        assert status == 422
        assert response["code"] == "QIT001009"

    def test_accepts_event_timestamp_outside_previous_five_minute_limit(self):
        for offset in (timedelta(minutes=-6), timedelta(minutes=6)):
            payload = pix_transaction_payload()
            payload["transaction_date"] = (
                datetime.now(timezone.utc) + offset
            ).isoformat()

            status, response = RequestGenerator.POST_pix_transaction(payload)

            assert status == 201
            assert response["status"] in {
                "approved",
                "two_factor_required",
                "rejected",
            }

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
