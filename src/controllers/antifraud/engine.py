from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from statistics import median
from zoneinfo import ZoneInfo

from controllers.antifraud.constants import AntifraudPolicy


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
    now = transaction.received_at
    if now.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    if any(item.received_at.utcoffset() is None for item in history):
        raise ValueError("history received_at values must be timezone-aware")
    prior = [
        item
        for item in history
        if item.id != transaction.id and item.received_at < now
    ]
    score = 0
    blocked = False
    triggered: list[dict] = []
    skipped: list[dict] = []
    self_payment = transaction.source_document_number == transaction.destination_document_number

    def trigger(rule: str, points: int, block: bool, reason: str) -> None:
        nonlocal score, blocked
        score += points
        blocked = blocked or block
        triggered.append(
            {"rule": rule, "points": points, "block": block, "reason": reason}
        )

    def skip(rule: str, reason: str) -> None:
        skipped.append({"rule": rule, "reason": reason})

    def in_window(item: TransactionData, window: timedelta) -> bool:
        return now - window <= item.received_at < now

    def effective(item: TransactionData) -> bool:
        return item.status != "rejected"

    payer_attempts = [
        item for item in prior
        if item.source_document_number == transaction.source_document_number
    ]
    recent_attempts_10m = [
        item for item in payer_attempts
        if now - timedelta(minutes=policy.burst_window_minutes) < item.received_at
    ]

    if transaction.amount > policy.hard_ceiling_cents:
        trigger(
            "hard_ceiling",
            0,
            True,
            f"Valor observado de {transaction.amount} centavos acima do limite de {policy.hard_ceiling_cents}.",
        )

    local_hour = transaction.transaction_date.astimezone(ZoneInfo(policy.timezone)).hour
    if (
        len(transaction.source_document_number) == policy.cpf_digits
        and (local_hour >= policy.night_start_hour or local_hour < policy.night_end_hour)
        and transaction.amount > policy.night_amount_cents
    ):
        trigger(
            "night_over_limit",
            policy.night_points,
            False,
            f"CPF realizou {transaction.amount} centavos no horario noturno (hora local {local_hour}; limite {policy.night_amount_cents}).",
        )

    burst_count = len(recent_attempts_10m) + 1
    if burst_count >= policy.burst_reject_count:
        trigger(
            "burst",
            0,
            True,
            f"{burst_count} tentativas do pagador em {policy.burst_window_minutes} minutos (bloqueio a partir de {policy.burst_reject_count}).",
        )
    elif burst_count >= policy.burst_two_factor_count:
        trigger(
            "burst",
            policy.burst_points,
            False,
            f"{burst_count} tentativas do pagador em {policy.burst_window_minutes} minutos (2FA a partir de {policy.burst_two_factor_count}).",
        )

    rolling_window = timedelta(hours=policy.rolling_24h_window_hours)
    rolling_movements = [
        item
        for item in payer_attempts
        if effective(item) and in_window(item, rolling_window)
    ]
    rolling_total = sum(item.amount for item in rolling_movements) + transaction.amount
    if rolling_total > policy.rolling_24h_reject_cents:
        trigger(
            "rolling_24h_total",
            0,
            True,
            f"Movimentacao efetiva observada de {rolling_total} centavos em 24 horas (bloqueio acima de {policy.rolling_24h_reject_cents}).",
        )
    elif rolling_total > policy.rolling_24h_two_factor_cents:
        trigger(
            "rolling_24h_total",
            policy.rolling_24h_points,
            False,
            f"Movimentacao efetiva observada de {rolling_total} centavos em 24 horas (2FA acima de {policy.rolling_24h_two_factor_cents}).",
        )

    median_window = timedelta(days=policy.amount_median_window_days)
    median_history = sorted(
        (
            item
            for item in payer_attempts
            if effective(item) and in_window(item, median_window)
        ),
        key=lambda item: (item.received_at, item.id),
        reverse=True,
    )[: policy.amount_median_max_samples]
    median_samples = [item.amount for item in median_history]
    if len(median_samples) < policy.amount_median_min_samples:
        skip(
            "amount_vs_median",
            f"Historico insuficiente: {len(median_samples)} de {policy.amount_median_min_samples} movimentacoes efetivas.",
        )
    else:
        reference_median = median(median_samples)
        if (
            transaction.amount > policy.amount_median_multiplier * reference_median
            and transaction.amount > policy.amount_median_min_cents
        ):
            trigger(
                "amount_vs_median",
                policy.amount_median_points,
                False,
                f"Valor de {transaction.amount} centavos supera {policy.amount_median_multiplier} vezes a mediana de {reference_median:g}.",
            )

    device_window = timedelta(days=policy.new_device_window_days)
    device_attempts = [
        item for item in payer_attempts if in_window(item, device_window)
    ]
    if len(device_attempts) < policy.new_device_min_attempts:
        skip(
            "new_device",
            f"Historico insuficiente: {len(device_attempts)} de {policy.new_device_min_attempts} tentativas do pagador.",
        )
    elif (
        transaction.amount >= policy.new_device_min_cents
        and all(item.source_device_id != transaction.source_device_id for item in device_attempts)
    ):
        trigger(
            "new_device",
            policy.new_device_points,
            False,
            f"Dispositivo {transaction.source_device_id} nao foi usado nas {len(device_attempts)} tentativas anteriores; valor de {transaction.amount} centavos.",
        )

    payer_age = max(
        now - transaction.source_account_opening_date,
        timedelta(0),
    )
    if (
        payer_age < timedelta(days=policy.young_payer_max_age_days)
        and transaction.amount > policy.young_payer_min_cents
    ):
        trigger(
            "young_payer_account",
            policy.young_payer_points,
            False,
            f"Conta do pagador tem {payer_age.total_seconds() / 86400:.2f} dias; transacao de {transaction.amount} centavos.",
        )

    geo_window = timedelta(hours=policy.impossible_travel_window_hours)
    geo_history = [
        item
        for item in payer_attempts
        if in_window(item, geo_window)
        and item.source_latitude is not None
        and item.source_longitude is not None
    ]
    if not geo_history:
        skip(
            "impossible_travel",
            "Historico insuficiente: nenhuma transacao anterior geolocalizada nas ultimas 24 horas.",
        )
    elif transaction.source_latitude is not None and transaction.source_longitude is not None:
        latest_geo = max(
            geo_history,
            key=lambda item: (item.received_at, item.id),
        )
        distance = _distance_km(
            float(latest_geo.source_latitude),
            float(latest_geo.source_longitude),
            float(transaction.source_latitude),
            float(transaction.source_longitude),
            policy.earth_radius_km,
        )
        elapsed_seconds = max(
            (now - latest_geo.received_at).total_seconds(),
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
                False,
                f"Deslocamento de {distance:.1f} km a {speed:.1f} km/h em menos de 24 horas.",
            )

    if not self_payment and transaction.amount >= policy.young_destination_min_cents:
        destination_age = max(
            now - transaction.destination_account_opening_date,
            timedelta(0),
        )
        if destination_age < timedelta(days=policy.young_destination_first_age_days):
            trigger(
                "young_destination",
                policy.young_destination_first_points,
                False,
                f"Conta de destino tem {destination_age.total_seconds() / 86400:.2f} dias (faixa abaixo de {policy.young_destination_first_age_days}).",
            )
        elif destination_age < timedelta(days=policy.young_destination_second_age_days):
            trigger(
                "young_destination",
                policy.young_destination_second_points,
                False,
                f"Conta de destino tem {destination_age.total_seconds() / 86400:.2f} dias (faixa abaixo de {policy.young_destination_second_age_days}).",
            )

    prior_effective_payee = any(
        effective(item)
        and item.source_document_number == transaction.source_document_number
        and item.destination_document_number == transaction.destination_document_number
        for item in prior
    )
    if (
        not self_payment
        and transaction.amount >= policy.new_payee_min_cents
        and not prior_effective_payee
    ):
        trigger(
            "new_payee",
            policy.new_payee_points,
            False,
            f"Nao ha movimentacao efetiva anterior para o favorecido {transaction.destination_document_number}; valor de {transaction.amount} centavos.",
        )

    if (
        not self_payment
        and len(transaction.destination_document_number) == policy.cpf_digits
    ):
        fan_in_window = timedelta(hours=policy.mule_fan_in_window_hours)
        payer_documents = {
            item.source_document_number
            for item in prior
            if item.destination_document_number == transaction.destination_document_number
            and in_window(item, fan_in_window)
        }
        payer_documents.add(transaction.source_document_number)
        fan_in_count = len(payer_documents)
        if fan_in_count >= policy.mule_fan_in_reject_count:
            trigger(
                "mule_fan_in",
                0,
                True,
                f"{fan_in_count} pagadores distintos enviaram para o CPF {transaction.destination_document_number} em 24 horas (bloqueio a partir de {policy.mule_fan_in_reject_count}).",
            )
        elif fan_in_count >= policy.mule_fan_in_two_factor_count:
            trigger(
                "mule_fan_in",
                policy.mule_fan_in_points,
                False,
                f"{fan_in_count} pagadores distintos enviaram para o CPF {transaction.destination_document_number} em 24 horas (2FA a partir de {policy.mule_fan_in_two_factor_count}).",
            )

    shared_window = timedelta(hours=policy.shared_device_window_hours)
    device_documents = {
        item.source_document_number
        for item in prior
        if item.source_device_id == transaction.source_device_id
        and in_window(item, shared_window)
    }
    device_documents.add(transaction.source_document_number)
    shared_count = len(device_documents)
    if shared_count >= policy.shared_device_min_documents:
        trigger(
            "shared_device",
            policy.shared_device_points,
            False,
            f"Dispositivo {transaction.source_device_id} foi usado por {shared_count} documentos de pagadores distintos em 24 horas.",
        )

    if blocked or score >= policy.reject_score:
        status = "rejected"
    elif score >= policy.two_factor_score:
        status = "two_factor_required"
    else:
        status = "approved"

    metadata = {
        "engine_version": policy.engine_version,
        "score": score,
        "thresholds": {
            "two_factor": policy.two_factor_score,
            "reject": policy.reject_score,
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
