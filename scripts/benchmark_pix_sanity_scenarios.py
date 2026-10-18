import argparse
import csv
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any
from uuid import uuid4

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results" / "pix_sanity_timings.csv"
LOCAL_TZ = timezone(timedelta(hours=-3))
BASE_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=LOCAL_TZ)
CSV_FIELDS = [
    "scenario",
    "iteration",
    "call_index",
    "role",
    "method",
    "path",
    "transaction_id",
    "http_status",
    "decision_status",
    "score",
    "engine_version",
    "error_code",
    "elapsed_ms",
    "expected_http_status",
    "expected_decision_status",
    "passed",
    "failure",
]


def new_document(digits: int = 11) -> str:
    return f"{uuid4().int % (10**digits):0{digits}d}"


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def transaction_payload(
    *,
    transaction_id: str | None = None,
    amount: int = 1_000,
    transaction_date: datetime = BASE_TIME,
    payer: str | None = None,
    payee: str | None = None,
    source_opening_days: int = 365,
    destination_opening_days: int = 365,
    device_id: str | None = None,
    geolocation: dict[str, float] | None = None,
) -> dict[str, Any]:
    source = {
        "device_id": device_id or f"benchmark-{uuid4()}",
        "channel": "app",
        "ip": "198.51.100.23",
    }
    if geolocation is not None:
        source["geolocation"] = geolocation

    return {
        "id": transaction_id or f"benchmark-{uuid4()}",
        "amount": amount,
        "transaction_date": timestamp(transaction_date),
        "source_account": {
            "branch": "0001",
            "account_number": "88213",
            "opening_date": timestamp(
                transaction_date - timedelta(days=source_opening_days)
            ),
            "owner": {"document_number": payer or new_document()},
        },
        "destination_account": {
            "participant": "60701190",
            "branch": "3675",
            "account_number": "10442",
            "opening_date": timestamp(
                transaction_date - timedelta(days=destination_opening_days)
            ),
            "owner": {"document_number": payee or new_document()},
        },
        "source": source,
    }


@dataclass
class TimedResponse:
    status_code: int
    body: dict[str, Any]
    elapsed_ms: float


class TimedPixClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        writer: csv.DictWriter,
        csv_file: Any,
        scenario: str,
        iteration: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.writer = writer
        self.csv_file = csv_file
        self.scenario = scenario
        self.iteration = iteration
        self.call_index = 0
        self.session = requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        role: str,
        payload: dict[str, Any] | None = None,
        authorized: bool = True,
        expected_http_status: int,
        expected_decision_status: str | None = None,
        expected_score: int | None = None,
        expected_rules: list[str] | None = None,
        expected_authentication: str | None = None,
        expected_error_code: str | None = None,
        expected_key: str | None = None,
    ) -> TimedResponse:
        headers = {"INTERNAL-TOKEN": self.token} if authorized else {}
        url = f"{self.base_url}{path}"
        started = perf_counter_ns()
        response = self.session.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000

        try:
            body = response.json()
        except ValueError:
            body = {}

        self.call_index += 1
        metadata = body.get("metadata", {}) if isinstance(body, dict) else {}
        decision_status = body.get("status") if isinstance(body, dict) else None
        score = metadata.get("score")
        rules = [
            item.get("rule")
            for item in metadata.get("rules_triggered", [])
            if isinstance(item, dict)
        ]
        authentication = metadata.get("authentication", {})
        actual_authentication = (
            authentication.get("type")
            if isinstance(authentication, dict)
            else None
        )
        error_code = body.get("code") if isinstance(body, dict) else None
        checks = [
            (
                response.status_code == expected_http_status,
                f"HTTP expected {expected_http_status}, got {response.status_code}",
            )
        ]
        if expected_decision_status is not None:
            checks.append(
                (
                    decision_status == expected_decision_status,
                    f"decision expected {expected_decision_status}, got {decision_status}",
                )
            )
        if expected_score is not None:
            checks.append(
                (score == expected_score, f"score expected {expected_score}, got {score}")
            )
        if expected_rules is not None:
            checks.append(
                (rules == expected_rules, f"rules expected {expected_rules}, got {rules}")
            )
        if expected_authentication is not None:
            checks.append(
                (
                    actual_authentication == expected_authentication,
                    f"authentication expected {expected_authentication}, got {actual_authentication}",
                )
            )
        if expected_error_code is not None:
            checks.append(
                (
                    error_code == expected_error_code,
                    f"error code expected {expected_error_code}, got {error_code}",
                )
            )
        if expected_key is not None:
            checks.append(
                (
                    body.get("key") == expected_key,
                    f"analysis key expected {expected_key}, got {body.get('key')}",
                )
            )

        failures = [message for passed, message in checks if not passed]
        self.writer.writerow(
            {
                "scenario": self.scenario,
                "iteration": self.iteration,
                "call_index": self.call_index,
                "role": role,
                "method": method,
                "path": path,
                "transaction_id": (payload or {}).get("id", ""),
                "http_status": response.status_code,
                "decision_status": decision_status or "",
                "score": "" if score is None else score,
                "engine_version": metadata.get("engine_version", ""),
                "error_code": error_code or "",
                "elapsed_ms": f"{elapsed_ms:.3f}",
                "expected_http_status": expected_http_status,
                "expected_decision_status": expected_decision_status or "",
                "passed": not failures,
                "failure": "; ".join(failures),
            }
        )
        self.csv_file.flush()
        return TimedResponse(response.status_code, body, elapsed_ms)

    def post(
        self,
        payload: dict[str, Any],
        *,
        role: str = "target",
        authorized: bool = True,
        expected_http_status: int = 201,
        expected_decision_status: str | None = None,
        expected_score: int | None = None,
        expected_rules: list[str] | None = None,
        expected_authentication: str | None = None,
        expected_error_code: str | None = None,
        expected_key: str | None = None,
    ) -> TimedResponse:
        return self.request(
            "POST",
            "/pix/transaction",
            role=role,
            payload=payload,
            authorized=authorized,
            expected_http_status=expected_http_status,
            expected_decision_status=expected_decision_status,
            expected_score=expected_score,
            expected_rules=expected_rules,
            expected_authentication=expected_authentication,
            expected_error_code=expected_error_code,
            expected_key=expected_key,
        )

    def get(
        self,
        path: str,
        *,
        expected_http_status: int,
        expected_error_code: str | None = None,
    ) -> TimedResponse:
        return self.request(
            "GET",
            path,
            role="target",
            expected_http_status=expected_http_status,
            expected_error_code=expected_error_code,
        )


def run_approved_known_payee(client: TimedPixClient) -> None:
    payer, payee = new_document(), new_document()
    client.post(
        transaction_payload(
            amount=15_000,
            transaction_date=BASE_TIME - timedelta(hours=1),
            payer=payer,
            payee=payee,
        ),
        role="setup_history",
        expected_decision_status="approved",
    )
    client.post(
        transaction_payload(
            amount=15_000,
            payer=payer,
            payee=payee,
        ),
        expected_decision_status="approved",
        expected_score=0,
        expected_rules=[],
    )


def run_challenge_example(client: TimedPixClient) -> None:
    at = BASE_TIME.replace(hour=22, minute=15)
    client.post(
        transaction_payload(
            amount=150_000,
            transaction_date=at,
            destination_opening_days=7,
        ),
        expected_decision_status="two_factor_required",
        expected_score=5,
        expected_rules=["night_over_limit", "young_destination", "new_payee"],
    )


def run_high_value(client: TimedPixClient) -> None:
    client.post(
        transaction_payload(amount=6_000_000),
        expected_decision_status="two_factor_required",
        expected_authentication="human_in_the_loop",
    )


def run_burst(client: TimedPixClient, count: int) -> None:
    payer, payee, device = new_document(), new_document(), f"burst-{uuid4()}"
    for index in range(count):
        expected = (
            "rejected"
            if index + 1 >= 10
            else "two_factor_required"
            if index + 1 >= 5
            else "approved"
        )
        client.post(
            transaction_payload(
                transaction_date=BASE_TIME + timedelta(minutes=index),
                payer=payer,
                payee=payee,
                device_id=device,
            ),
            role="target",
            expected_decision_status=expected,
        )


def run_night_known_payee(client: TimedPixClient, known_payee: bool) -> None:
    payer, payee = new_document(), new_document()
    if known_payee:
        client.post(
            transaction_payload(
                transaction_date=BASE_TIME.replace(hour=20),
                payer=payer,
                payee=payee,
            ),
            role="setup_history",
            expected_decision_status="approved",
        )
    client.post(
        transaction_payload(
            amount=120_000,
            transaction_date=BASE_TIME.replace(hour=21),
            payer=payer,
            payee=payee,
        ),
        expected_decision_status="approved" if known_payee else "two_factor_required",
        expected_score=2 if known_payee else 3,
        expected_rules=(
            ["night_over_limit"]
            if known_payee
            else ["night_over_limit", "new_payee"]
        ),
    )


def run_mule_fan_in(client: TimedPixClient, payee_digits: int) -> None:
    payee = new_document(payee_digits)
    for index in range(6):
        client.post(
            transaction_payload(
                transaction_date=BASE_TIME + timedelta(minutes=index),
                payer=new_document(),
                payee=payee,
                device_id=f"fan-in-{uuid4()}",
            ),
            role="target",
            expected_decision_status=(
                "two_factor_required"
                if payee_digits == 11 and index >= 4
                else "approved"
            ),
        )


def run_self_payment(client: TimedPixClient) -> None:
    document = new_document()
    client.post(
        transaction_payload(
            amount=150_000,
            payer=document,
            payee=document,
            destination_opening_days=1,
        ),
        expected_decision_status="approved",
        expected_score=0,
        expected_rules=[],
    )


def run_impossible_travel(client: TimedPixClient) -> None:
    payer = new_document()
    client.post(
        transaction_payload(
            transaction_date=BASE_TIME,
            payer=payer,
            geolocation={"latitude": 0.0, "longitude": 0.0},
        ),
        role="setup_history",
        expected_decision_status="approved",
    )
    client.post(
        transaction_payload(
            transaction_date=BASE_TIME + timedelta(minutes=30),
            payer=payer,
            geolocation={"latitude": 0.0, "longitude": 5.0},
        ),
        expected_decision_status="two_factor_required",
        expected_rules=["impossible_travel"],
    )


def run_replay(client: TimedPixClient) -> None:
    payload = transaction_payload(amount=150_000)
    first = client.post(payload, expected_decision_status="approved")
    analysis_key = first.body.get("key")
    replay = {**payload, "amount": 5_000_001}
    client.post(
        replay,
        expected_http_status=200,
        expected_decision_status="approved",
        expected_key=analysis_key,
    )


def run_missing_get(client: TimedPixClient) -> None:
    client.get(
        f"/pix/transaction/missing-{uuid4()}",
        expected_http_status=404,
        expected_error_code="QIT001008",
    )


def run_missing_token(client: TimedPixClient) -> None:
    client.post(
        transaction_payload(),
        authorized=False,
        expected_http_status=403,
        expected_error_code="QIT000002",
    )


def run_missing_field(client: TimedPixClient) -> None:
    payload = transaction_payload()
    del payload["source"]["device_id"]
    client.post(
        payload,
        expected_http_status=400,
        expected_error_code="QIT000001",
    )


def run_timestamp_without_timezone(client: TimedPixClient) -> None:
    payload = transaction_payload()
    payload["transaction_date"] = "2026-10-17T12:00:00"
    client.post(
        payload,
        expected_http_status=422,
        expected_error_code="QIT001009",
    )


SCENARIOS = [
    ("approved_known_payee", run_approved_known_payee),
    ("challenge_example", run_challenge_example),
    ("high_value_human_review", run_high_value),
    ("burst_cpf_tenth_rejected", lambda client: run_burst(client, 10)),
    ("burst_cpf_fifth_two_factor", lambda client: run_burst(client, 5)),
    ("night_known_payee_approved", lambda client: run_night_known_payee(client, True)),
    ("night_new_payee_two_factor", lambda client: run_night_known_payee(client, False)),
    ("mule_fan_in_cpf_two_factor", lambda client: run_mule_fan_in(client, 11)),
    ("mule_fan_in_cnpj_skipped", lambda client: run_mule_fan_in(client, 14)),
    ("self_payment_skips_destination_rules", run_self_payment),
    ("impossible_travel", run_impossible_travel),
    ("same_id_replay", run_replay),
    ("missing_transaction_404", run_missing_get),
    ("missing_internal_token_403", run_missing_token),
    ("missing_required_field_400", run_missing_field),
    ("timestamp_without_timezone_422", run_timestamp_without_timezone),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and time every PIX sanity-check scenario over HTTP."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PIX_API_URL", "http://localhost:3000"),
        help="API base URL (default: PIX_API_URL or http://localhost:3000)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("INTERNAL_TOKEN", "default_token"),
        help="INTERNAL-TOKEN value (default: INTERNAL_TOKEN or default_token)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Runs per scenario (default: 100)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    timings: list[float] = []
    total_calls = 0
    failures = 0

    try:
        health = requests.get(f"{args.base_url.rstrip('/')}/health_check", timeout=10)
    except requests.RequestException as error:
        print(f"API health check failed: {error}", file=sys.stderr)
        return 2
    if health.status_code != 204:
        print(
            f"API health check expected HTTP 204, got {health.status_code}",
            file=sys.stderr,
        )
        return 2

    with args.output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        csv_file.flush()

        for scenario_name, scenario in SCENARIOS:
            for iteration in range(1, args.iterations + 1):
                client = TimedPixClient(
                    base_url=args.base_url,
                    token=args.token,
                    writer=writer,
                    csv_file=csv_file,
                    scenario=scenario_name,
                    iteration=iteration,
                )
                scenario(client)
                client.session.close()

                total_calls += client.call_index

    with args.output.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            timings.append(float(row["elapsed_ms"]))
            failures += row["passed"].lower() != "true"

    mean_ms = statistics.mean(timings) if timings else 0.0
    median_ms = statistics.median(timings) if timings else 0.0
    percentile_95_ms = (
        sorted(timings)[max(0, int(len(timings) * 0.95) - 1)] if timings else 0.0
    )
    print(f"Scenarios: {len(SCENARIOS)} x {args.iterations} = {len(SCENARIOS) * args.iterations}")
    print(f"HTTP calls timed: {total_calls}")
    print(
        f"Latency (ms): mean={mean_ms:.3f}, median={median_ms:.3f}, "
        f"p95={percentile_95_ms:.3f}"
    )
    print(f"Sanity-check failures: {failures}")
    print(f"CSV: {args.output.resolve()}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
