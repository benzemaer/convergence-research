"""Independently review an R2A-T04 Score-only formal result package."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t04_audit_validator import (  # noqa: E402
    REQUIRED_COMPACT_FILES,
    validate_review_bundle,
)
from src.r2a.r2a_t04_request_panel import (  # noqa: E402
    build_request_panel,
    canonical_envelope,
    load_audit_config,
)

TASK_ID = "R2A-T04"
SCOPE_ID = "r2a_t04_ca_q15_q25_k5_response_audit.v1"
AUTHORIZATION_ID = "R2A-T04-CA-Q-AUDIT-AUTH-20260720-R5"
AUTHORIZATION_REVISION = 5
PANEL_ID = "r2a_t04_ca_q15_q25_k5_panel.v1"
RUN_ID_PATTERN = re.compile(r"^R2A-T04-[0-9]{8}T[0-9]{9}Z$")
EXPECTED_SCORE_IDENTITY = {
    "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
    "sha256": "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3",
    "byte_size": 4_255_395_840,
}
REQUIRED_ROOT_FILES = {
    "authorization.json",
    "score_source_identity.json",
    "request_panel.json",
    "run_manifest.json",
    "validation_receipt.json",
    "result_analysis.md",
    "audit_metrics.duckdb",
    "interval_inventory.parquet",
    "interval_security_distribution.csv",
    "logs/formal_run.jsonl",
}
REQUIRED_AUDIT_TABLES = {
    "request_metrics_records",
    "year_metrics_records",
    "termination_metrics_records",
    "response_daily",
    "response_checks",
    "interval_inventory",
    "score_dimension_structure",
    "score_component_structure",
}
FORBIDDEN_TABLE_PATTERNS = (
    "market",
    "price",
    "ohlc",
    "chart",
    "path_metric",
    "future",
    "return",
    "mfe",
    "mae",
)
FORBIDDEN_FIELD_PATTERNS = (
    "market_source",
    "market_features",
    "interval_path_metrics",
    "adj_close",
    "adj_high",
    "adj_low",
    "future_horizon",
    "close_return",
    "mfe",
    "mae",
    "time_to_peak",
    "time_to_trough",
    "chart",
    "png",
    "worksheet",
    "visual_review",
)
MISMATCH_COUNTERS = (
    "request_metric",
    "year_metric",
    "termination_metric",
    "response_check",
    "interval_inventory",
    "interval_parquet",
    "interval_security_distribution",
    "dimension_endpoint",
    "component_endpoint",
    "interval_sample",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently review an R2A-T04 Score-only formal package."
    )
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--review-bundle", type=Path, required=True)
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _normal(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_normal(item) for item in value]
    if isinstance(value, list):
        return [_normal(item) for item in value]
    if isinstance(value, set):
        return sorted(_normal(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _normal(item) for key, item in sorted(value.items())}
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        _normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping | list | tuple | set) or isinstance(
        right, Mapping | list | tuple | set
    ):
        return _normal(left) == _normal(right)
    if left is None or right is None:
        return (
            left is right
            or left is None
            and str(right).strip().lower() in {"", "none", "null"}
            or right is None
            and str(left).strip().lower() in {"", "none", "null"}
        )
    if isinstance(left, bool) or isinstance(right, bool):
        mapping = {"true": True, "false": False, "1": True, "0": False}
        left_value = mapping.get(str(left).lower(), left)
        right_value = mapping.get(str(right).lower(), right)
        return left_value is right_value
    try:
        return abs(float(left) - float(right)) <= 1e-12
    except (TypeError, ValueError):
        return str(left) == str(right)


def _rows(connection: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


class Review:
    def __init__(self) -> None:
        self.mismatches: list[dict[str, Any]] = []
        self.counts = Counter()
        self.statuses = {
            "score_identity_status": "failed",
            "formal_root_inventory_status": "failed",
            "compact_bundle_status": "failed",
        }

    def fail(
        self,
        category: str,
        check_id: str,
        *,
        expected: Any = None,
        actual: Any = None,
        key: Any = None,
    ) -> None:
        self.counts[category] += 1
        self.mismatches.append(
            {
                "category": category,
                "check_id": check_id,
                "key": _normal(key),
                "expected": _normal(expected),
                "actual": _normal(actual),
            }
        )

    def equal(
        self,
        category: str,
        check_id: str,
        actual: Any,
        expected: Any,
        *,
        key: Any = None,
    ) -> None:
        if not _same(actual, expected):
            self.fail(category, check_id, expected=expected, actual=actual, key=key)


def _identity_subset(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in EXPECTED_SCORE_IDENTITY}


def _check_score_identity(
    review: Review,
    score_db: Path,
    run_root: Path,
    bundle: Path,
    summary: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    release_id = None
    if score_db.is_file():
        with duckdb.connect(str(score_db), read_only=True) as score:
            candidates = {
                str(row[0])
                for row in score.execute(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema='main' AND column_name='score_release_id'"
                ).fetchall()
            }
            preferred = next(
                (
                    name
                    for name in (
                        "securities",
                        "dimension_definitions",
                        "daily_dimension_scores",
                    )
                    if name in candidates
                ),
                None,
            )
            if preferred is not None:
                values = score.execute(
                    f"SELECT DISTINCT score_release_id FROM {preferred} LIMIT 2"
                ).fetchall()
                if len(values) == 1:
                    release_id = values[0][0]
    actual = {
        "score_release_id": release_id,
        "sha256": _sha256(score_db) if score_db.is_file() else None,
        "byte_size": score_db.stat().st_size if score_db.is_file() else None,
    }
    review.equal("identity", "score_file_identity", actual, dict(expected))
    for label, value in (
        ("run_root", _json(run_root / "score_source_identity.json")),
        ("compact", _json(bundle / "score_source_identity.json")),
        ("summary", summary.get("score_source", {})),
    ):
        review.equal(
            "identity",
            f"score_identity_{label}",
            _identity_subset(value),
            dict(expected),
        )
    if review.counts["identity"] == 0:
        review.statuses["score_identity_status"] = "passed"


def _check_root_inventory(review: Review, run_root: Path) -> None:
    actual_files = {
        path.relative_to(run_root).as_posix()
        for path in run_root.rglob("*")
        if path.is_file()
    }
    missing = sorted(REQUIRED_ROOT_FILES - actual_files)
    if missing:
        review.fail("inventory", "required_root_files", expected=[], actual=missing)
    request_files = sorted((run_root / "requests").glob("*.json"))
    review.equal("inventory", "request_json_count", len(request_files), 2)
    residual = (
        sorted(
            path.relative_to(run_root).as_posix()
            for path in (run_root / "request-results").rglob("*")
            if path.is_file()
        )
        if (run_root / "request-results").is_dir()
        else []
    )
    if residual:
        review.fail(
            "inventory", "residual_request_results", expected=[], actual=residual
        )
    forbidden: list[str] = []
    for relative in actual_files:
        lower = relative.lower()
        if (
            relative == "source_manifest.json"
            or relative == "DONE"
            or lower.endswith(".png")
            or lower.startswith("charts/")
            or "worksheet" in lower
            or ("market" in lower and lower.endswith((".duckdb", ".db")))
        ):
            forbidden.append(relative)
    if forbidden:
        review.fail(
            "inventory", "forbidden_root_files", expected=[], actual=sorted(forbidden)
        )
    if review.counts["inventory"] == 0:
        review.statuses["formal_root_inventory_status"] = "passed"


def _check_run_identity(
    review: Review,
    run_root: Path,
    bundle: Path,
    summary: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    authorization = _json(run_root / "authorization.json")
    manifest = _json(run_root / "run_manifest.json")
    expected_auth = {
        "scope_id": SCOPE_ID,
        "formal_authorization_id": AUTHORIZATION_ID,
        "authorization_revision": AUTHORIZATION_REVISION,
        "formal_run_consumed": True,
        "full_universe_request_concurrency": 1,
        "duckdb_thread_count": 4,
    }
    for field, expected in expected_auth.items():
        review.equal("run_identity", field, authorization.get(field), expected)
    expected_manifest = {
        "scope_id": SCOPE_ID,
        "formal_authorization_id": AUTHORIZATION_ID,
        "authorization_revision": AUTHORIZATION_REVISION,
        "formal_run_consumed": True,
        "request_count": 2,
        "request_execution": "strictly_serial",
        "duckdb_thread_count": 4,
    }
    for field, expected in expected_manifest.items():
        review.equal("run_identity", field, manifest.get(field), expected)
    run_ids = (
        run_root.name,
        manifest.get("formal_run_id"),
        summary.get("formal_run_id"),
    )
    review.equal("run_identity", "formal_run_ids", len(set(run_ids)), 1)
    review.equal(
        "run_identity",
        "formal_run_id_pattern",
        bool(RUN_ID_PATTERN.fullmatch(run_root.name)),
        True,
    )
    for field, expected in (
        ("scope_id", SCOPE_ID),
        ("formal_authorization_id", AUTHORIZATION_ID),
        ("authorization_revision", AUTHORIZATION_REVISION),
        ("request_count", 2),
    ):
        review.equal("run_identity", f"summary_{field}", summary.get(field), expected)
    execution = summary.get("execution", {})
    for field, expected in (
        ("formal_run_consumed", True),
        ("full_universe_request_concurrency", 1),
        ("duckdb_thread_count", 4),
    ):
        review.equal(
            "run_identity", f"summary_execution_{field}", execution.get(field), expected
        )
    root_validation = _json(run_root / "validation_receipt.json")
    review.equal(
        "run_identity",
        "validation_receipt_vs_summary",
        root_validation,
        summary.get("validation", {}),
    )
    review.equal(
        "run_identity",
        "compact_validation_receipt",
        _json(bundle / "validation_receipt.json"),
        root_validation,
    )
    review.equal(
        "run_identity",
        "result_analysis_identity",
        (bundle / "result_analysis.md").read_bytes(),
        (run_root / "result_analysis.md").read_bytes(),
    )
    log_rows = [
        json.loads(line)
        for line in (run_root / "logs" / "formal_run.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    review.equal("run_identity", "formal_log_record_count", len(log_rows), 2)
    review.equal(
        "run_identity",
        "formal_log_validator_status",
        sum(row.get("validator_status") == "passed" for row in log_rows),
        2,
    )
    return authorization, manifest


def _check_panel(review: Review, run_root: Path, bundle: Path) -> list[dict[str, Any]]:
    local = _json(run_root / "request_panel.json")
    compact = _json(bundle / "request_panel.json")
    config = load_audit_config()
    built = list(build_request_panel(config))
    review.equal("panel", "run_root_vs_compact", local, compact)
    review.equal("panel", "run_root_vs_current_config", local, built)
    review.equal("panel", "panel_count", len(local), 2)
    review.equal("panel", "panel_id", config.get("panel_id"), PANEL_ID)
    for field in ("logical_request_name", "request_id", "request_hash"):
        values = [item.get(field) for item in local]
        review.equal("panel", f"unique_{field}", len(values), len(set(values)))
    expected_names = {str(item["logical_request_name"]) for item in local}
    actual_names = {path.stem for path in (run_root / "requests").glob("*.json")}
    review.equal("panel", "request_file_names", actual_names, expected_names)
    for item in local:
        name = str(item["logical_request_name"])
        path = run_root / "requests" / f"{name}.json"
        if path.is_file():
            review.equal(
                "panel",
                "request_envelope",
                _json(path),
                canonical_envelope(item),
                key=name,
            )
    return local


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _check_bundle(review: Review, bundle: Path) -> dict[str, Any]:
    result = validate_review_bundle(bundle)
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
    }
    expected = set(REQUIRED_COMPACT_FILES) | {"run_summary.json"}
    review.equal("compact", "exact_inventory", actual, expected)
    total = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
    if total > 60 * 1024 * 1024:
        review.fail("compact", "bundle_size", expected=60 * 1024 * 1024, actual=total)
    forbidden: set[str] = set()
    for path in bundle.iterdir():
        if path.suffix == ".json":
            keys = _walk_keys(_json(path))
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                keys = iter(csv.DictReader(handle).fieldnames or [])
        else:
            keys = ()
        for key in keys:
            lower = key.lower()
            if any(pattern in lower for pattern in FORBIDDEN_FIELD_PATTERNS):
                forbidden.add(key)
    if forbidden:
        review.counts["forbidden_field"] += len(forbidden)
        review.fail(
            "compact", "forbidden_fields", expected=[], actual=sorted(forbidden)
        )
    if review.counts["compact"] == 0:
        review.statuses["compact_bundle_status"] = "passed"
    return result


def _literal(value: str) -> Any:
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _indexed(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> dict[tuple[str, ...], Mapping[str, Any]]:
    return {tuple(str(row.get(key, "")) for key in keys): row for row in rows}


def _compare_fields(
    review: Review,
    category: str,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
    fields: Sequence[str],
    key: Any,
) -> None:
    if expected is None:
        review.fail(category, "missing_record", expected="record", actual=None, key=key)
        return
    for field in fields:
        review.equal(category, field, actual.get(field), expected.get(field), key=key)


def _request_metrics(
    review: Review, db: duckdb.DuckDBPyConnection, bundle: Path
) -> tuple[int, int]:
    csv_rows = _indexed(_csv(bundle / "request_metrics.csv"), ("logical_request_name",))
    records = _rows(
        db, "SELECT * FROM request_metrics_records ORDER BY logical_request_name"
    )
    validator_passed = sum(row["validator_status"] == "passed" for row in records)
    review.equal("request_metric", "validator_record_count", len(records), 2)
    review.equal("request_metric", "validator_passed_count", validator_passed, 2)
    fields = (
        "spine_observation_count",
        "joint_ready_count",
        "raw_true_count",
        "raw_false_count",
        "raw_null_count",
        "confirmed_true_count",
        "confirmation_event_count",
        "confirmed_interval_count",
        "security_with_interval_count",
        "right_censored_interval_count",
    )
    for record in records:
        name = str(record["logical_request_name"])
        daily = db.execute(
            "SELECT count(*),count(*) FILTER(WHERE joint_ready),"
            "count(*) FILTER(WHERE raw_state=true),count(*) FILTER(WHERE raw_state=false),"
            "count(*) FILTER(WHERE raw_state IS NULL),count(*) FILTER(WHERE confirmed_state=true),"
            "count(*) FILTER(WHERE confirmation_event) FROM response_daily WHERE logical_request_name=?",
            [name],
        ).fetchone()
        interval = db.execute(
            "SELECT count(*),count(DISTINCT security_id),count(*) FILTER(WHERE right_censored),"
            "median(confirmed_observation_count) FROM interval_inventory WHERE logical_request_name=?",
            [name],
        ).fetchone()
        actual = dict(zip(fields, (*daily, *interval[:3])))
        actual["duration_median"] = interval[3]
        stored = json.loads(record["metrics_json"])
        stored_flat = {field: stored.get(field) for field in fields}
        stored_flat["duration_median"] = stored.get("duration_quantiles", {}).get(
            "median"
        )
        compact = dict(csv_rows.get((name,), {}))
        duration = _literal(compact.get("duration_quantiles", ""))
        compact["duration_median"] = (
            duration.get("median") if isinstance(duration, Mapping) else None
        )
        _compare_fields(
            review,
            "request_metric",
            actual,
            stored_flat,
            (*fields, "duration_median"),
            name,
        )
        _compare_fields(
            review,
            "request_metric",
            actual,
            compact,
            (*fields, "duration_median"),
            name,
        )
    return len(records), validator_passed


def _year_metrics(review: Review, db: duckdb.DuckDBPyConnection, bundle: Path) -> None:
    csv_rows = _indexed(
        _csv(bundle / "year_metrics.csv"), ("logical_request_name", "year")
    )
    records = _rows(
        db, "SELECT * FROM year_metrics_records ORDER BY logical_request_name,year"
    )
    record_keys = {
        (str(row["logical_request_name"]), int(row["year"])) for row in records
    }
    daily_keys = {
        (str(name), int(year))
        for name, year in db.execute(
            "SELECT DISTINCT logical_request_name,year(trading_date) "
            "FROM response_daily"
        ).fetchall()
    }
    review.equal("year_metric", "request_year_key_set", record_keys, daily_keys)
    review.equal(
        "year_metric",
        "compact_request_year_key_set",
        set(csv_rows),
        {(name, str(year)) for name, year in daily_keys},
    )
    for record in records:
        name, year = str(record["logical_request_name"]), int(record["year"])
        confirmation = db.execute(
            "SELECT count(*) FILTER(WHERE confirmation_event) FROM response_daily "
            "WHERE logical_request_name=? AND year(trading_date)=?",
            [name, year],
        ).fetchone()[0]
        values = db.execute(
            "SELECT count(*),count(DISTINCT security_id),median(confirmed_observation_count),"
            "avg(right_censored::INT) FROM interval_inventory WHERE logical_request_name=? "
            "AND year(confirmation_date)=?",
            [name, year],
        ).fetchone()
        termination = {
            str(reason): int(count)
            for reason, count in db.execute(
                "SELECT termination_reason,count(*) FROM interval_inventory WHERE "
                "logical_request_name=? AND year(confirmation_date)=? GROUP BY 1",
                [name, year],
            ).fetchall()
        }
        actual = {
            "confirmation_events": confirmation,
            "interval_count": values[0],
            "security_breadth": values[1],
            "duration_median": values[2],
            "right_censored_rate": values[3],
            "termination_distribution": termination,
        }
        stored = json.loads(record["metrics_json"])
        compact = dict(csv_rows.get((name, str(year)), {}))
        compact["termination_distribution"] = _literal(
            compact.get("termination_distribution", "")
        )
        fields = tuple(actual)
        _compare_fields(review, "year_metric", actual, stored, fields, (name, year))
        _compare_fields(review, "year_metric", actual, compact, fields, (name, year))


def _termination_metrics(
    review: Review, db: duckdb.DuckDBPyConnection, bundle: Path
) -> None:
    expected_db = _indexed(
        _rows(db, "SELECT * FROM termination_metrics_records"),
        ("logical_request_name", "termination_reason"),
    )
    expected_csv = _indexed(
        _csv(bundle / "termination_metrics.csv"),
        ("logical_request_name", "termination_reason"),
    )
    actual_rows = _rows(
        db,
        "SELECT logical_request_name,termination_reason,count(*) count,"
        "count(*)::DOUBLE/sum(count(*)) OVER(PARTITION BY logical_request_name) rate "
        "FROM interval_inventory GROUP BY 1,2",
    )
    actual = _indexed(actual_rows, ("logical_request_name", "termination_reason"))
    review.equal("termination_metric", "key_set_db", set(actual), set(expected_db))
    review.equal("termination_metric", "key_set_csv", set(actual), set(expected_csv))
    for key, row in actual.items():
        _compare_fields(
            review,
            "termination_metric",
            row,
            expected_db.get(key),
            ("count", "rate"),
            key,
        )
        _compare_fields(
            review,
            "termination_metric",
            row,
            expected_csv.get(key),
            ("count", "rate"),
            key,
        )


def _response_checks(
    review: Review, db: duckdb.DuckDBPyConnection, bundle: Path
) -> None:
    left_name = "CA_q15_k5"
    right_name = "CA_q25_k5"
    comparison = "CA_q15_k5 -> CA_q25_k5"

    def subset(field: str) -> tuple[int, bool]:
        violation = int(
            db.execute(
                f"SELECT count(*) FROM response_daily l ANTI JOIN response_daily r "
                "ON l.security_id=r.security_id AND l.trading_date=r.trading_date "
                f"AND r.logical_request_name=? AND r.{field}=true "
                f"WHERE l.logical_request_name=? AND l.{field}=true",
                [right_name, left_name],
            ).fetchone()[0]
        )
        right_only = int(
            db.execute(
                f"SELECT count(*) FROM response_daily r ANTI JOIN response_daily l "
                "ON l.security_id=r.security_id AND l.trading_date=r.trading_date "
                f"AND l.logical_request_name=? AND l.{field}=true "
                f"WHERE r.logical_request_name=? AND r.{field}=true",
                [left_name, right_name],
            ).fetchone()[0]
        )
        return violation, right_only > 0

    joint_mismatch = int(
        db.execute(
            "SELECT count(*) FROM (SELECT security_id,trading_date,joint_ready FROM "
            "response_daily WHERE logical_request_name=?) l FULL JOIN (SELECT "
            "security_id,trading_date,joint_ready FROM response_daily WHERE "
            "logical_request_name=?) r USING(security_id,trading_date) WHERE "
            "l.security_id IS NULL OR r.security_id IS NULL OR "
            "l.joint_ready IS DISTINCT FROM r.joint_ready",
            [left_name, right_name],
        ).fetchone()[0]
    )
    raw_violation, raw_strict = subset("raw_state")
    confirmed_violation, confirmed_strict = subset("confirmed_state")
    non_degenerate = raw_strict or confirmed_strict
    computed = {
        "ca_q_joint_ready_equality": {
            "comparison": comparison,
            "violation_count": joint_mismatch,
            "strict_change": False,
            "passed": joint_mismatch == 0,
        },
        "ca_q_raw_subset": {
            "comparison": comparison,
            "violation_count": raw_violation,
            "strict_change": raw_strict,
            "passed": raw_violation == 0,
        },
        "ca_q_confirmed_subset": {
            "comparison": comparison,
            "violation_count": confirmed_violation,
            "strict_change": confirmed_strict,
            "passed": confirmed_violation == 0,
        },
        "ca_q_response_non_degenerate": {
            "comparison": comparison,
            "violation_count": 0 if non_degenerate else 1,
            "strict_change": non_degenerate,
            "passed": non_degenerate,
        },
    }
    db_rows = _indexed(_rows(db, "SELECT * FROM response_checks"), ("check_id",))
    csv_rows = _indexed(_csv(bundle / "response_checks.csv"), ("check_id",))
    review.equal(
        "response_check",
        "check_id_set_db",
        set(computed),
        {key[0] for key in db_rows},
    )
    review.equal(
        "response_check",
        "check_id_set_csv",
        set(computed),
        {key[0] for key in csv_rows},
    )
    for key, actual in computed.items():
        require_strict = key == "ca_q_response_non_degenerate"
        if (
            actual["violation_count"] != 0
            or not actual["passed"]
            or require_strict
            and actual["strict_change"] is not True
        ):
            review.fail(
                "response_check",
                "independent_response_failure",
                expected="zero_violation_and_required_strict",
                actual=actual,
                key=key,
            )
        _compare_fields(
            review,
            "response_check",
            actual,
            db_rows.get((key,)),
            ("comparison", "violation_count", "strict_change", "passed"),
            key,
        )
        _compare_fields(
            review,
            "response_check",
            actual,
            csv_rows.get((key,)),
            ("comparison", "violation_count", "strict_change", "passed"),
            key,
        )


def _describe(db: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[str, str]]:
    if relation.startswith("read_parquet("):
        relation = f"SELECT * FROM {relation}"
    return [
        (str(row[0]), str(row[1]))
        for row in db.execute(f"DESCRIBE {relation}").fetchall()
    ]


def _relation_hash(db: duckdb.DuckDBPyConnection, relation: str, order: str) -> str:
    cursor = db.execute(f"SELECT * FROM {relation} ORDER BY {order}")
    digest = hashlib.sha256()
    while rows := cursor.fetchmany(65_536):
        for row in rows:
            digest.update(
                json.dumps(
                    _normal(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _intervals(
    review: Review, db: duckdb.DuckDBPyConnection, run_root: Path, bundle: Path
) -> None:
    duplicate = int(
        db.execute(
            "SELECT count(*) FROM (SELECT logical_request_name,request_id,security_id,interval_ordinal,count(*) n "
            "FROM interval_inventory GROUP BY 1,2,3,4 HAVING n<>1)"
        ).fetchone()[0]
    )
    review.equal("interval_inventory", "primary_key_duplicates", duplicate, 0)
    count_mismatches = int(
        db.execute(
            "SELECT count(*) FROM request_metrics_records r LEFT JOIN (SELECT logical_request_name,count(*) n "
            "FROM interval_inventory GROUP BY 1) i USING(logical_request_name) WHERE "
            "CAST(json_extract(r.metrics_json,'$.confirmed_interval_count') AS BIGINT)<>coalesce(i.n,0)"
        ).fetchone()[0]
    )
    review.equal("interval_inventory", "request_interval_counts", count_mismatches, 0)
    parquet_path = run_root / "interval_inventory.parquet"
    escaped = parquet_path.as_posix().replace("'", "''")
    try:
        review.equal(
            "interval_parquet",
            "schema",
            _describe(db, f"read_parquet('{escaped}')"),
            _describe(db, "interval_inventory"),
        )
        parquet_count = int(
            db.execute(f"SELECT count(*) FROM read_parquet('{escaped}')").fetchone()[0]
        )
        db_count = int(
            db.execute("SELECT count(*) FROM interval_inventory").fetchone()[0]
        )
        review.equal("interval_parquet", "row_count", parquet_count, db_count)
        keys = "logical_request_name,request_id,security_id,interval_ordinal"
        review.equal(
            "interval_parquet",
            "canonical_fingerprint",
            _relation_hash(db, f"read_parquet('{escaped}')", keys),
            _relation_hash(db, "interval_inventory", keys),
        )
    except Exception as error:
        review.fail(
            "interval_parquet",
            "parquet_read_failed",
            expected="readable_and_reconciled",
            actual=f"{type(error).__name__}:{error}",
        )
    actual_security = _indexed(
        _rows(
            db,
            "SELECT logical_request_name,security_id,count(*) interval_count,sum(confirmed_observation_count) "
            "confirmed_observation_total,count(*) FILTER(WHERE right_censored) right_censored_interval_count,"
            "max(confirmed_observation_count) max_interval_duration FROM interval_inventory GROUP BY 1,2",
        ),
        ("logical_request_name", "security_id"),
    )
    compact_security = _indexed(
        _csv(run_root / "interval_security_distribution.csv"),
        ("logical_request_name", "security_id"),
    )
    review.equal(
        "interval_security_distribution",
        "key_set",
        set(actual_security),
        set(compact_security),
    )
    for key, row in actual_security.items():
        _compare_fields(
            review,
            "interval_security_distribution",
            row,
            compact_security.get(key),
            (
                "interval_count",
                "confirmed_observation_total",
                "right_censored_interval_count",
                "max_interval_duration",
            ),
            key,
        )
    expected_samples = _rows(
        db,
        "WITH ranked AS (SELECT *,sha256(request_hash||':'||security_id||':'||CAST(confirmation_date AS VARCHAR)||':'||"
        "CAST(interval_ordinal AS VARCHAR)) sample_hash,row_number() OVER(PARTITION BY logical_request_name ORDER BY "
        "sha256(request_hash||':'||security_id||':'||CAST(confirmation_date AS VARCHAR)||':'||CAST(interval_ordinal AS VARCHAR)),"
        "security_id,interval_ordinal) n FROM interval_inventory) SELECT logical_request_name,request_id,request_hash,security_id,"
        "interval_ordinal,raw_start_date,confirmation_date,last_confirmed_end_date,termination_date,termination_reason,"
        "confirmed_observation_count,right_censored,sample_hash FROM ranked WHERE n<=20 ORDER BY 1,sample_hash",
    )
    actual_samples = _csv(bundle / "interval_samples.csv")
    review.equal(
        "interval_sample", "row_count", len(actual_samples), len(expected_samples)
    )
    for index, expected in enumerate(expected_samples):
        actual = actual_samples[index] if index < len(actual_samples) else None
        if actual is None:
            review.fail(
                "interval_sample",
                "missing_row",
                expected=expected,
                actual=None,
                key=index,
            )
        else:
            for field, value in expected.items():
                review.equal(
                    "interval_sample", field, actual.get(field), value, key=index
                )


def _endpoint_summary_query(table: str) -> str:
    if table == "score_dimension_structure":
        values = (
            ("score_dimension", "score_dimension"),
            ("score_dimension_min", "score_dimension_min"),
        )
        identity = "logical_request_name,anchor_type,dimension_id"
        eligible = "eligible_dimension"
    else:
        values = (
            ("raw_value", "raw_value"),
            ("percentile", "percentile"),
            ("score", "score"),
        )
        identity = "logical_request_name,anchor_type,dimension_id,component_id"
        eligible = "eligible"
    quantiles = ",".join(
        f"quantile_cont({column},{q}) {prefix}_p{int(q * 100):02d}"
        for column, prefix in values
        for q in (0.10, 0.25, 0.50, 0.75, 0.90)
    )
    return f"SELECT {identity},count(*) row_count,count(*) FILTER(WHERE {eligible}) eligible_count,avg({eligible}::INT) eligible_rate,count(*) FILTER(WHERE validity_status='valid') valid_count,avg((validity_status='valid')::INT) valid_rate,{quantiles} FROM {table} GROUP BY {identity} ORDER BY {identity}"


def _endpoints(review: Review, db: duckdb.DuckDBPyConnection, bundle: Path) -> None:
    expected = {
        str(name): int(count)
        for name, count in db.execute(
            "SELECT logical_request_name,sum((raw_start_date IS NOT NULL)::INT+(confirmation_date IS NOT NULL)::INT+"
            "(last_confirmed_end_date IS NOT NULL)::INT+(termination_date IS NOT NULL)::INT) FROM interval_inventory GROUP BY 1"
        ).fetchall()
    }
    for category, table, multiplier, keys, filename in (
        (
            "dimension_endpoint",
            "score_dimension_structure",
            5,
            (
                "logical_request_name",
                "request_id",
                "security_id",
                "interval_ordinal",
                "anchor_type",
                "dimension_id",
            ),
            "score_dimension_endpoint_summary.csv",
        ),
        (
            "component_endpoint",
            "score_component_structure",
            10,
            (
                "logical_request_name",
                "request_id",
                "security_id",
                "interval_ordinal",
                "anchor_type",
                "dimension_id",
                "component_id",
            ),
            "score_component_endpoint_summary.csv",
        ),
    ):
        actual_counts = {
            str(name): int(count)
            for name, count in db.execute(
                f"SELECT logical_request_name,count(*) FROM {table} GROUP BY 1"
            ).fetchall()
        }
        for name, endpoints in expected.items():
            review.equal(
                category,
                "endpoint_row_count",
                actual_counts.get(name, 0),
                endpoints * multiplier,
                key=name,
            )
        group = ",".join(str(index) for index in range(1, len(keys) + 1))
        duplicate = int(
            db.execute(
                f"SELECT count(*) FROM (SELECT {','.join(keys)},count(*) n FROM {table} GROUP BY {group} HAVING n<>1)"
            ).fetchone()[0]
        )
        review.equal(category, "primary_key_duplicates", duplicate, 0)
        actual_summary = _rows(db, _endpoint_summary_query(table))
        compact_summary = _csv(bundle / filename)
        review.equal(
            category, "summary_row_count", len(compact_summary), len(actual_summary)
        )
        for index, expected_row in enumerate(actual_summary):
            actual_row = (
                compact_summary[index] if index < len(compact_summary) else None
            )
            if actual_row is None:
                review.fail(
                    category,
                    "summary_missing_row",
                    expected=expected_row,
                    actual=None,
                    key=index,
                )
            else:
                for field, value in expected_row.items():
                    review.equal(
                        category,
                        f"summary_{field}",
                        actual_row.get(field),
                        value,
                        key=index,
                    )


def _audit_database(review: Review, run_root: Path, bundle: Path) -> tuple[int, int]:
    audit_path = run_root / "audit_metrics.duckdb"
    with duckdb.connect(str(audit_path), read_only=True) as db:
        tables = {
            str(row[0])
            for row in db.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'"
            ).fetchall()
        }
        review.equal("audit", "required_tables", REQUIRED_AUDIT_TABLES <= tables, True)
        forbidden = sorted(
            name
            for name in tables
            if any(pattern in name.lower() for pattern in FORBIDDEN_TABLE_PATTERNS)
        )
        review.counts["forbidden_table"] += len(forbidden)
        if forbidden:
            review.fail("audit", "forbidden_tables", expected=[], actual=forbidden)
        request_count, passed_count = _request_metrics(review, db, bundle)
        _year_metrics(review, db, bundle)
        _termination_metrics(review, db, bundle)
        _response_checks(review, db, bundle)
        _intervals(review, db, run_root, bundle)
        _endpoints(review, db, bundle)
    with duckdb.connect(str(audit_path), read_only=True) as reopened:
        reopened.execute("SELECT 1").fetchone()
    return request_count, passed_count


def _receipt(
    review: Review,
    run_root: Path,
    formal_run_id: str,
    panel_count: int,
    validator_count: int,
    validator_passed: int,
) -> dict[str, Any]:
    status = "passed" if not review.mismatches else "failed"
    receipt: dict[str, Any] = {
        "task_id": TASK_ID,
        "scope_id": SCOPE_ID,
        "formal_run_id": formal_run_id,
        "formal_authorization_id": AUTHORIZATION_ID,
        "authorization_revision": AUTHORIZATION_REVISION,
        "status": status,
        **review.statuses,
        "panel_count": panel_count,
        "request_validator_count": validator_count,
        "request_validator_passed_count": validator_passed,
    }
    for counter in MISMATCH_COUNTERS:
        receipt[f"{counter}_mismatch_count"] = int(review.counts[counter])
    receipt["forbidden_table_count"] = int(review.counts["forbidden_table"])
    receipt["forbidden_field_count"] = int(review.counts["forbidden_field"])
    receipt["mismatch_count"] = len(review.mismatches)
    receipt["mismatch_fingerprint"] = _canonical_hash(review.mismatches)
    receipt["mismatches"] = review.mismatches
    return receipt


def run_independent_review(
    *,
    score_db: Path,
    run_root: Path,
    review_bundle: Path,
    expected_score_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the independent review and always attempt to persist its receipt."""

    review = Review()
    panel_count = validator_count = validator_passed = 0
    formal_run_id = run_root.name
    try:
        bundle_result = _check_bundle(review, review_bundle)
        del bundle_result
        _check_root_inventory(review, run_root)
        summary = _json(review_bundle / "run_summary.json")
        _check_score_identity(
            review,
            score_db,
            run_root,
            review_bundle,
            summary,
            dict(expected_score_identity or EXPECTED_SCORE_IDENTITY),
        )
        _check_run_identity(review, run_root, review_bundle, summary)
        panel_count = len(_check_panel(review, run_root, review_bundle))
        validator_count, validator_passed = _audit_database(
            review, run_root, review_bundle
        )
    except Exception as error:  # receipt must survive every fail-closed path
        review.fail(
            "execution",
            "independent_review_exception",
            expected="all_checks_executable",
            actual=f"{type(error).__name__}:{error}",
        )
    receipt = _receipt(
        review,
        run_root,
        formal_run_id,
        panel_count,
        validator_count,
        validator_passed,
    )
    try:
        run_root.mkdir(parents=True, exist_ok=True)
        (run_root / "independent_review_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        review.fail("execution", "receipt_write_failed", actual=type(error).__name__)
        receipt = _receipt(
            review,
            run_root,
            formal_run_id,
            panel_count,
            validator_count,
            validator_passed,
        )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    receipt = run_independent_review(
        score_db=args.score_db,
        run_root=args.run_root,
        review_bundle=args.review_bundle,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
