"""Independently review an R2A-T04 local run and compact bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import duckdb

from src.r2a.r2a_t04_audit_validator import (
    recompute_path_metrics,
    validate_review_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_SCORE = (
    ROOT
    / "data/generated/r2a/r2a_t01/R2A-T01-20260718T103110891Z/score-release"
    / "pcavt-score-w120-v1-c7e04f11a2cd09aa/score_data.duckdb"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review R2A-T04 real-data audit.")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--review-bundle", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _close(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= 1e-12


def _market_path(source: dict[str, Any], run_root: Path) -> Path:
    basename = str(source["database_basename"])
    candidates: list[Path] = []
    if environment := os.environ.get("R2A_T04_MARKET_DB"):
        candidates.append(Path(environment))
    input_root = run_root.parents[2]
    candidates.extend(input_root.rglob(basename))
    unique = {path.resolve() for path in candidates if path.is_file()}
    if len(unique) != 1:
        raise RuntimeError(f"market_context_source_not_uniquely_bound:{len(unique)}")
    return unique.pop()


def _assert_identity(path: Path, expected: dict[str, Any], label: str) -> None:
    if (
        not path.is_file()
        or path.stat().st_size != int(expected["byte_size"])
        or _sha256(path) != expected["sha256"]
    ):
        raise RuntimeError(f"{label}_identity_mismatch")


def _response_checks(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    chains = (
        (
            "q_raw_subset",
            (
                "Q01_PCAVT_q10_k3",
                "D05_PCAVT_q15_k3",
                "Q02_PCAVT_q20_k3",
                "Q03_PCAVT_q25_k3",
            ),
            "raw_state",
        ),
        (
            "q_confirmed_subset",
            (
                "Q01_PCAVT_q10_k3",
                "D05_PCAVT_q15_k3",
                "Q02_PCAVT_q20_k3",
                "Q03_PCAVT_q25_k3",
            ),
            "confirmed_state",
        ),
        (
            "k_confirmed_subset",
            (
                "K03_PCAVT_q15_k7",
                "K02_PCAVT_q15_k5",
                "D05_PCAVT_q15_k3",
                "K01_PCAVT_q15_k2",
            ),
            "confirmed_state",
        ),
        (
            "dimension_raw_subset",
            (
                "D05_PCAVT_q15_k3",
                "D04_PCAV_q15_k3",
                "D03_PCA_q15_k3",
                "D02_PA_q15_k3",
                "D01_P_q15_k3",
            ),
            "raw_state",
        ),
        (
            "dimension_confirmed_subset",
            (
                "D05_PCAVT_q15_k3",
                "D04_PCAV_q15_k3",
                "D03_PCA_q15_k3",
                "D02_PA_q15_k3",
                "D01_P_q15_k3",
            ),
            "confirmed_state",
        ),
    )
    for check_id, names, field in chains:
        violations = 0
        strict = False
        for smaller, larger in zip(names, names[1:]):
            violations += int(
                connection.execute(
                    f"SELECT count(*) FROM response_daily s ANTI JOIN ("
                    f"SELECT security_id,trading_date FROM response_daily WHERE "
                    f"logical_request_name=? AND {field}=true) l "
                    "USING(security_id,trading_date) "
                    f"WHERE s.logical_request_name=? AND s.{field}=true",
                    [larger, smaller],
                ).fetchone()[0]
            )
            counts = connection.execute(
                "SELECT count(*) FILTER(WHERE logical_request_name=? AND "
                f"{field}=true),"
                f"count(*) FILTER(WHERE logical_request_name=? AND {field}=true) "
                "FROM response_daily",
                [smaller, larger],
            ).fetchone()
            strict = strict or counts[0] != counts[1]
        checks.append(
            {"check_id": check_id, "violations": violations, "strict": strict}
        )
    raw_mismatch = 0
    for candidate in ("K01_PCAVT_q15_k2", "K02_PCAVT_q15_k5", "K03_PCAVT_q15_k7"):
        raw_mismatch += int(
            connection.execute(
                "SELECT count(*) FROM response_daily a JOIN response_daily b "
                "USING(security_id,trading_date) WHERE "
                "a.logical_request_name='D05_PCAVT_q15_k3' AND "
                "b.logical_request_name=? AND a.raw_state IS DISTINCT FROM b.raw_state",
                [candidate],
            ).fetchone()[0]
        )
    checks.append({"check_id": "k_raw_equality", "violations": raw_mismatch})
    profiles = connection.execute(
        "SELECT logical_request_name,dimension_id,row_count,row_fingerprint,"
        "active_count,active_fingerprint FROM dimension_response_profiles"
    ).fetchall()
    by_key = {(row[0], row[1]): row[2:] for row in profiles}
    non_target_mismatch = 0
    for candidate, target in (
        ("M01_P25", "P"),
        ("M02_C25", "C"),
        ("M03_A25", "A"),
        ("M04_V25", "V"),
        ("M05_T25", "T"),
    ):
        for dimension in "PCAVT":
            if (
                dimension != target
                and by_key[(candidate, dimension)]
                != by_key[("D05_PCAVT_q15_k3", dimension)]
            ):
                non_target_mismatch += 1
    checks.append(
        {"check_id": "marginal_non_target_profiles", "violations": non_target_mismatch}
    )
    return checks


def _request_metric_mismatches(connection: duckdb.DuckDBPyConnection) -> list[str]:
    mismatches: list[str] = []
    for logical_name, metrics_json in connection.execute(
        "SELECT logical_request_name,metrics_json FROM request_metrics_records"
    ).fetchall():
        expected = json.loads(metrics_json)
        actual = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE joint_ready),"
            "count(*) FILTER(WHERE raw_state=true),"
            "count(*) FILTER(WHERE raw_state=false),"
            "count(*) FILTER(WHERE raw_state IS NULL),"
            "count(*) FILTER(WHERE confirmed_state=true),"
            "count(*) FILTER(WHERE confirmation_event) FROM response_daily "
            "WHERE logical_request_name=?",
            [logical_name],
        ).fetchone()
        fields = (
            "spine_observation_count",
            "joint_ready_count",
            "raw_true_count",
            "raw_false_count",
            "raw_null_count",
            "confirmed_true_count",
            "confirmation_event_count",
        )
        for field, value in zip(fields, actual):
            if int(expected[field]) != int(value):
                mismatches.append(f"{logical_name}:{field}")
        interval = connection.execute(
            "SELECT count(*),count(DISTINCT security_id),"
            "count(*) FILTER(WHERE right_censored),median(confirmed_observation_count) "
            "FROM interval_path_metrics WHERE logical_request_name=?",
            [logical_name],
        ).fetchone()
        for field, value in zip(
            (
                "confirmed_interval_count",
                "security_with_interval_count",
                "right_censored_interval_count",
            ),
            interval[:3],
        ):
            if int(expected[field]) != int(value):
                mismatches.append(f"{logical_name}:{field}")
        if not _close(expected["duration_quantiles"]["median"], interval[3]):
            mismatches.append(f"{logical_name}:duration_median")
    return mismatches


def _year_metric_mismatches(connection: duckdb.DuckDBPyConnection) -> list[str]:
    mismatches: list[str] = []
    for logical_name, year, metrics_json in connection.execute(
        "SELECT logical_request_name,year,metrics_json FROM year_metrics_records"
    ).fetchall():
        expected = json.loads(metrics_json)
        daily = connection.execute(
            "SELECT count(*) FILTER(WHERE confirmation_event) FROM response_daily "
            "WHERE logical_request_name=? AND year(trading_date)=?",
            [logical_name, year],
        ).fetchone()[0]
        intervals = connection.execute(
            "SELECT count(*),count(DISTINCT security_id) FROM interval_path_metrics "
            "WHERE logical_request_name=? AND year(confirmation_date)=?",
            [logical_name, year],
        ).fetchone()
        if int(expected["confirmation_events"]) != int(daily):
            mismatches.append(f"{logical_name}:{year}:confirmation_events")
        if int(expected["interval_count"]) != int(intervals[0]):
            mismatches.append(f"{logical_name}:{year}:interval_count")
        if int(expected["security_breadth"]) != int(intervals[1]):
            mismatches.append(f"{logical_name}:{year}:security_breadth")
    return mismatches


def main() -> int:
    args = parse_args()
    bundle = validate_review_bundle(args.review_bundle)
    summary = json.loads(
        (args.review_bundle / "run_summary.json").read_text(encoding="utf-8")
    )
    source = json.loads(
        (args.run_root / "source_manifest.json").read_text(encoding="utf-8")
    )
    _assert_identity(ACCEPTED_SCORE, summary["score_source"], "score")
    _assert_identity(
        _market_path(source, args.run_root), summary["market_source"], "market"
    )
    local_panel = json.loads(
        (args.run_root / "request_panel.json").read_text(encoding="utf-8")
    )
    compact_panel = json.loads(
        (args.review_bundle / "request_panel.json").read_text(encoding="utf-8")
    )
    if local_panel != compact_panel or len(local_panel) != 16:
        raise RuntimeError("request_panel_identity_mismatch")
    mismatches: list[dict[str, object]] = []
    audit_path = args.run_root / "audit_metrics.duckdb"
    with duckdb.connect(str(audit_path), read_only=True) as connection:
        validators = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE validator_status='passed') "
            "FROM request_metrics_records"
        ).fetchone()
        request_mismatches = _request_metric_mismatches(connection)
        year_mismatches = _year_metric_mismatches(connection)
        response_checks = _response_checks(connection)
        termination_mismatches = connection.execute(
            "SELECT count(*) FROM (SELECT logical_request_name,"
            "termination_reason,count(*) n "
            "FROM interval_path_metrics GROUP BY 1,2) a FULL JOIN "
            "termination_metrics_records b "
            "USING(logical_request_name,termination_reason) "
            "WHERE a.n IS DISTINCT FROM b.count"
        ).fetchone()[0]
        samples = (
            connection.execute(
                "SELECT * FROM interval_path_metrics ORDER BY "
                "sha256(request_hash||':'||security_id||':'||"
                "confirmation_date::VARCHAR) LIMIT 100"
            )
            .fetch_arrow_table()
            .to_pylist()
        )
        for sample in samples:
            observations = (
                connection.execute(
                    "SELECT adj_close,adj_high,adj_low,trading_date "
                    "FROM market_features "
                    "WHERE security_id=? ORDER BY observation_sequence",
                    [sample["security_id"]],
                )
                .fetch_arrow_table()
                .to_pylist()
            )
            anchor = next(
                index
                for index, row in enumerate(observations)
                if row["trading_date"] == sample["confirmation_date"]
            )
            for horizon in (5, 10, 20):
                actual = recompute_path_metrics(
                    observations, anchor_index=anchor, horizon=horizon
                )
                for expected_field, actual_field in (
                    (f"close_return_{horizon}", "close_return"),
                    (f"mfe{horizon}", "mfe"),
                    (f"mae{horizon}", "mae"),
                    (f"time_to_peak_{horizon}", "time_to_peak"),
                    (f"time_to_trough_{horizon}", "time_to_trough"),
                ):
                    if expected_field in sample and not _close(
                        sample[expected_field], actual[actual_field]
                    ):
                        mismatches.append(
                            {
                                "security_id": sample["security_id"],
                                "confirmation_date": str(sample["confirmation_date"]),
                                "field": expected_field,
                                "expected": sample[expected_field],
                                "actual": actual[actual_field],
                            }
                        )
    registry = list(
        csv.DictReader(
            (args.review_bundle / "chart_sample_registry.csv").open(encoding="utf-8")
        )
    )
    status = (
        "passed"
        if validators == (16, 16)
        and not request_mismatches
        and not year_mismatches
        and not termination_mismatches
        and len(samples) == 100
        and len(registry) == 48
        and not mismatches
        and all(
            check["violations"] == 0 and check.get("strict", True)
            for check in response_checks
        )
        else "failed"
    )
    receipt = {
        "status": status,
        "score_identity": "passed",
        "market_identity": "passed",
        "panel_count": len(local_panel),
        "request_validator_passed_count": validators[1],
        "request_metric_mismatches": request_mismatches,
        "year_metric_mismatches": year_mismatches,
        "response_checks": response_checks,
        "termination_mismatch_count": termination_mismatches,
        "path_metric_sample_count": len(samples),
        "path_metric_mismatch_count": len(mismatches),
        "chart_registry_count": len(registry),
        "review_bundle": bundle,
        "mismatch_fingerprint": hashlib.sha256(
            json.dumps(mismatches, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }
    output = args.run_root / "independent_review_receipt.json"
    output.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
