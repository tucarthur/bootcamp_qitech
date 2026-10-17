from dataclasses import dataclass


@dataclass(frozen=True)
class AntifraudPolicy:
    engine_version: str = "4"
    timezone: str = "America/Sao_Paulo"
    earth_radius_km: float = 6371.0

    high_value_review_amount_cents: int = 5_000_000
    destination_cpf_amount_cents: int = 1_000_000
    destination_cnpj_amount_cents: int = 5_000_000
    destination_cpf_points: int = 3
    destination_cnpj_points: int = 2

    night_start_hour: int = 20
    night_end_hour: int = 6
    night_amount_cents: int = 100_000
    night_points: int = 2

    burst_window_minutes: int = 10
    burst_cpf_reject_count: int = 10
    burst_cpf_two_factor_count: int = 5
    burst_cnpj_reject_count: int = 40
    burst_cnpj_two_factor_count: int = 20
    burst_points: int = 3

    rolling_24h_window_hours: int = 24
    rolling_24h_cpf_reject_cents: int = 3_000_000
    rolling_24h_cpf_two_factor_cents: int = 1_000_000
    rolling_24h_cnpj_reject_cents: int = 15_000_000
    rolling_24h_cnpj_two_factor_cents: int = 5_000_000
    rolling_24h_points: int = 2

    amount_median_window_days: int = 90
    amount_median_max_samples: int = 50
    amount_median_min_samples: int = 5
    amount_median_min_cents: int = 50_000
    amount_median_robust_z_threshold: float = 3.0
    amount_median_mad_scale: float = 1.4826
    amount_median_scale_floor_cents: int = 1_000
    amount_median_points: int = 2

    new_device_window_days: int = 90
    new_device_min_attempts: int = 3
    new_device_min_cents: int = 20_000
    new_device_points: int = 2

    young_payer_max_age_days: int = 30
    young_payer_min_cents: int = 100_000
    young_payer_points: int = 1

    impossible_travel_window_hours: int = 24
    impossible_travel_min_distance_km: float = 100.0
    impossible_travel_min_speed_kmh: float = 900.0
    impossible_travel_min_elapsed_seconds: int = 60
    impossible_travel_points: int = 3

    young_destination_min_cents: int = 50_000
    young_destination_first_age_days: int = 7
    young_destination_second_age_days: int = 30
    young_destination_first_points: int = 3
    young_destination_second_points: int = 2

    new_payee_min_cents: int = 100_000
    new_payee_points: int = 1

    mule_fan_in_window_hours: int = 24
    mule_fan_in_reject_count: int = 10
    mule_fan_in_two_factor_count: int = 5
    mule_fan_in_points: int = 3

    shared_device_window_hours: int = 24
    shared_device_min_documents: int = 3
    shared_device_points: int = 3

    two_factor_score: int = 3
    reject_score: int = 8
    cpf_digits: int = 11
    cnpj_digits: int = 14


POLICY = AntifraudPolicy()
