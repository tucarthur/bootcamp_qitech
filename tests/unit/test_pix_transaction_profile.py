from datetime import datetime, timedelta, timezone

from controllers.antifraud import TransactionData
from repositories.pix_transaction_repository import PixTransactionRepository

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def transaction(**overrides) -> TransactionData:
    values = {
        "id": "profile-transaction",
        "amount": 1_000,
        "transaction_date": NOW,
        "received_at": NOW,
        "source_document_number": "12345678909",
        "source_account_opening_date": NOW - timedelta(days=365),
        "destination_document_number": "98765432100",
        "destination_account_opening_date": NOW - timedelta(days=365),
        "source_device_id": "profile-device",
        "source_latitude": -23.56,
        "source_longitude": -46.65,
        "status": "approved",
    }
    values.update(overrides)
    return TransactionData(**values)


def test_behavior_profile_snapshot_round_trips_compressed_history():
    item = transaction(status="two_factor_required")
    snapshot = [PixTransactionRepository._to_snapshot(item)]

    encoded = PixTransactionRepository._encode_snapshot(snapshot)
    decoded = PixTransactionRepository._decode_snapshot(encoded)
    restored = PixTransactionRepository._from_snapshot(decoded[0])

    assert restored == item
    assert len(encoded) < len(str(snapshot).encode("utf-8"))


def test_profile_merge_preserves_late_events_and_keeps_newest_bounded_history():
    newest = transaction(
        id="newest",
        transaction_date=NOW,
        received_at=NOW,
    )
    late = transaction(
        id="late",
        transaction_date=NOW - timedelta(days=1),
        received_at=NOW - timedelta(days=1),
    )
    snapshots = [
        PixTransactionRepository._to_snapshot(newest),
        PixTransactionRepository._to_snapshot(late),
    ]

    merged = PixTransactionRepository._merge_snapshots(
        snapshots[:1],
        snapshots[1:],
    )

    assert [row["id"] for row in merged] == ["newest", "late"]


def test_profile_snapshot_round_trip_preserves_cnpj_and_missing_geolocation():
    item = transaction(
        source_document_number="12345678000195",
        source_latitude=None,
        source_longitude=None,
        destination_document_number="98765432000100",
    )

    restored = PixTransactionRepository._from_snapshot(
        PixTransactionRepository._decode_snapshot(
            PixTransactionRepository._encode_snapshot(
                [PixTransactionRepository._to_snapshot(item)]
            )
        )[0]
    )

    assert isinstance(restored, TransactionData)
    assert restored.source_document_number == item.source_document_number
    assert restored.destination_document_number == item.destination_document_number
    assert restored.source_latitude is None
    assert restored.source_longitude is None
