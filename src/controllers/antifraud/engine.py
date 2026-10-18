from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from controllers.antifraud.constants import AntifraudPolicy
from controllers.antifraud.limits import (
    LearnedLimit,
    average_window_thresholds,
    learned_burst_thresholds,
    resolve_learned_limit,
)


@dataclass(frozen=True)
class TransactionData:
    id: str
    amount: int
    transaction_date: datetime
    received_at: datetime
    source_document_number: str
    source_account_opening_date: datetime
    destination_document_number: str
    destination_account_opening_date: datetime
    source_device_id: str
    source_latitude: float | None
    source_longitude: float | None
    status: str | None = None


def analyze(
    transaction: TransactionData,
    history: list[TransactionData],
    policy: AntifraudPolicy,
) -> dict:
    now = transaction.transaction_date
    if now.utcoffset() is None:
        raise ValueError("transaction_date must be timezone-aware")
    if any(item.transaction_date.utcoffset() is None for item in history):
        raise ValueError("history transaction_date values must be timezone-aware")

    history_cutoff = now - timedelta(days=policy.history_window_days)
    prior = [
        item
        for item in history
        if item.id != transaction.id and item.transaction_date < now
    ]
    recent = [item for item in prior if item.transaction_date >= history_cutoff]
    payer_attempts = [
        item
        for item in recent
        if item.source_document_number == transaction.source_document_number
    ]
    payer_effective = [item for item in payer_attempts if item.status != "rejected"]
    self_payment = (
        transaction.source_document_number == transaction.destination_document_number
    )

    score = 0
    blocked = False
    requires_2fa = False
    triggered: list[dict] = []
    skipped: list[dict] = []

    def trigger(
        rule: str,
        points: int,
        reason: str,
        *,
        block: bool = False,
        force_2fa: bool = False,
        basis: str | None = None,
        limit: float | None = None,
    ) -> None:
        nonlocal score, blocked, requires_2fa
        score += points
        blocked = blocked or block
        requires_2fa = requires_2fa or force_2fa
        item = {
            "rule": rule,
            "points": points,
            "block": block,
            "reason": reason,
        }
        if force_2fa:
            item["requires_2fa"] = True
        if basis is not None:
            item["basis"] = basis
        if limit is not None:
            item["limit"] = round(limit, 2)
        triggered.append(item)

    def skip(rule: str, reason: str) -> None:
        skipped.append({"rule": rule, "reason": reason})

    def in_window(item: TransactionData, window: timedelta) -> bool:
        return now - window <= item.transaction_date < now

    def effective(item: TransactionData) -> bool:
        return item.status != "rejected"

    def document_kind(document_number: str) -> str | None:
        if len(document_number) == policy.cpf_digits:
            return "cpf"
        if len(document_number) == policy.cnpj_digits:
            return "cnpj"
        return None

    def limit_for(
        samples: list[int],
        kind: str,
        floors: dict[str, int],
        fixed: dict[str, int],
        multiplier: float,
    ) -> LearnedLimit:
        return resolve_learned_limit(
            samples=samples,
            minimum_samples=policy.amount_min_samples,
            floor=floors[kind],
            fixed=fixed[kind],
            multiplier=multiplier,
            mad_factor=policy.robust_mad_factor,
            floor_ratio=policy.robust_scale_floor_ratio,
        )

    def sample_amounts(items: list[TransactionData]) -> list[int]:
        ordered = sorted(
            items,
            key=lambda item: (item.transaction_date, item.id),
            reverse=True,
        )
        return [item.amount for item in ordered[: policy.sample_max_rows]]

    payer_kind = document_kind(transaction.source_document_number)
    destination_kind = document_kind(transaction.destination_document_number)

    # 1. Night limit
    local_hour = now.astimezone(ZoneInfo(policy.timezone)).hour
    if (
        payer_kind == "cpf"
        and (local_hour >= policy.night_start_hour or local_hour < policy.night_end_hour)
        and transaction.amount > policy.night_amount_cents
    ):
        trigger(
            "night_over_limit",
            policy.night_points,
            f"CPF realizou {transaction.amount} centavos no horario noturno "
            f"(hora local {local_hour}; limite {policy.night_amount_cents}).",
        )

    # 2. Amount anomaly against all effective payer transfers
    general_samples = sample_amounts(payer_effective)
    if len(general_samples) < policy.amount_min_samples:
        skip(
            "amount_vs_median",
            f"Historico insuficiente: {len(general_samples)} de "
            f"{policy.amount_min_samples} movimentacoes efetivas.",
        )
    else:
        median_limit = limit_for(
            general_samples,
            "cpf",
            {"cpf": policy.median_min_amount_cents, "cnpj": policy.median_min_amount_cents},
            {
                "cpf": policy.median_min_amount_cents,
                "cnpj": policy.median_min_amount_cents,
            },
            policy.warn_z,
        )
        if transaction.amount >= median_limit.value:
            trigger(
                "amount_vs_median",
                policy.median_points,
                f"Valor de {transaction.amount} centavos atinge o limite aprendido de "
                f"{median_limit.value:.0f} (mediana {median_limit.center:.0f} + "
                f"{policy.warn_z:g} x escala).",
                basis="history",
                limit=median_limit.value,
            )

    # 3. High-value review uses recipient kind and the general payer profile.
    if destination_kind is None:
        skip(
            "high_value_review",
            "Tipo de documento do destinatario desconhecido; esperado CPF ou CNPJ.",
        )
    else:
        high_value_limit = limit_for(
            general_samples,
            destination_kind,
            policy.high_value_floor_cents,
            policy.high_value_fixed_ceiling_cents,
            policy.critical_z,
        )
        if transaction.amount >= high_value_limit.value:
            source = (
                f"limite aprendido de {high_value_limit.value:.0f} centavos "
                f"(mediana {high_value_limit.center:.0f} + {policy.critical_z:g} x escala; "
                f"piso {policy.high_value_floor_cents[destination_kind]})"
                if high_value_limit.basis == "history"
                else f"teto fixo de {high_value_limit.value:.0f} centavos"
            )
            trigger(
                "high_value_review",
                0,
                f"Valor de {transaction.amount} centavos atinge o {source} para "
                f"destinatario {destination_kind.upper()}; exige confirmacao do cliente.",
                force_2fa=True,
                basis=high_value_limit.basis,
                limit=high_value_limit.value,
            )

    # 4. Amount anomaly for this recipient-document type.
    if destination_kind is None:
        skip(
            "destination_type_amount",
            "Tipo de documento do destinatario desconhecido; esperado CPF ou CNPJ.",
        )
    else:
        destination_samples = sample_amounts(
            [
                item
                for item in payer_effective
                if document_kind(item.destination_document_number) == destination_kind
            ]
        )
        destination_limit = limit_for(
            destination_samples,
            destination_kind,
            policy.destination_type_floor_cents,
            policy.destination_type_fixed_cents,
            policy.warn_z,
        )
        if transaction.amount >= destination_limit.value:
            trigger(
                "destination_type_amount",
                policy.destination_type_points[destination_kind],
                f"Valor de {transaction.amount} centavos atinge o limite "
                f"{destination_limit.basis} de {destination_limit.value:.0f} centavos "
                f"para destinatarios {destination_kind.upper()}.",
                basis=destination_limit.basis,
                limit=destination_limit.value,
            )

    # 5. Adaptive burst rule; attempts determine current velocity, effective
    # transfers determine the payer's learned peak.
    if payer_kind is None:
        skip("burst", "Tipo de documento do pagador desconhecido; esperado CPF ou CNPJ.")
    else:
        burst_window = timedelta(minutes=policy.burst_window_minutes)
        current_attempt_count = 1 + sum(
            now - burst_window < item.transaction_date < now
            for item in payer_attempts
        )
        effective_timestamps = [item.transaction_date for item in payer_effective]
        warn_threshold, block_threshold, burst_basis = learned_burst_thresholds(
            timestamps=effective_timestamps,
            minimum_samples=policy.burst_min_history,
            fixed=policy.burst_fixed[payer_kind],
            warn_floor=policy.burst_warn_floor[payer_kind],
            block_floor=policy.burst_block_floor[payer_kind],
            warn_factor=policy.burst_warn_factor,
            block_factor=policy.burst_block_factor,
            window=burst_window,
        )
        if current_attempt_count >= block_threshold:
            trigger(
                "burst",
                0,
                f"{current_attempt_count} tentativas em {policy.burst_window_minutes} "
                f"minutos atingem o limite de bloqueio {block_threshold} ({burst_basis}).",
                block=True,
                basis=burst_basis,
                limit=block_threshold,
            )
        elif current_attempt_count >= warn_threshold:
            trigger(
                "burst",
                policy.burst_points,
                f"{current_attempt_count} tentativas em {policy.burst_window_minutes} "
                f"minutos atingem o limite de alerta {warn_threshold} ({burst_basis}).",
                basis=burst_basis,
                limit=warn_threshold,
            )

    # 6. Adaptive rolling daily total, compared with prior active local days.
    if payer_kind is None:
        skip(
            "rolling_24h_total",
            "Tipo de documento do pagador desconhecido; esperado CPF ou CNPJ.",
        )
    else:
        daily_window = timedelta(hours=policy.daily_window_hours)
        current_total = transaction.amount + sum(
            item.amount
            for item in payer_effective
            if in_window(item, daily_window)
        )
        local_now = now.astimezone(ZoneInfo(policy.timezone))
        current_local_day = local_now.date()
        daily_totals: dict[object, int] = {}
        for item in payer_effective:
            item_local_day = item.transaction_date.astimezone(
                ZoneInfo(policy.timezone)
            ).date()
            if item_local_day < current_local_day:
                daily_totals[item_local_day] = (
                    daily_totals.get(item_local_day, 0) + item.amount
                )
        daily_samples = list(daily_totals.values())
        if len(daily_samples) >= policy.daily_min_active_days:
            daily_profile = resolve_learned_limit(
                samples=daily_samples,
                minimum_samples=policy.daily_min_active_days,
                floor=policy.daily_warn_floor_cents[payer_kind],
                fixed=policy.daily_fixed_cents[payer_kind][0],
                multiplier=policy.warn_z,
                mad_factor=policy.robust_mad_factor,
                floor_ratio=policy.robust_scale_floor_ratio,
            )
            critical_profile = resolve_learned_limit(
                samples=daily_samples,
                minimum_samples=policy.daily_min_active_days,
                floor=policy.daily_critical_floor_cents[payer_kind],
                fixed=policy.daily_fixed_cents[payer_kind][1],
                multiplier=policy.critical_z,
                mad_factor=policy.robust_mad_factor,
                floor_ratio=policy.robust_scale_floor_ratio,
            )
        else:
            daily_profile = LearnedLimit(
                float(policy.daily_fixed_cents[payer_kind][0]), "fixed"
            )
            critical_profile = LearnedLimit(
                float(policy.daily_fixed_cents[payer_kind][1]), "fixed"
            )
        if current_total >= critical_profile.value:
            trigger(
                "rolling_24h_total",
                0,
                f"Total de {current_total} centavos atinge o nivel critico "
                f"{critical_profile.value:.0f} para pagador {payer_kind.upper()}; "
                "exige 2FA.",
                force_2fa=True,
                basis=critical_profile.basis,
                limit=critical_profile.value,
            )
        elif current_total >= daily_profile.value:
            trigger(
                "rolling_24h_total",
                policy.daily_points,
                f"Total de {current_total} centavos atinge o alerta "
                f"{daily_profile.value:.0f} para pagador {payer_kind.upper()}.",
                basis=daily_profile.basis,
                limit=daily_profile.value,
            )

    # 7. New device uses all attempts in the profile window.
    device_attempts = [
        item
        for item in payer_attempts
        if now - timedelta(days=policy.history_window_days)
        <= item.transaction_date
        < now
    ]
    if len(device_attempts) < policy.new_device_min_history:
        skip(
            "new_device",
            f"Historico insuficiente: {len(device_attempts)} de "
            f"{policy.new_device_min_history} tentativas do pagador.",
        )
    elif (
        transaction.amount >= policy.new_device_min_amount_cents
        and all(item.source_device_id != transaction.source_device_id for item in device_attempts)
    ):
        trigger(
            "new_device",
            policy.new_device_points,
            f"Dispositivo {transaction.source_device_id} nao foi usado nas "
            f"{len(device_attempts)} tentativas anteriores; valor "
            f"{transaction.amount} centavos.",
        )

    # 8. Young payer account.
    payer_age = max(now - transaction.source_account_opening_date, timedelta(0))
    if (
        payer_age < timedelta(days=policy.young_payer_max_age_days)
        and transaction.amount > policy.young_payer_min_amount_cents
    ):
        trigger(
            "young_payer_account",
            policy.young_payer_points,
            f"Conta do pagador tem {payer_age.total_seconds() / 86400:.2f} dias; "
            f"transacao de {transaction.amount} centavos.",
        )

    # 9. Impossible travel.
    geo_history = [
        item
        for item in payer_attempts
        if in_window(
            item,
            timedelta(hours=policy.impossible_travel_window_hours),
        )
        and item.source_latitude is not None
        and item.source_longitude is not None
    ]
    if transaction.source_latitude is None or transaction.source_longitude is None:
        skip("impossible_travel", "Geolocalizacao ausente no Pix atual.")
    elif not geo_history:
        skip(
            "impossible_travel",
            "Historico insuficiente: nenhuma transacao anterior geolocalizada "
            "nas ultimas 24 horas.",
        )
    else:
        latest_geo = max(
            geo_history,
            key=lambda item: (item.transaction_date, item.id),
        )
        distance = _distance_km(
            float(latest_geo.source_latitude),
            float(latest_geo.source_longitude),
            float(transaction.source_latitude),
            float(transaction.source_longitude),
            policy.earth_radius_km,
        )
        elapsed_seconds = max(
            (now - latest_geo.transaction_date).total_seconds(),
            policy.impossible_travel_min_elapsed_seconds,
        )
        speed = distance / (elapsed_seconds / 3600)
        if (
            distance >= policy.impossible_travel_min_distance_km
            and speed > policy.impossible_travel_min_speed_kmh
        ):
            trigger(
                "impossible_travel",
                policy.impossible_travel_points,
                f"Deslocamento de {distance:.1f} km a {speed:.1f} km/h "
                "em menos de 24 horas.",
            )

    # 10. Young destination.
    if self_payment:
        skip("young_destination", "Pagador e destinatario sao o mesmo documento.")
    elif transaction.amount >= policy.young_destination_min_amount_cents:
        destination_age = max(
            now - transaction.destination_account_opening_date,
            timedelta(0),
        )
        if destination_age < timedelta(days=policy.young_destination_first_age_days):
            trigger(
                "young_destination",
                policy.young_destination_first_points,
                f"Conta de destino tem {destination_age.total_seconds() / 86400:.2f} "
                f"dias (menos de {policy.young_destination_first_age_days}); "
                f"valor {transaction.amount} centavos.",
            )
        elif destination_age < timedelta(days=policy.young_destination_second_age_days):
            trigger(
                "young_destination",
                policy.young_destination_second_points,
                f"Conta de destino tem {destination_age.total_seconds() / 86400:.2f} "
                f"dias (menos de {policy.young_destination_second_age_days}); "
                f"valor {transaction.amount} centavos.",
            )

    # 11. New payee relationship.
    if self_payment:
        skip("new_payee", "Pagador e destinatario sao o mesmo documento.")
    else:
        previously_paid = any(
            effective(item)
            and item.source_document_number == transaction.source_document_number
            and item.destination_document_number == transaction.destination_document_number
            for item in prior
        )
        if (
            not previously_paid
            and transaction.amount >= policy.new_payee_min_amount_cents
        ):
            trigger(
                "new_payee",
                policy.new_payee_points,
                f"Primeiro Pix efetivo deste pagador para o destinatario "
                f"{transaction.destination_document_number}; valor "
                f"{transaction.amount} centavos.",
            )

    # 12. Repeated payments to a previously unknown payee.
    if self_payment:
        skip("payee_burst", "Pagador e destinatario sao o mesmo documento.")
    elif destination_kind is None:
        skip("payee_burst", "Tipo de documento do destinatario desconhecido.")
    else:
        payee_window = timedelta(minutes=policy.payee_burst_window_minutes)
        matching_attempts = [
            item
            for item in payer_attempts
            if item.destination_document_number
            == transaction.destination_document_number
            and now - payee_window < item.transaction_date < now
        ]
        count = len(matching_attempts) + 1
        total = transaction.amount + sum(item.amount for item in matching_attempts)
        relationship_cutoff = now - payee_window
        historical_payee_attempts = [
            item
            for item in payer_attempts
            if item.destination_document_number
            == transaction.destination_document_number
            and history_cutoff <= item.transaction_date <= relationship_cutoff
        ]
        prior_relationship = any(
            effective(item)
            and item.source_document_number == transaction.source_document_number
            and item.destination_document_number
            == transaction.destination_document_number
            and history_cutoff <= item.transaction_date < relationship_cutoff
            for item in prior
        )
        if not prior_relationship and total >= policy.payee_burst_min_total_cents:
            (
                warn_count,
                strong_count,
                payee_burst_basis,
                average_count,
            ) = average_window_thresholds(
                timestamps=[
                    item.transaction_date for item in historical_payee_attempts
                ],
                window=payee_window,
                minimum_windows=policy.payee_burst_min_history_windows,
                fixed=(
                    policy.payee_burst_warn_count[destination_kind],
                    policy.payee_burst_strong_count[destination_kind],
                ),
                warn_factor=policy.payee_burst_average_warn_factor,
                strong_factor=policy.payee_burst_average_strong_factor,
            )
            average_description = (
                f"; media historica de {average_count:.2f} tentativas por janela"
                if average_count is not None
                else ""
            )
            if count >= strong_count:
                trigger(
                    "payee_burst",
                    policy.payee_burst_strong_points,
                    f"{count} tentativas somando {total} centavos para destinatario "
                    f"{destination_kind.upper()} sem relacionamento anterior"
                    f"{average_description}.",
                    basis=payee_burst_basis,
                    limit=strong_count,
                )
            elif count >= warn_count:
                trigger(
                    "payee_burst",
                    policy.payee_burst_warn_points,
                    f"{count} tentativas somando {total} centavos para destinatario "
                    f"{destination_kind.upper()} sem relacionamento anterior"
                    f"{average_description}.",
                    basis=payee_burst_basis,
                    limit=warn_count,
                )

    # 13. Mule fan-in.
    if self_payment:
        skip("mule_fan_in", "Pagador e destinatario sao o mesmo documento.")
    elif destination_kind == "cpf":
        fan_in_window = timedelta(hours=policy.mule_fan_in_window_hours)
        payer_documents = {
            item.source_document_number
            for item in recent
            if item.destination_document_number
            == transaction.destination_document_number
            and in_window(item, fan_in_window)
        }
        payer_documents.add(transaction.source_document_number)
        fan_in_count = len(payer_documents)
        if fan_in_count >= policy.mule_fan_in_block_count:
            trigger(
                "mule_fan_in",
                0,
                f"{fan_in_count} pagadores distintos enviaram ao mesmo CPF em 24 horas.",
                block=True,
            )
        elif fan_in_count >= policy.mule_fan_in_warn_count:
            trigger(
                "mule_fan_in",
                policy.mule_fan_in_points,
                f"{fan_in_count} pagadores distintos enviaram ao mesmo CPF em 24 horas.",
            )
    else:
        skip("mule_fan_in", "Regra aplicavel somente a destinatarios CPF.")

    # 14. Shared device.
    shared_window = timedelta(hours=policy.shared_device_window_hours)
    device_documents = {
        item.source_document_number
        for item in recent
        if item.source_device_id == transaction.source_device_id
        and in_window(item, shared_window)
    }
    device_documents.add(transaction.source_document_number)
    if len(device_documents) >= policy.shared_device_min_payers:
        trigger(
            "shared_device",
            policy.shared_device_points,
            f"Dispositivo {transaction.source_device_id} foi usado por "
            f"{len(device_documents)} documentos de pagadores distintos em 24 horas.",
        )

    if blocked or score >= policy.reject_score:
        status = "rejected"
    elif requires_2fa or score >= policy.two_factor_score:
        status = "two_factor_required"
    else:
        status = "approved"

    metadata = {
        "engine_version": policy.engine_version,
        "score": score,
        "thresholds": {
            "two_factor": policy.two_factor_score,
            "reject": policy.reject_score,
            "warn_z": policy.warn_z,
            "critical_z": policy.critical_z,
        },
        "rules_triggered": triggered,
    }
    if skipped:
        metadata["rules_skipped"] = skipped
    return {"status": status, "metadata": metadata}


def _distance_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
    earth_radius_km: float,
) -> float:
    latitude_delta = radians(latitude_2 - latitude_1)
    longitude_delta = radians(longitude_2 - longitude_1)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(latitude_1))
        * cos(radians(latitude_2))
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(min(1.0, haversine)))
