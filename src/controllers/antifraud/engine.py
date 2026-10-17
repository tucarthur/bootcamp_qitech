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
    now = transaction.transaction_date
    if now.utcoffset() is None:
        raise ValueError("transaction_date must be timezone-aware")
    if any(item.transaction_date.utcoffset() is None for item in history):
        raise ValueError("history transaction_date values must be timezone-aware")
    prior = [
        item
        for item in history
        if item.id != transaction.id and item.transaction_date < now
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
        return now - window <= item.transaction_date < now

    def effective(item: TransactionData) -> bool:
        return item.status != "rejected"

    payer_attempts = [
        item for item in prior
        if item.source_document_number == transaction.source_document_number
    ]
    if transaction.amount >= policy.high_value_review_amount_cents:
        trigger(
            "high_value_review",
            0,
            False,
            f"Valor de {transaction.amount} centavos exige confirmação humana independente.",
        )

    destination_type_rules = {
        policy.cpf_digits: (
            policy.destination_cpf_amount_cents,
            policy.destination_cpf_points,
            "CPF",
        ),
        policy.cnpj_digits: (
            policy.destination_cnpj_amount_cents,
            policy.destination_cnpj_points,
            "CNPJ",
        ),
    }
    destination_type_rule = destination_type_rules.get(
        len(transaction.destination_document_number)
    )
    if destination_type_rule is None:
        skip(
            "destination_type_amount",
            "Tipo de documento do destinatario desconhecido; esperado CPF (11 digitos) ou CNPJ (14 digitos).",
        )
    else:
        destination_threshold, destination_points, destination_type = destination_type_rule
        if transaction.amount >= destination_threshold:
            trigger(
                "destination_type_amount",
                destination_points,
                False,
                f"Valor de {transaction.amount} centavos para destinatario {destination_type} "
                f"atinge o limite de {destination_threshold} centavos.",
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

    payer_type_rules = {
        policy.cpf_digits: (
            "CPF",
            policy.burst_cpf_two_factor_count,
            policy.burst_cpf_reject_count,
            policy.rolling_24h_cpf_two_factor_cents,
            policy.rolling_24h_cpf_reject_cents,
        ),
        policy.cnpj_digits: (
            "CNPJ",
            policy.burst_cnpj_two_factor_count,
            policy.burst_cnpj_reject_count,
            policy.rolling_24h_cnpj_two_factor_cents,
            policy.rolling_24h_cnpj_reject_cents,
        ),
    }
    payer_type_rule = payer_type_rules.get(len(transaction.source_document_number))
    if payer_type_rule is None:
        skip(
            "burst",
            "Tipo de documento do pagador desconhecido; esperado CPF (11 digitos) ou CNPJ (14 digitos).",
        )
    else:
        payer_type, burst_two_factor_count, burst_reject_count, _, _ = payer_type_rule
        recent_attempts_10m = [
            item
            for item in payer_attempts
            if now - timedelta(minutes=policy.burst_window_minutes)
            < item.transaction_date
        ]
        burst_count = len(recent_attempts_10m) + 1
        if burst_count >= burst_reject_count:
            trigger(
                "burst",
                0,
                True,
                f"{burst_count} tentativas do pagador {payer_type} em "
                f"{policy.burst_window_minutes} minutos (bloqueio a partir de {burst_reject_count}).",
            )
        elif burst_count >= burst_two_factor_count:
            trigger(
                "burst",
                policy.burst_points,
                False,
                f"{burst_count} tentativas do pagador {payer_type} em "
                f"{policy.burst_window_minutes} minutos (2FA a partir de {burst_two_factor_count}).",
            )

    rolling_window = timedelta(hours=policy.rolling_24h_window_hours)
    rolling_movements = [
        item
        for item in payer_attempts
        if effective(item) and in_window(item, rolling_window)
    ]
    prior_rolling_total = sum(item.amount for item in rolling_movements)
    rolling_total = prior_rolling_total + transaction.amount
    if payer_type_rule is None:
        skip(
            "rolling_24h_total",
            "Tipo de documento do pagador desconhecido; esperado CPF (11 digitos) ou CNPJ (14 digitos).",
        )
    else:
        _, _, _, rolling_two_factor_cents, rolling_reject_cents = payer_type_rule
    if payer_type_rule is not None and rolling_total > rolling_reject_cents:
        if (
            transaction.amount >= policy.high_value_review_amount_cents
            and prior_rolling_total <= rolling_reject_cents
        ):
            trigger(
                "rolling_24h_total",
                policy.rolling_24h_points,
                False,
                f"Movimentacao efetiva observada de {rolling_total} centavos em 24 horas "
                f"para pagador {payer_type}; o Pix de alto valor exige confirmacao humana "
                "e nao bloqueia automaticamente.",
            )
        else:
            trigger(
                "rolling_24h_total",
                0,
                True,
                f"Movimentacao efetiva observada de {rolling_total} centavos em 24 horas "
                f"para pagador {payer_type} (bloqueio acima de {rolling_reject_cents}).",
            )
    elif payer_type_rule is not None and rolling_total > rolling_two_factor_cents:
        trigger(
            "rolling_24h_total",
            policy.rolling_24h_points,
            False,
            f"Movimentacao efetiva observada de {rolling_total} centavos em 24 horas "
            f"para pagador {payer_type} (2FA acima de {rolling_two_factor_cents}).",
        )

    median_window = timedelta(days=policy.amount_median_window_days)
    median_history = sorted(
        (
            item
            for item in payer_attempts
            if effective(item) and in_window(item, median_window)
        ),
        key=lambda item: (item.transaction_date, item.id),
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
        median_absolute_deviation = median(
            abs(amount - reference_median) for amount in median_samples
        )
        scale = max(
            policy.amount_median_mad_scale * median_absolute_deviation,
            policy.amount_median_scale_floor_cents,
        )
        robust_z_score = (transaction.amount - reference_median) / scale
        if (
            robust_z_score >= policy.amount_median_robust_z_threshold
            and transaction.amount >= policy.amount_median_min_cents
        ):
            trigger(
                "amount_vs_median",
                policy.amount_median_points,
                False,
                f"Valor de {transaction.amount} centavos tem desvio robusto "
                f"{robust_z_score:.2f} (mediana {reference_median:g}, MAD {median_absolute_deviation:g}).",
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
                False,
                f"Deslocamento de {distance:.1f} km a {speed:.1f} km/h em menos de 24 horas.",
            )
    else:
        skip(
            "impossible_travel",
            "Geolocalizacao ausente no Pix atual.",
        )

    if self_payment:
        skip("young_destination", "Pagador e destinatario sao o mesmo documento.")
    elif transaction.amount >= policy.young_destination_min_cents:
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

    if self_payment:
        skip("new_payee", "Pagador e destinatario sao o mesmo documento.")
    else:
        prior_effective_payee = any(
            effective(item)
            and item.source_document_number == transaction.source_document_number
            and item.destination_document_number == transaction.destination_document_number
            for item in prior
        )
        if (
            transaction.amount >= policy.new_payee_min_cents
            and not prior_effective_payee
        ):
            trigger(
                "new_payee",
                policy.new_payee_points,
                False,
                f"Nao ha movimentacao efetiva anterior para o favorecido "
                f"{transaction.destination_document_number}; valor de {transaction.amount} centavos.",
            )

    if self_payment:
        skip("mule_fan_in", "Pagador e destinatario sao o mesmo documento.")
    elif len(transaction.destination_document_number) == policy.cpf_digits:
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

    elif len(transaction.destination_document_number) != policy.cpf_digits:
        skip(
            "mule_fan_in",
            "Regra aplicavel somente a destinatarios CPF.",
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
            "high_value_review_amount": policy.high_value_review_amount_cents,
        },
        "rules_triggered": triggered,
    }
    if (
        transaction.amount >= policy.high_value_review_amount_cents
        and status == "two_factor_required"
    ):
        metadata["authentication"] = {
            "type": "human_in_the_loop",
            "reason": "high_value_transaction",
            "required": True,
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
