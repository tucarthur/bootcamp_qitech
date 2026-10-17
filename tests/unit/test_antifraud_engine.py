from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from controllers.antifraud import POLICY, TransactionData, analyze
from controllers.pix_transaction_controller import PixTransactionController
from errors import PixTransactionTimestampOutsideAllowedWindow


NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone(timedelta(hours=-3)))


def transaction(**overrides) -> TransactionData:
    values = {
        "id": "current",
        "amount": 1_000,
        "transaction_date": NOW,
        "source_document_number": "12345678909",
        "source_account_opening_date": NOW - timedelta(days=365),
        "destination_document_number": "98765432100",
        "destination_account_opening_date": NOW - timedelta(days=365),
        "source_device_id": "current-device",
        "source_latitude": -23.56,
        "source_longitude": -46.65,
    }
    values.update(overrides)
    values.setdefault("received_at", values["transaction_date"])
    return TransactionData(**values)


def previous(minutes=1, **overrides) -> TransactionData:
    values = {
        "id": f"previous-{minutes}-{overrides.get('source_document_number', '12345678909')}",
        "transaction_date": NOW - timedelta(minutes=minutes),
        "status": "approved",
    }
    values.update(overrides)
    return transaction(**values)


def triggered(result: dict) -> dict[str, dict]:
    return {
        item["rule"]: item
        for item in result["metadata"]["rules_triggered"]
    }


def test_hard_ceiling_is_strict_and_blocks():
    assert "hard_ceiling" not in triggered(analyze(transaction(amount=5_000_000), [], POLICY))
    result = analyze(transaction(amount=5_000_001), [], POLICY)
    assert triggered(result)["hard_ceiling"]["block"] is True
    assert result["status"] == "rejected"

    multiple_rules = analyze(
        transaction(
            amount=5_000_001,
            transaction_date=NOW.replace(hour=22),
            destination_account_opening_date=NOW - timedelta(days=1),
        ),
        [],
        POLICY,
    )
    assert {"hard_ceiling", "night_over_limit", "young_destination", "new_payee"}.issubset(
        triggered(multiple_rules)
    )


def test_night_rule_uses_sao_paulo_time_and_cpf_only():
    night = NOW.replace(hour=1)
    result = analyze(transaction(transaction_date=night, amount=100_001), [], POLICY)
    assert triggered(result)["night_over_limit"]["points"] == 2
    cnpj_payer = transaction(
        transaction_date=night,
        amount=100_001,
        source_document_number="12345678000199",
    )
    assert "night_over_limit" not in triggered(analyze(cnpj_payer, [], POLICY))

    at_amount_boundary = transaction(transaction_date=night, amount=100_000)
    assert "night_over_limit" not in triggered(
        analyze(at_amount_boundary, [], POLICY)
    )


def test_score_thresholds_select_two_factor_and_rejection():
    night_transaction = transaction(
        amount=100_001,
        transaction_date=NOW.replace(hour=20),
    )
    two_factor = analyze(night_transaction, [], POLICY)
    assert two_factor["metadata"]["score"] == 3
    assert two_factor["status"] == "two_factor_required"

    with_new_device = [
        previous(
            minutes=index + 1,
            source_device_id=f"old-{index}",
            destination_document_number="11111111111",
        )
        for index in range(3)
    ]
    rejected = analyze(
        transaction(
            amount=150_000,
            transaction_date=NOW.replace(hour=20),
            destination_account_opening_date=NOW - timedelta(days=1),
        ),
        with_new_device,
        POLICY,
    )
    assert rejected["metadata"]["score"] >= POLICY.reject_score
    assert rejected["status"] == "rejected"


def test_burst_has_exclusive_step_and_rejection_tiers():
    result = analyze(transaction(), [previous(minutes=9 - index) for index in range(4)], POLICY)
    assert triggered(result)["burst"]["points"] == POLICY.burst_points

    blocked = analyze(
        transaction(),
        [previous(minutes=9 - index) for index in range(9)],
        POLICY,
    )
    assert triggered(blocked)["burst"]["block"] is True
    assert triggered(blocked)["burst"]["points"] == 0

    cutoff_only = analyze(transaction(), [previous(minutes=10)], POLICY)
    assert "burst" not in triggered(cutoff_only)


def test_velocity_windows_use_receipt_time_not_caller_event_time():
    current = transaction(
        transaction_date=NOW - timedelta(days=365),
        received_at=NOW,
    )
    history = [
        previous(
            minutes=index + 1,
            transaction_date=NOW - timedelta(days=366, minutes=index + 1),
            received_at=NOW - timedelta(minutes=index + 1),
        )
        for index in range(4)
    ]

    result = analyze(current, history, POLICY)

    assert triggered(result)["burst"]["points"] == POLICY.burst_points


def test_timestamp_skew_rejects_at_five_minutes_and_accepts_below():
    received_at = NOW

    PixTransactionController._validate_timestamp_skew(
        received_at + timedelta(minutes=5) - timedelta(microseconds=1),
        received_at,
    )
    PixTransactionController._validate_timestamp_skew(
        received_at - timedelta(minutes=5) + timedelta(microseconds=1),
        received_at,
    )

    for event_time in (received_at + timedelta(minutes=5), received_at - timedelta(minutes=5)):
        with pytest.raises(PixTransactionTimestampOutsideAllowedWindow) as error:
            PixTransactionController._validate_timestamp_skew(event_time, received_at)
        assert error.value.code == "QIT001010"


def test_rolling_total_excludes_rejected_and_uses_strict_thresholds():
    history = [
        previous(amount=900_000, status="rejected"),
        previous(minutes=2, amount=1_000_001, status="approved"),
    ]
    result = analyze(transaction(amount=1), history, POLICY)
    assert triggered(result)["rolling_24h_total"]["points"] == 2

    blocked = analyze(
        transaction(amount=1),
        [previous(amount=3_000_000)],
        POLICY,
    )
    assert triggered(blocked)["rolling_24h_total"]["block"] is True
    at_boundary = analyze(
        transaction(amount=1),
        [previous(amount=999_999)],
        POLICY,
    )
    assert "rolling_24h_total" not in triggered(at_boundary)


def test_amount_median_uses_five_most_recent_effective_samples():
    history = [
        previous(minutes=minutes, amount=10_000 + index, status="approved")
        for index, minutes in enumerate([10, 20, 30, 40, 50])
    ]
    result = analyze(transaction(amount=60_001), history, POLICY)
    assert triggered(result)["amount_vs_median"]["points"] == 2

    rejected_only = [replace(item, status="rejected") for item in history]
    insufficient = analyze(transaction(amount=60_001), rejected_only, POLICY)
    assert "amount_vs_median" not in triggered(insufficient)
    assert any(
        item["rule"] == "amount_vs_median"
        for item in insufficient["metadata"]["rules_skipped"]
    )


def test_amount_median_uses_latest_fifty_not_largest_fifty():
    old_large = previous(minutes=60, amount=100_000_000)
    recent = [
        previous(minutes=minutes, amount=1_000)
        for minutes in range(1, 51)
    ]
    result = analyze(transaction(amount=60_000), [old_large, *recent], POLICY)
    assert "amount_vs_median" in triggered(result)


def test_successful_rules_are_omitted_and_skipped_rules_only_appear_when_needed():
    history = [
        previous(
            minutes=index + 1,
            transaction_date=NOW - timedelta(hours=index + 1),
            destination_document_number="98765432100",
            source_device_id="current-device",
        )
        for index in range(5)
    ]
    result = analyze(transaction(), history, POLICY)
    assert result["status"] == "approved"
    assert result["metadata"]["score"] == 0
    assert result["metadata"]["rules_triggered"] == []
    assert "rules_skipped" not in result["metadata"]


def test_new_device_requires_three_attempts_and_a_new_device():
    history = [
        previous(minutes=index + 1, source_device_id=f"old-device-{index}")
        for index in range(3)
    ]
    result = analyze(transaction(amount=20_000), history, POLICY)
    assert triggered(result)["new_device"]["points"] == 2

    known_device = [replace(item, source_device_id="current-device") for item in history]
    assert "new_device" not in triggered(
        analyze(transaction(amount=20_000), known_device, POLICY)
    )
    insufficient = analyze(transaction(amount=20_000), history[:2], POLICY)
    assert any(item["rule"] == "new_device" for item in insufficient["metadata"]["rules_skipped"])


def test_young_payer_uses_transaction_time_and_strict_amount_cutoff():
    recent_account = transaction(
        amount=100_001,
        source_account_opening_date=NOW - timedelta(days=29),
    )
    assert "young_payer_account" in triggered(analyze(recent_account, [], POLICY))
    boundary = replace(
        recent_account,
        source_account_opening_date=NOW - timedelta(days=30),
    )
    assert "young_payer_account" not in triggered(analyze(boundary, [], POLICY))
    amount_boundary = replace(recent_account, amount=100_000)
    assert "young_payer_account" not in triggered(
        analyze(amount_boundary, [], POLICY)
    )


def test_impossible_travel_requires_recent_prior_geo_and_exceeds_both_cutoffs():
    current = transaction(source_latitude=0.0, source_longitude=1.0)
    result = analyze(
        current,
        [previous(minutes=5, source_latitude=0.0, source_longitude=0.0)],
        POLICY,
    )
    assert triggered(result)["impossible_travel"]["points"] == 3

    no_geo = analyze(transaction(), [], POLICY)
    assert any(item["rule"] == "impossible_travel" for item in no_geo["metadata"]["rules_skipped"])


def test_young_destination_has_one_tier_and_future_dates_clamp_to_zero():
    fresh = transaction(
        amount=50_000,
        destination_account_opening_date=NOW - timedelta(days=6),
    )
    assert triggered(analyze(fresh, [], POLICY))["young_destination"]["points"] == 3

    older = replace(
        fresh,
        destination_account_opening_date=NOW - timedelta(days=7),
    )
    assert triggered(analyze(older, [], POLICY))["young_destination"]["points"] == 2

    future = replace(fresh, destination_account_opening_date=NOW + timedelta(days=20))
    assert triggered(analyze(future, [], POLICY))["young_destination"]["points"] == 3


def test_new_payee_ignores_rejected_history_but_not_effective_history():
    current = transaction(amount=100_000)
    rejected_prior = previous(
        amount=100_000,
        destination_document_number=current.destination_document_number,
        status="rejected",
    )
    assert "new_payee" in triggered(analyze(current, [rejected_prior], POLICY))

    approved_prior = replace(rejected_prior, status="approved")
    assert "new_payee" not in triggered(analyze(current, [approved_prior], POLICY))


def test_mule_fan_in_uses_distinct_payers_and_has_hard_block_tier():
    destination = "98765432100"
    five_sources = [
        previous(
            minutes=index + 1,
            source_document_number=f"{index + 1:011d}",
            destination_document_number=destination,
        )
        for index in range(4)
    ]
    current = transaction(destination_document_number=destination)
    assert triggered(analyze(current, five_sources, POLICY))["mule_fan_in"]["points"] == 3

    nine_sources = [
        previous(
            minutes=index + 1,
            source_document_number=f"{index + 1:011d}",
            destination_document_number=destination,
        )
        for index in range(9)
    ]
    assert triggered(analyze(current, nine_sources, POLICY))["mule_fan_in"]["block"] is True

    cnpj_destination = replace(
        current,
        destination_document_number="12345678000195",
    )
    cnpj_history = [
        replace(item, destination_document_number=cnpj_destination.destination_document_number)
        for item in nine_sources
    ]
    assert "mule_fan_in" not in triggered(analyze(cnpj_destination, cnpj_history, POLICY))


def test_shared_device_counts_distinct_documents_and_self_payment_skips_rules():
    history = [
        previous(
            minutes=index + 1,
            source_document_number=f"{index + 1:011d}",
            source_device_id="current-device",
        )
        for index in range(2)
    ]
    result = analyze(transaction(), history, POLICY)
    assert triggered(result)["shared_device"]["points"] == 3

    self_payment = transaction(
        amount=150_000,
        destination_document_number="12345678909",
        destination_account_opening_date=NOW - timedelta(days=1),
    )
    self_result = analyze(self_payment, history, POLICY)
    assert not {
        "young_destination",
        "new_payee",
        "mule_fan_in",
    }.intersection(triggered(self_result))


def test_obvious_low_risk_transaction_is_approved():
    result = analyze(transaction(), [], POLICY)

    assert result["status"] == "approved"
    assert result["metadata"]["score"] == 0
    assert result["metadata"]["rules_triggered"] == []


def test_rejected_history_does_not_inflate_effective_total():
    history = [previous(amount=POLICY.rolling_24h_reject_cents, status="rejected")]

    result = analyze(transaction(amount=1_000), history, POLICY)

    assert result["status"] == "approved"
    assert "rolling_24h_total" not in triggered(result)


def test_out_of_window_history_does_not_trigger_burst_or_rolling_total():
    old = previous(
        amount=POLICY.rolling_24h_reject_cents,
        received_at=NOW - timedelta(hours=POLICY.rolling_24h_window_hours, seconds=1),
        transaction_date=NOW - timedelta(hours=POLICY.rolling_24h_window_hours, seconds=1),
    )

    result = analyze(transaction(), [old], POLICY)

    assert result["status"] == "approved"
    assert not {"burst", "rolling_24h_total"}.intersection(triggered(result))


def test_amount_above_hard_ceiling_is_rejected():
    result = analyze(
        transaction(amount=POLICY.hard_ceiling_cents + 1),
        [],
        POLICY,
    )

    assert result["status"] == "rejected"
    assert triggered(result)["hard_ceiling"]["block"] is True


def test_tenth_recent_payer_attempt_is_rejected():
    history = [previous(minutes=index + 1) for index in range(POLICY.burst_reject_count - 1)]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "rejected"
    assert triggered(result)["burst"]["block"] is True


def test_effective_rolling_total_above_reject_limit_is_rejected():
    history = [previous(amount=POLICY.rolling_24h_reject_cents)]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "rejected"
    assert triggered(result)["rolling_24h_total"]["block"] is True


def test_fifth_recent_payer_attempt_requires_two_factor():
    history = [previous(minutes=index + 1) for index in range(POLICY.burst_two_factor_count - 1)]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["burst"]["points"] == POLICY.burst_points


def test_rolling_total_above_two_factor_limit_requires_two_factor():
    result = analyze(
        transaction(amount=POLICY.rolling_24h_two_factor_cents + 1),
        [],
        POLICY,
    )

    assert result["status"] == "two_factor_required"
    assert triggered(result)["rolling_24h_total"]["points"] == POLICY.rolling_24h_points


def test_new_device_and_first_payee_require_two_factor():
    history = [
        previous(
            minutes=index + 1,
            amount=1_000,
            source_device_id=f"old-device-{index}",
            destination_document_number=f"{index + 1:011d}",
        )
        for index in range(POLICY.new_device_min_attempts)
    ]

    result = analyze(
        transaction(amount=POLICY.new_payee_min_cents),
        history,
        POLICY,
    )

    assert result["status"] == "two_factor_required"
    assert {"new_device", "new_payee"} <= set(triggered(result))


def test_distinct_payers_funneling_to_one_cpf_require_two_factor():
    destination = "98765432100"
    history = [
        previous(
            minutes=index + 1,
            source_document_number=f"{index + 1:011d}",
            destination_document_number=destination,
        )
        for index in range(POLICY.mule_fan_in_two_factor_count - 1)
    ]

    result = analyze(transaction(destination_document_number=destination), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["mule_fan_in"]["points"] == POLICY.mule_fan_in_points


def test_shared_device_used_by_three_payers_requires_two_factor():
    history = [
        previous(
            minutes=index + 1,
            source_document_number=f"{index + 1:011d}",
            source_device_id="current-device",
            destination_document_number="11111111111",
        )
        for index in range(POLICY.shared_device_min_documents - 1)
    ]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["shared_device"]["points"] == POLICY.shared_device_points
