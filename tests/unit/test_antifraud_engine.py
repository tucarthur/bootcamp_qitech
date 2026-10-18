from dataclasses import replace
from datetime import datetime, timedelta, timezone

from controllers.antifraud import (
    POLICY,
    ContextHistoryCounts,
    TransactionData,
    TreeEvasionCredit,
    analyze,
)


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


def test_high_value_fixed_thresholds_require_2fa_by_recipient_type():
    result = analyze(
        transaction(amount=POLICY.high_value_fixed_ceiling_cents["cpf"]),
        [],
        POLICY,
    )

    assert result["status"] == "two_factor_required"
    assert triggered(result)["high_value_review"]["points"] == 0
    assert triggered(result)["high_value_review"]["block"] is False
    assert triggered(result)["high_value_review"]["requires_2fa"] is True
    assert triggered(result)["high_value_review"]["basis"] == "fixed"

    larger_amount = analyze(
        transaction(amount=POLICY.high_value_fixed_ceiling_cents["cpf"] + 1),
        [],
        POLICY,
    )
    assert larger_amount["status"] == "two_factor_required"

    cnpj_value_below_fixed_limit = analyze(
        transaction(
            amount=3_500_000,
            source_document_number="12345678000195",
            destination_document_number="98765432000100",
        ),
        [],
        POLICY,
    )
    assert "high_value_review" not in triggered(cnpj_value_below_fixed_limit)


def test_blacklisted_account_is_rejected_and_reports_authentication_requirement():
    result = analyze(
        transaction(amount=POLICY.high_value_fixed_ceiling_cents["cpf"] + 1),
        [],
        POLICY,
        account_blacklisted=True,
    )

    blacklist_rule = triggered(result)["account_blacklist"]
    assert result["status"] == "rejected"
    assert blacklist_rule["block"] is True
    assert blacklist_rule["points"] == 0
    assert blacklist_rule["requires_authentication"] is True
    assert "high_value_review" in triggered(result)


def test_sql_context_counts_drive_mule_fan_in_and_shared_device_rules():
    result = analyze(
        transaction(),
        [],
        POLICY,
        context_history_counts=ContextHistoryCounts(
            distinct_payee_payers=POLICY.mule_fan_in_block_count - 1,
            distinct_device_payers=POLICY.shared_device_min_payers - 1,
        ),
    )

    rules = triggered(result)
    assert result["status"] == "rejected"
    assert rules["mule_fan_in"]["block"] is True
    assert rules["shared_device"]["points"] == POLICY.shared_device_points


def test_tree_evasion_blocks_exact_three_cpf_sweep_within_fifteen_seconds():
    result = analyze(
        transaction(
            amount=1_000,
            destination_document_number="98765432102",
        ),
        [],
        POLICY,
        tree_evasion_credits=[
            TreeEvasionCredit(
                amount=3_000,
                received_at=NOW - timedelta(seconds=10),
                prior_outgoing_amount=2_000,
                prior_cpf_documents=("98765432100", "98765432101"),
            )
        ],
    )

    rule = triggered(result)["tree_evasion"]
    assert result["status"] == "rejected"
    assert rule["block"] is True
    assert rule["points"] == 0


def test_tree_evasion_uses_server_receipt_time_not_client_transaction_time():
    result = analyze(
        transaction(
            amount=1_000,
            transaction_date=NOW + timedelta(days=1),
            received_at=NOW,
            destination_document_number="98765432102",
        ),
        [],
        POLICY,
        tree_evasion_credits=[
            TreeEvasionCredit(
                amount=3_000,
                received_at=NOW - timedelta(seconds=10),
                prior_outgoing_amount=2_000,
                prior_cpf_documents=("98765432100", "98765432101"),
            )
        ],
    )

    assert triggered(result)["tree_evasion"]["block"] is True


def test_tree_evasion_requires_exact_full_balance_and_three_distinct_cpfs():
    credits = [
        TreeEvasionCredit(
            amount=3_000,
            received_at=NOW - timedelta(seconds=10),
            prior_outgoing_amount=1_999,
            prior_cpf_documents=("98765432100", "98765432101"),
        ),
        TreeEvasionCredit(
            amount=3_000,
            received_at=NOW - timedelta(seconds=10),
            prior_outgoing_amount=2_000,
            prior_cpf_documents=("98765432100",),
        ),
    ]

    for credit in credits:
        result = analyze(
            transaction(amount=1_000, destination_document_number="98765432102"),
            [],
            POLICY,
            tree_evasion_credits=[credit],
        )
        assert "tree_evasion" not in triggered(result)


def test_tree_evasion_does_not_trigger_at_or_after_fifteen_seconds_or_for_cnpj():
    for elapsed_seconds in (15, 16):
        result = analyze(
            transaction(
                amount=1_000,
                destination_document_number="98765432102",
            ),
            [],
            POLICY,
            tree_evasion_credits=[
                TreeEvasionCredit(
                    amount=3_000,
                    received_at=NOW - timedelta(seconds=elapsed_seconds),
                    prior_outgoing_amount=2_000,
                    prior_cpf_documents=("98765432100", "98765432101"),
                )
            ],
        )
        assert "tree_evasion" not in triggered(result)

    cnpj_result = analyze(
        transaction(
            amount=1_000,
            destination_document_number="98765432000100",
        ),
        [],
        POLICY,
        tree_evasion_credits=[
            TreeEvasionCredit(
                amount=3_000,
                received_at=NOW - timedelta(seconds=10),
                prior_outgoing_amount=2_000,
                prior_cpf_documents=("98765432100", "98765432101"),
            )
        ],
    )
    assert "tree_evasion" not in triggered(cnpj_result)


def test_destination_amount_threshold_depends_on_document_type():
    cpf = analyze(
        transaction(amount=POLICY.destination_type_fixed_cents["cpf"]),
        [],
        POLICY,
    )
    assert triggered(cpf)["destination_type_amount"]["points"] == 3

    cnpj = analyze(
        transaction(
            amount=POLICY.destination_type_fixed_cents["cnpj"],
            destination_document_number="12345678000195",
        ),
        [],
        POLICY,
    )
    assert triggered(cnpj)["destination_type_amount"]["points"] == 2

    below_cnpj_limit = analyze(
        transaction(
            amount=POLICY.destination_type_fixed_cents["cnpj"] - 1,
            destination_document_number="12345678000195",
        ),
        [],
        POLICY,
    )
    assert "destination_type_amount" not in triggered(below_cnpj_limit)


def test_amount_rules_learn_from_effective_history_and_include_metadata_basis():
    history = [
        previous(
            minutes=minutes,
            amount=40_000,
            destination_document_number=f"{index + 1:011d}",
            id=f"amount-history-{index}",
        )
        for index, minutes in enumerate(range(1, POLICY.amount_min_samples + 1))
    ]

    learned_median = analyze(transaction(amount=70_000), history, POLICY)
    assert triggered(learned_median)["amount_vs_median"]["basis"] == "history"
    assert triggered(learned_median)["amount_vs_median"]["limit"] == 70_000

    learned_destination = analyze(transaction(amount=100_000), history, POLICY)
    assert triggered(learned_destination)["destination_type_amount"]["basis"] == "history"
    assert triggered(learned_destination)["destination_type_amount"]["limit"] == 100_000

    high_value = analyze(transaction(amount=500_000), history, POLICY)
    assert triggered(high_value)["high_value_review"]["basis"] == "history"
    assert triggered(high_value)["high_value_review"]["requires_2fa"] is True


def test_amount_profiles_use_matching_destination_type_and_ignore_rejected_history():
    cnpj = "12345678000195"
    history = [
        previous(
            minutes=index + 1,
            amount=600_000,
            destination_document_number=cnpj,
            id=f"cnpj-amount-{index}",
        )
        for index in range(POLICY.amount_min_samples)
    ]
    history.append(
        previous(
            minutes=20,
            amount=1,
            destination_document_number="98765432100",
            status="rejected",
            id="rejected-cpf",
        )
    )

    result = analyze(
        transaction(
            amount=1_050_000,
            destination_document_number="11111111000199",
        ),
        history,
        POLICY,
    )

    assert triggered(result)["destination_type_amount"]["basis"] == "history"
    assert triggered(result)["destination_type_amount"]["limit"] == 1_050_000



def test_night_rule_uses_sao_paulo_time_and_cpf_only():
    night = NOW.replace(hour=1)
    result = analyze(transaction(transaction_date=night, amount=100_001), [], POLICY)
    assert triggered(result)["night_over_limit"]["points"] == 2
    assert triggered(result)["night_over_limit"]["block"] is True
    assert result["status"] == "rejected"
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
    night_rejection = analyze(night_transaction, [], POLICY)
    assert night_rejection["metadata"]["score"] >= POLICY.night_points
    assert triggered(night_rejection)["night_over_limit"]["block"] is True
    assert night_rejection["status"] == "rejected"

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


def test_new_device_and_impossible_travel_together_hard_reject_without_points():
    history = [
        previous(
            minutes=index + 1,
            source_device_id=f"old-{index}",
            source_latitude=-23.56,
            source_longitude=-46.65,
        )
        for index in range(POLICY.new_device_min_history)
    ]

    result = analyze(
        transaction(
            amount=POLICY.new_device_min_amount_cents,
            source_latitude=40.71,
            source_longitude=-74.01,
        ),
        history,
        POLICY,
    )

    rules = triggered(result)
    assert "new_device" in rules
    assert "impossible_travel" in rules
    assert rules["new_device_impossible_travel"]["block"] is True
    assert rules["new_device_impossible_travel"]["points"] == 0
    assert result["status"] == "rejected"


def test_new_device_impossible_travel_subrule_requires_both_signals():
    history = [
        previous(
            minutes=index + 1,
            source_device_id=f"old-{index}",
            source_latitude=-23.56,
            source_longitude=-46.65,
        )
        for index in range(POLICY.new_device_min_history)
    ]

    existing_device = analyze(
        transaction(
            amount=POLICY.new_device_min_amount_cents,
            source_device_id="old-0",
            source_latitude=40.71,
            source_longitude=-74.01,
        ),
        history,
        POLICY,
    )

    assert "impossible_travel" in triggered(existing_device)
    assert "new_device" not in triggered(existing_device)
    assert "new_device_impossible_travel" not in triggered(existing_device)


def test_burst_has_exclusive_step_and_rejection_tiers():
    result = analyze(transaction(), [previous(minutes=9 - index) for index in range(
        POLICY.burst_fixed["cpf"][0] - 1
    )], POLICY)
    assert triggered(result)["burst"]["points"] == POLICY.burst_points

    blocked = analyze(
        transaction(),
        [previous(minutes=9 - index) for index in range(
            POLICY.burst_fixed["cpf"][1] - 1
        )],
        POLICY,
    )
    assert triggered(blocked)["burst"]["block"] is True
    assert triggered(blocked)["burst"]["points"] == 0

    cutoff_only = analyze(transaction(), [previous(minutes=10)], POLICY)
    assert "burst" not in triggered(cutoff_only)


def test_velocity_windows_use_caller_event_time_not_receipt_time():
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

    assert "burst" not in triggered(result)


def test_rolling_total_excludes_rejected_and_uses_strict_thresholds():
    history = [
        previous(amount=900_000, status="rejected"),
        previous(minutes=2, amount=1_000_001, status="approved"),
    ]
    result = analyze(transaction(amount=1), history, POLICY)
    assert triggered(result)["rolling_24h_total"]["points"] == 2

    critical = analyze(
        transaction(amount=1),
        [previous(amount=POLICY.daily_fixed_cents["cpf"][1])],
        POLICY,
    )
    assert triggered(critical)["rolling_24h_total"]["requires_2fa"] is True
    assert triggered(critical)["rolling_24h_total"]["block"] is False
    assert critical["status"] == "two_factor_required"
    at_boundary = analyze(
        transaction(amount=1),
        [previous(amount=POLICY.daily_fixed_cents["cpf"][0] - 2)],
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


def test_amount_median_uses_robust_z_score_and_mad_floor():
    stable_history = [
        previous(minutes=index + 1, amount=100_000)
        for index in range(POLICY.amount_min_samples)
    ]
    high_deviation = analyze(transaction(amount=175_000), stable_history, POLICY)
    assert "amount_vs_median" in triggered(high_deviation)

    below_threshold = analyze(transaction(amount=174_999), stable_history, POLICY)
    assert "amount_vs_median" not in triggered(below_threshold)


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

    current_without_geo = analyze(
        transaction(source_latitude=None, source_longitude=None),
        [previous(minutes=5, source_latitude=0.0, source_longitude=0.0)],
        POLICY,
    )
    skipped_travel = {
        item["rule"]: item["reason"]
        for item in current_without_geo["metadata"]["rules_skipped"]
    }
    assert skipped_travel["impossible_travel"] == "Geolocalizacao ausente no Pix atual."


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
        "payee_burst",
        "mule_fan_in",
    }.intersection(triggered(self_result))
    self_skipped = {
        item["rule"] for item in self_result["metadata"]["rules_skipped"]
    }
    assert {"young_destination", "new_payee", "payee_burst", "mule_fan_in"} <= self_skipped


def test_obvious_low_risk_transaction_is_approved():
    result = analyze(transaction(), [], POLICY)

    assert result["status"] == "approved"
    assert result["metadata"]["score"] == 0
    assert result["metadata"]["rules_triggered"] == []


def test_rejected_history_does_not_inflate_effective_total():
    history = [
        previous(
            amount=POLICY.daily_fixed_cents["cpf"][1],
            status="rejected",
        )
    ]

    result = analyze(transaction(amount=1_000), history, POLICY)

    assert result["status"] == "approved"
    assert "rolling_24h_total" not in triggered(result)


def test_out_of_window_history_does_not_trigger_burst_or_rolling_total():
    old = previous(
        amount=POLICY.daily_fixed_cents["cpf"][1],
        received_at=NOW - timedelta(hours=POLICY.daily_window_hours, seconds=1),
        transaction_date=NOW - timedelta(hours=POLICY.daily_window_hours, seconds=1),
    )

    result = analyze(transaction(), [old], POLICY)

    assert result["status"] == "approved"
    assert not {"burst", "rolling_24h_total"}.intersection(triggered(result))


def test_tenth_recent_payer_attempt_is_rejected():
    history = [
        previous(minutes=index + 1)
        for index in range(POLICY.burst_fixed["cpf"][1] - 1)
    ]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "rejected"
    assert triggered(result)["burst"]["block"] is True


def test_effective_rolling_total_above_reject_limit_is_rejected():
    history = [previous(amount=POLICY.daily_fixed_cents["cpf"][1])]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["rolling_24h_total"]["requires_2fa"] is True
    assert triggered(result)["rolling_24h_total"]["block"] is False


def test_fifth_recent_payer_attempt_requires_two_factor():
    history = [
        previous(minutes=index + 1)
        for index in range(POLICY.burst_fixed["cpf"][0] - 1)
    ]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["burst"]["points"] == POLICY.burst_points


def test_rolling_total_above_two_factor_limit_requires_two_factor():
    result = analyze(
        transaction(amount=POLICY.daily_fixed_cents["cpf"][0] + 1),
        [],
        POLICY,
    )

    assert result["status"] == "two_factor_required"
    assert triggered(result)["rolling_24h_total"]["points"] == POLICY.daily_points


def test_burst_and_rolling_thresholds_are_higher_for_cnpj_payers():
    cnpj = "12345678000195"
    burst_history = [
        previous(
            minutes=index + 1,
            source_document_number=cnpj,
        )
        for index in range(POLICY.burst_fixed["cpf"][0] - 1)
    ]
    assert "burst" not in triggered(
        analyze(transaction(source_document_number=cnpj), burst_history, POLICY)
    )
    cnpj_burst = analyze(
        transaction(source_document_number=cnpj),
        [
            previous(
                minutes=1 + index % 9,
                source_document_number=cnpj,
                id=f"cnpj-attempt-{index}",
                status="rejected",
            )
            for index in range(POLICY.burst_fixed["cnpj"][0] - 1)
        ],
        POLICY,
    )
    assert triggered(cnpj_burst)["burst"]["points"] == POLICY.burst_points

    daily_two_factor = analyze(
        transaction(
            amount=POLICY.daily_fixed_cents["cnpj"][0] + 1,
            source_document_number=cnpj,
        ),
        [],
        POLICY,
    )
    assert triggered(daily_two_factor)["rolling_24h_total"]["points"] == POLICY.daily_points
    assert triggered(daily_two_factor)["rolling_24h_total"]["basis"] == "fixed"
    assert "requires_2fa" not in triggered(daily_two_factor)["rolling_24h_total"]

    below_daily_two_factor = analyze(
        transaction(
            amount=POLICY.daily_fixed_cents["cnpj"][0] - 1,
            source_document_number=cnpj,
        ),
        [],
        POLICY,
    )
    assert "rolling_24h_total" not in triggered(below_daily_two_factor)


def test_burst_learning_uses_effective_peak_and_attempts_for_current_count():
    effective_history = [
        previous(minutes=minutes, id=f"old-effective-{index}")
        for index, minutes in enumerate(
            [60, 120, 180, 240, 300, 360, 420, 480, 540, 600]
        )
    ]
    rejected_attempts = [
        previous(
            minutes=index + 1,
            status="rejected",
            id=f"recent-rejected-{index}",
        )
        for index in range(4)
    ]
    result = analyze(
        transaction(),
        [*effective_history, *rejected_attempts],
        POLICY,
    )

    burst_rule = triggered(result)["burst"]
    assert burst_rule["points"] == POLICY.burst_points
    assert burst_rule["basis"] == "history"
    assert burst_rule["limit"] == 4


def test_burst_learned_peak_can_raise_threshold_above_fixed_defaults():
    historical_peak = [
        previous(
            minutes=1 + index % 9,
            transaction_date=NOW - timedelta(days=1, minutes=index % 9),
            id=f"historical-peak-{index}",
        )
        for index in range(30)
    ]
    current_rejected_attempts = [
        previous(
            minutes=index + 1,
            status="rejected",
            id=f"current-rejected-{index}",
        )
        for index in range(44)
    ]

    result = analyze(
        transaction(),
        [*historical_peak, *current_rejected_attempts],
        POLICY,
    )

    assert "burst" not in triggered(result)


def test_daily_total_learns_from_prior_active_local_days():
    history = [
        previous(
            amount=40_000,
            transaction_date=NOW - timedelta(days=index + 1),
            id=f"active-day-{index}",
        )
        for index in range(POLICY.daily_min_active_days)
    ]

    result = analyze(transaction(amount=200_000), history, POLICY)

    daily_rule = triggered(result)["rolling_24h_total"]
    assert daily_rule["basis"] == "history"
    assert daily_rule["limit"] == 200_000
    assert daily_rule["points"] == POLICY.daily_points
    assert "requires_2fa" not in daily_rule


def test_payee_burst_counts_attempts_and_requires_unfamiliar_payee():
    destination = "98765432100"
    history = [
        previous(
            minutes=index + 1,
            amount=50_000,
            destination_document_number=destination,
            id=f"payee-burst-{index}",
        )
        for index in range(3)
    ]

    result = analyze(
        transaction(amount=50_000, destination_document_number=destination),
        history,
        POLICY,
    )

    payee_burst = triggered(result)["payee_burst"]
    assert payee_burst["points"] == POLICY.payee_burst_warn_points
    assert payee_burst["basis"] == "fixed"
    assert payee_burst["limit"] == POLICY.payee_burst_warn_count["cpf"]

    learned_relationship = previous(
        minutes=60,
        amount=10_000,
        destination_document_number=destination,
        id="known-payee",
    )
    known_result = analyze(
        transaction(amount=50_000, destination_document_number=destination),
        [*history, learned_relationship],
        POLICY,
    )
    assert "payee_burst" not in triggered(known_result)

    below_sum = analyze(
        transaction(
            amount=5_000,
            destination_document_number=destination,
        ),
        [
            previous(
                minutes=index + 1,
                amount=5_000,
                destination_document_number=destination,
                id=f"low-payee-burst-{index}",
            )
            for index in range(3)
        ],
        POLICY,
    )
    assert "payee_burst" not in triggered(below_sum)


def test_payee_burst_raises_threshold_using_average_prior_pair_windows():
    destination = "98765432100"
    historical_attempts = [
        previous(
            minutes=31 + 30 * window_index + attempt_index,
            amount=50_000,
            destination_document_number=destination,
            status="rejected",
            id=f"payee-average-{window_index}-{attempt_index}",
        )
        for window_index in range(POLICY.payee_burst_min_history_windows)
        for attempt_index in range(2)
    ]
    current_window_attempts = [
        previous(
            minutes=index + 1,
            amount=50_000,
            destination_document_number=destination,
            id=f"payee-current-window-{index}",
        )
        for index in range(4)
    ]

    result = analyze(
        transaction(amount=50_000, destination_document_number=destination),
        [*historical_attempts, *current_window_attempts],
        POLICY,
    )

    rule = triggered(result)["payee_burst"]
    assert rule["points"] == POLICY.payee_burst_warn_points
    assert rule["basis"] == "history_average"
    assert rule["limit"] == 4
    assert "media historica de 2.00 tentativas por janela" in rule["reason"]

    strong_current_attempts = [
        previous(
            minutes=index + 1,
            amount=50_000,
            destination_document_number=destination,
            id=f"payee-strong-current-window-{index}",
        )
        for index in range(7)
    ]
    strong_result = analyze(
        transaction(amount=50_000, destination_document_number=destination),
        [*historical_attempts, *strong_current_attempts],
        POLICY,
    )

    strong_rule = triggered(strong_result)["payee_burst"]
    assert strong_rule["points"] == POLICY.payee_burst_strong_points
    assert strong_rule["basis"] == "history_average"
    assert strong_rule["limit"] == 8


def test_payee_burst_has_strong_tier_and_higher_cnpj_count():
    cpf_destination = "98765432100"
    cpf_strong = analyze(
        transaction(
            amount=50_000,
            destination_document_number=cpf_destination,
        ),
        [
            previous(
                minutes=index + 1,
                amount=50_000,
                destination_document_number=cpf_destination,
                id=f"strong-cpf-payee-{index}",
            )
            for index in range(POLICY.payee_burst_strong_count["cpf"] - 1)
        ],
        POLICY,
    )
    assert (
        triggered(cpf_strong)["payee_burst"]["points"]
        == POLICY.payee_burst_strong_points
    )

    cnpj_destination = "98765432000100"
    cnpj_warning = analyze(
        transaction(
            amount=25_000,
            destination_document_number=cnpj_destination,
        ),
        [
            previous(
                minutes=index + 1,
                amount=25_000,
                destination_document_number=cnpj_destination,
                id=f"warn-cnpj-payee-{index}",
            )
            for index in range(POLICY.payee_burst_warn_count["cnpj"] - 1)
        ],
        POLICY,
    )
    assert (
        triggered(cnpj_warning)["payee_burst"]["points"]
        == POLICY.payee_burst_warn_points
    )


def test_daily_critical_level_requires_2fa_instead_of_blocking():
    result = analyze(
        transaction(amount=POLICY.daily_fixed_cents["cpf"][1]),
        [],
        POLICY,
    )

    rule = triggered(result)["rolling_24h_total"]
    assert result["status"] == "two_factor_required"
    assert rule["requires_2fa"] is True
    assert rule["block"] is False
    assert rule["basis"] == "fixed"


def test_prior_daily_activity_does_not_create_automatic_daily_block():
    result = analyze(
        transaction(),
        [previous(amount=POLICY.daily_fixed_cents["cpf"][1] + 1)],
        POLICY,
    )

    rule = triggered(result)["rolling_24h_total"]
    assert result["status"] == "two_factor_required"
    assert rule["requires_2fa"] is True
    assert rule["block"] is False


def test_new_device_and_first_payee_require_two_factor():
    history = [
        previous(
            minutes=index + 1,
            amount=1_000,
            source_device_id=f"old-device-{index}",
            destination_document_number=f"{index + 1:011d}",
        )
        for index in range(POLICY.new_device_min_history)
    ]

    result = analyze(
        transaction(amount=POLICY.new_payee_min_amount_cents),
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
        for index in range(POLICY.mule_fan_in_warn_count - 1)
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
        for index in range(POLICY.shared_device_min_payers - 1)
    ]

    result = analyze(transaction(), history, POLICY)

    assert result["status"] == "two_factor_required"
    assert triggered(result)["shared_device"]["points"] == POLICY.shared_device_points
