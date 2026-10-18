from dataclasses import dataclass, field


@dataclass(frozen=True)
class AntifraudPolicy:
    engine_version: str = "5"
    timezone: str = "America/Sao_Paulo"
    earth_radius_km: float = 6371.0

    history_window_days: int = 90
    history_max_rows: int = 500
    sample_max_rows: int = 50
    robust_mad_factor: float = 1.4826
    robust_scale_floor_ratio: float = 0.25
    warn_z: float = 3.0
    critical_z: float = 6.0
    amount_min_samples: int = 5

    night_start_hour: int = 20
    night_end_hour: int = 6
    night_amount_cents: int = 100_000
    night_points: int = 2

    median_min_amount_cents: int = 50_000
    median_points: int = 2

    high_value_floor_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 500_000, "cnpj": 2_000_000}
    )
    high_value_fixed_ceiling_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 3_000_000, "cnpj": 10_000_000}
    )

    destination_type_floor_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 100_000, "cnpj": 500_000}
    )
    destination_type_fixed_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 1_000_000, "cnpj": 5_000_000}
    )
    destination_type_points: dict[str, int] = field(
        default_factory=lambda: {"cpf": 3, "cnpj": 2}
    )

    burst_window_minutes: int = 10
    burst_min_history: int = 10
    burst_warn_factor: int = 2
    burst_block_factor: int = 4
    burst_warn_floor: dict[str, int] = field(
        default_factory=lambda: {"cpf": 4, "cnpj": 10}
    )
    burst_block_floor: dict[str, int] = field(
        default_factory=lambda: {"cpf": 10, "cnpj": 40}
    )
    burst_fixed: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {"cpf": (5, 10), "cnpj": (20, 40)}
    )
    burst_points: int = 3

    daily_window_hours: int = 24
    daily_min_active_days: int = 5
    daily_warn_floor_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 200_000, "cnpj": 1_000_000}
    )
    daily_critical_floor_cents: dict[str, int] = field(
        default_factory=lambda: {"cpf": 1_000_000, "cnpj": 5_000_000}
    )
    daily_fixed_cents: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {
            "cpf": (1_000_000, 3_000_000),
            "cnpj": (5_000_000, 15_000_000),
        }
    )
    daily_points: int = 2

    new_device_min_history: int = 3
    new_device_min_amount_cents: int = 20_000
    new_device_points: int = 2

    young_payer_max_age_days: int = 30
    young_payer_min_amount_cents: int = 100_000
    young_payer_points: int = 1

    impossible_travel_window_hours: int = 24
    impossible_travel_min_distance_km: float = 100.0
    impossible_travel_min_speed_kmh: float = 900.0
    impossible_travel_min_elapsed_seconds: int = 60
    impossible_travel_points: int = 3

    young_destination_min_amount_cents: int = 50_000
    young_destination_first_age_days: int = 7
    young_destination_second_age_days: int = 30
    young_destination_first_points: int = 3
    young_destination_second_points: int = 2

    new_payee_min_amount_cents: int = 100_000
    new_payee_points: int = 1

    payee_burst_window_minutes: int = 30
    payee_burst_min_total_cents: int = 100_000
    payee_burst_warn_count: dict[str, int] = field(
        default_factory=lambda: {"cpf": 3, "cnpj": 5}
    )
    payee_burst_strong_count: dict[str, int] = field(
        default_factory=lambda: {"cpf": 5, "cnpj": 10}
    )
    payee_burst_warn_points: int = 2
    payee_burst_strong_points: int = 3

    mule_fan_in_window_hours: int = 24
    mule_fan_in_block_count: int = 10
    mule_fan_in_warn_count: int = 5
    mule_fan_in_points: int = 3

    shared_device_window_hours: int = 24
    shared_device_min_payers: int = 3
    shared_device_points: int = 3

    two_factor_score: int = 3
    reject_score: int = 8
    cpf_digits: int = 11
    cnpj_digits: int = 14


POLICY = AntifraudPolicy()
