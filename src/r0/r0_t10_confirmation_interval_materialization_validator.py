from __future__ import annotations

# ruff: noqa: E501
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import LEGACY_V1_FIELD_NAMES
from src.r0.confirmation_interval_engine import (
    compute_confirmed_intervals,
    compute_daily_confirmations,
)
from src.r0.daily_state_engine import WEAK_DELTA
from src.r0.formal_run_identity import FULL_GIT_SHA_RE
from src.r0.r0_t10_confirmation_interval_materializer import (
    CONFIRMED_INTERVAL_DUCKDB_NAME,
    CONFIRMED_INTERVAL_TABLE_NAME,
    DAILY_CONFIRMATION_DUCKDB_NAME,
    DAILY_CONFIRMATION_TABLE_NAME,
    MANIFEST_NAME,
    SUMMARY_NAME,
)
from src.r0.r0_t10_nested_state_materializer import NESTED_DAILY_TABLE_NAME
from src.r0.upstream_artifact_io import quote_ident, sha256_file

FORBIDDEN_FIELD_FRAGMENTS = {
    "future",
    "return",
    "backtest",
    "portfolio",
    "signal",
    "release_direction",
    "breakout_direction",
    "r0_t08",
    "r0_t09",
}


class R0T10ConfirmationIntervalValidationError(RuntimeError):
    pass


def validate_materialization(
    output_dir: str | Path,
    *,
    r0_t06_evidence: str | Path,
    nested_daily_state_duckdb: str | Path,
) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = root / MANIFEST_NAME
    summary_path = root / SUMMARY_NAME
    manifest = _load_json_object(manifest_path)
    summary = _load_json_object(summary_path)
    evidence = _parse_r0_t06_evidence(Path(r0_t06_evidence))
    errors: list[str] = []

    _validate_input_gate(evidence, Path(nested_daily_state_duckdb), errors)
    full_code_commit_check = _validate_code_commits(manifest, summary, errors)
    _check_no_row_payload(manifest, "manifest", errors)
    _check_no_row_payload(summary, "summary", errors)
    _validate_output_hashes(root, manifest, errors)
    shard_counts = _validate_shards(manifest, errors)
    stats = {
        "daily_confirmation": _daily_stats(
            root / DAILY_CONFIRMATION_DUCKDB_NAME,
            DAILY_CONFIRMATION_TABLE_NAME,
            errors,
        ),
        "confirmed_interval": _interval_stats(
            root / CONFIRMED_INTERVAL_DUCKDB_NAME,
            CONFIRMED_INTERVAL_TABLE_NAME,
            errors,
        ),
    }
    _validate_counts(manifest, summary, shard_counts, stats, errors)
    _validate_coverage(stats, errors)
    _validate_semantics(stats, errors)
    _validate_forbidden_and_legacy(stats, errors)
    daily_recompute = _validate_deterministic_daily_recompute(
        root=root,
        nested_daily_state_duckdb=Path(nested_daily_state_duckdb),
        errors=errors,
    )
    interval_recompute = _validate_deterministic_interval_recompute(
        root=root,
        errors=errors,
    )
    confirmed_nested_invariant_check = (
        "passed"
        if not stats["daily_confirmation"].get("confirmed_nested_invariant_hit_count")
        else "blocked"
    )
    no_backfill_check = (
        "passed"
        if not stats["daily_confirmation"].get("backfill_hit_count")
        else "blocked"
    )
    result = {
        "status": "passed" if not errors else "failed",
        "output_dir": str(root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path)
        if manifest_path.exists()
        else None,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path) if summary_path.exists() else None,
        "duckdb_sha256": {
            "daily_confirmation": sha256_file(root / DAILY_CONFIRMATION_DUCKDB_NAME)
            if (root / DAILY_CONFIRMATION_DUCKDB_NAME).exists()
            else None,
            "confirmed_interval": sha256_file(root / CONFIRMED_INTERVAL_DUCKDB_NAME)
            if (root / CONFIRMED_INTERVAL_DUCKDB_NAME).exists()
            else None,
        },
        "manifest_counts": {
            "daily_confirmation": int(manifest.get("daily_confirmation_row_count", -1)),
            "confirmed_interval": int(manifest.get("confirmed_interval_row_count", -1)),
        },
        "shard_counts": shard_counts,
        "duckdb_stats": stats,
        "daily_recompute_sample_count": daily_recompute["sample_count"],
        "daily_recompute_mismatch_count": daily_recompute["mismatch_count"],
        "daily_recompute_W_coverage": daily_recompute["W_coverage"],
        "daily_recompute_q_coverage": daily_recompute["q_coverage"],
        "daily_recompute_K_coverage": daily_recompute["K_coverage"],
        "daily_recompute_state_name_coverage": daily_recompute["state_name_coverage"],
        "confirmed_true_sample_count": daily_recompute["confirmed_true_sample_count"],
        "raw_false_sample_count": daily_recompute["raw_false_sample_count"],
        "raw_non_ready_sample_count": daily_recompute["raw_non_ready_sample_count"],
        "daily_recompute_skipped_reasons": daily_recompute["skipped_reasons"],
        "interval_recompute_sample_count": interval_recompute["sample_count"],
        "interval_recompute_mismatch_count": interval_recompute["mismatch_count"],
        "open_interval_sample_count": interval_recompute["open_interval_sample_count"],
        "closed_interval_sample_count": interval_recompute[
            "closed_interval_sample_count"
        ],
        "false_termination_sample_count": interval_recompute[
            "false_termination_sample_count"
        ],
        "non_ready_termination_sample_count": interval_recompute[
            "non_ready_termination_sample_count"
        ],
        "interval_recompute_skipped_reasons": interval_recompute["skipped_reasons"],
        "confirmed_nested_invariant_check": confirmed_nested_invariant_check,
        "no_backfill_check": no_backfill_check,
        "forbidden_field_check": "passed"
        if not any(item.get("forbidden_field_hit_count") for item in stats.values())
        else "blocked",
        "legacy_v1_check": "passed"
        if not any(item.get("legacy_v1_hit_count") for item in stats.values())
        else "blocked",
        "future_return_absence_check": "passed"
        if not any(item.get("forbidden_field_hit_count") for item in stats.values())
        else "blocked",
        "full_code_commit_check": full_code_commit_check,
        "R0-T10-05_allowed_to_start": not errors,
        "errors": errors,
    }
    if errors:
        raise R0T10ConfirmationIntervalValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def _validate_input_gate(
    evidence: Mapping[str, Any], nested_path: Path, errors: list[str]
) -> None:
    if evidence.get("R0-T07_allowed_to_start") != "true":
        errors.append("r0_t06_evidence_gate_not_open")
    if not nested_path.is_file():
        errors.append("input_nested_daily_state_duckdb_missing")
        return
    expected = evidence.get("nested_daily_state_duckdb_sha256")
    if expected and sha256_file(nested_path) != expected:
        errors.append("input_nested_daily_state_duckdb_hash_mismatch")


def _validate_code_commits(
    manifest: Mapping[str, Any], summary: Mapping[str, Any], errors: list[str]
) -> str:
    manifest_commit = str(manifest.get("code_commit", ""))
    summary_commit = str(summary.get("code_commit", ""))
    if not FULL_GIT_SHA_RE.fullmatch(manifest_commit) or not FULL_GIT_SHA_RE.fullmatch(
        summary_commit
    ):
        errors.append("short_code_commit_forbidden")
        return "blocked"
    if manifest_commit != summary_commit:
        errors.append("code_commit_mismatch")
        return "blocked"
    return "passed"


def _validate_output_hashes(
    root: Path, manifest: Mapping[str, Any], errors: list[str]
) -> None:
    outputs = manifest.get("output_hashes", {})
    if not isinstance(outputs, Mapping):
        errors.append("manifest_output_hashes_missing")
        return
    for key, filename in (
        ("daily_confirmation", DAILY_CONFIRMATION_DUCKDB_NAME),
        ("confirmed_interval", CONFIRMED_INTERVAL_DUCKDB_NAME),
    ):
        path = root / filename
        expected = outputs.get(key)
        if not path.is_file():
            errors.append(f"{key}_duckdb_missing")
        elif expected != sha256_file(path):
            errors.append(f"{key}_duckdb_hash_mismatch")


def _validate_shards(manifest: Mapping[str, Any], errors: list[str]) -> dict[str, int]:
    counts = {"daily_confirmation": 0, "confirmed_interval": 0}
    shards = manifest.get("shards", [])
    if not isinstance(shards, list) or not shards:
        errors.append("manifest_shards_missing")
        return counts
    done_marker_count = 0
    for shard in shards:
        if not isinstance(shard, Mapping):
            errors.append("manifest_shard_not_object")
            continue
        done_path = Path(str(shard.get("done_marker_path", "")))
        if not done_path.is_file():
            errors.append("done_marker_missing")
        else:
            done_marker_count += 1
        for key in counts:
            section = shard.get(key)
            if not isinstance(section, Mapping):
                errors.append(f"{key}_shard_section_missing")
                continue
            path = Path(str(section.get("path", "")))
            if not path.is_file():
                errors.append(f"{key}_shard_missing")
                continue
            if section.get("file_sha256") != sha256_file(path):
                errors.append(f"{key}_shard_hash_mismatch")
            counts[key] += int(section.get("row_count", 0))
    counts["DONE_marker_count"] = done_marker_count
    return counts


def _daily_stats(path: Path, table_name: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if table_name not in tables:
            errors.append("daily_confirmation_table_missing")
            return {}
        schema = _schema(conn, table_name)
        row = conn.execute(
            f"""
            SELECT
              count(*),
              count(DISTINCT security_id),
              min(trading_date),
              max(trading_date),
              count(*) - count(DISTINCT (
                security_id,
                trading_date,
                percentile_window_W,
                q,
                weak_delta,
                state_name,
                confirmation_k
              )),
              sum(CASE WHEN confirmation_k NOT IN (2,3,5) THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmation_k = 1 THEN 1 ELSE 0 END),
              sum(CASE WHEN raw_state = true AND validity_status = 'valid' AND raw_streak IS NULL THEN 1 ELSE 0 END),
              sum(CASE WHEN raw_state = false AND validity_status = 'valid' AND raw_streak != 0 THEN 1 ELSE 0 END),
              sum(CASE WHEN validity_status != 'valid' AND raw_streak IS NOT NULL THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmed_state = true AND (raw_state IS DISTINCT FROM true OR raw_streak < confirmation_k) THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmed_state = true AND trading_date < confirmation_date THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmed_state = true THEN 1 ELSE 0 END)
            FROM {quote_ident(table_name)} d
            """
        ).fetchone()
        confirmed_true_count = int(row[12] or 0)
        confirmed_nested_invariant_hit_count = (
            0
            if confirmed_true_count == 0
            else _confirmed_nested_invariant_hit_count(conn, table_name)
        )
        coverage = _coverage(conn, table_name)
        distributions = {
            "confirmed_state": _distribution(conn, table_name, "confirmed_state"),
            "raw_state": _distribution(conn, table_name, "raw_state"),
            "validity_status": _distribution(conn, table_name, "validity_status"),
        }
    finally:
        conn.close()
    return {
        "table_name": table_name,
        "row_count": int(row[0]),
        "security_count": int(row[1]),
        "date_min": None if row[2] is None else str(row[2]),
        "date_max": None if row[3] is None else str(row[3]),
        "duplicate_key_hit_count": int(row[4] or 0),
        "invalid_k_hit_count": int(row[5] or 0),
        "k1_hit_count": int(row[6] or 0),
        "true_streak_missing_hit_count": int(row[7] or 0),
        "false_streak_hit_count": int(row[8] or 0),
        "non_ready_streak_hit_count": int(row[9] or 0),
        "confirmed_state_invalid_hit_count": int(row[10] or 0),
        "backfill_hit_count": int(row[11] or 0),
        "confirmed_true_count": confirmed_true_count,
        "confirmed_nested_invariant_hit_count": confirmed_nested_invariant_hit_count,
        **coverage,
        **distributions,
        **_field_guard_stats(schema),
    }


def _interval_stats(path: Path, table_name: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if table_name not in tables:
            errors.append("confirmed_interval_table_missing")
            return {}
        schema = _schema(conn, table_name)
        row = conn.execute(
            f"""
            SELECT
              count(*),
              count(DISTINCT security_id),
              min(confirmation_date),
              max(last_observed_date),
              sum(CASE WHEN confirmation_k NOT IN (2,3,5) THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmation_k = 1 THEN 1 ELSE 0 END),
              sum(CASE WHEN is_open_interval = true AND termination_reason != 'end_of_input_open' THEN 1 ELSE 0 END),
              sum(CASE WHEN is_open_interval = false AND termination_reason = 'end_of_input_open' THEN 1 ELSE 0 END),
              sum(CASE WHEN raw_duration_observations < confirmed_duration_observations THEN 1 ELSE 0 END),
              sum(CASE WHEN confirmed_duration_observations < 1 THEN 1 ELSE 0 END),
              sum(CASE WHEN termination_reason NOT IN (
                'raw_state_false',
                'raw_state_unknown',
                'raw_state_diagnostic_required',
                'raw_state_blocked',
                'end_of_input_open'
              ) THEN 1 ELSE 0 END)
            FROM {quote_ident(table_name)}
            """
        ).fetchone()
        coverage = _coverage(conn, table_name)
        termination_distribution = _distribution(conn, table_name, "termination_reason")
        open_count = int(
            conn.execute(
                f"SELECT count(*) FROM {quote_ident(table_name)} WHERE is_open_interval = true"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return {
        "table_name": table_name,
        "row_count": int(row[0]),
        "security_count": int(row[1]),
        "date_min": None if row[2] is None else str(row[2]),
        "date_max": None if row[3] is None else str(row[3]),
        "invalid_k_hit_count": int(row[4] or 0),
        "k1_hit_count": int(row[5] or 0),
        "open_termination_hit_count": int(row[6] or 0),
        "closed_termination_hit_count": int(row[7] or 0),
        "duration_inversion_hit_count": int(row[8] or 0),
        "unconfirmed_interval_hit_count": int(row[9] or 0),
        "invalid_termination_reason_hit_count": int(row[10] or 0),
        "open_interval_count": open_count,
        "closed_interval_count": int(row[0]) - open_count,
        "termination_reason_distribution": termination_distribution[
            "termination_reason_distribution"
        ],
        **coverage,
        **_field_guard_stats(schema),
    }


def _confirmed_nested_invariant_hit_count(conn: Any, table_name: str) -> int:
    return int(
        conn.execute(
            f"""
            WITH confirmed AS (
              SELECT *
              FROM {quote_ident(table_name)}
              WHERE confirmed_state = true
            ), pivoted AS (
              SELECT
                security_id,
                trading_date,
                percentile_window_W,
                q,
                weak_delta,
                confirmation_k,
                max(CASE WHEN state_name = 'S_P' THEN confirmed_state ELSE false END) AS s_p,
                max(CASE WHEN state_name = 'S_PC' THEN confirmed_state ELSE false END) AS s_pc,
                max(CASE WHEN state_name = 'S_PCT' THEN confirmed_state ELSE false END) AS s_pct,
                max(CASE WHEN state_name = 'S_PCVT' THEN confirmed_state ELSE false END) AS s_pcvt
              FROM confirmed
              GROUP BY
                security_id,
                trading_date,
                percentile_window_W,
                q,
                weak_delta,
                confirmation_k
            )
            SELECT count(*)
            FROM pivoted
            WHERE (s_pcvt = true AND s_pct IS DISTINCT FROM true)
               OR (s_pct = true AND s_pc IS DISTINCT FROM true)
               OR (s_pc = true AND s_p IS DISTINCT FROM true)
            """
        ).fetchone()[0]
    )


def _validate_counts(
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    shard_counts: Mapping[str, int],
    stats: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    for key, manifest_key in (
        ("daily_confirmation", "daily_confirmation_row_count"),
        ("confirmed_interval", "confirmed_interval_row_count"),
    ):
        expected = int(manifest.get(manifest_key, -1))
        if int(summary.get(manifest_key, -2)) != expected:
            errors.append(f"{key}_summary_manifest_count_mismatch")
        if int(shard_counts.get(key, -3)) != expected:
            errors.append(f"{key}_shard_manifest_count_mismatch")
        if int(stats.get(key, {}).get("row_count", -4)) != expected:
            errors.append(f"{key}_duckdb_manifest_count_mismatch")


def _validate_coverage(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    daily = stats.get("daily_confirmation", {})
    for key, expected in (
        ("W_coverage", [120, 250, 500]),
        ("q_coverage", [0.1, 0.2, 0.3]),
        ("K_coverage", [2, 3, 5]),
        ("state_name_coverage", ["S_P", "S_PC", "S_PCT", "S_PCVT"]),
    ):
        if list(daily.get(key, [])) != expected:
            errors.append(f"{key}_mismatch")
    if list(daily.get("weak_delta_coverage", [])) != [WEAK_DELTA]:
        errors.append("weak_delta_coverage_mismatch")


def _validate_semantics(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    for name, section in stats.items():
        for key, value in section.items():
            if key.endswith("_hit_count") and int(value or 0) > 0:
                errors.append(f"{name}_{key}")


def _validate_forbidden_and_legacy(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    for name, section in stats.items():
        if int(section.get("forbidden_field_hit_count", 0)) > 0:
            errors.append(f"{name}_forbidden_field_present")
        if int(section.get("legacy_v1_hit_count", 0)) > 0:
            errors.append(f"{name}_legacy_v1_field_present")


def _validate_deterministic_daily_recompute(
    *,
    root: Path,
    nested_daily_state_duckdb: Path,
    errors: list[str],
) -> dict[str, Any]:
    samples = _select_daily_recompute_samples(root / DAILY_CONFIRMATION_DUCKDB_NAME)
    sample_keys = {
        (
            row["security_id"],
            int(row["percentile_window_W"]),
            round(float(row["q"]), 2),
        )
        for row in samples
    }
    expected_by_key: dict[
        tuple[str, int, float], dict[tuple[str, str, int], dict[str, Any]]
    ] = {}
    for security_id, window, q_value in sample_keys:
        nested_rows = _load_nested_rows(
            nested_daily_state_duckdb, security_id, window, q_value
        )
        expected_rows = compute_daily_confirmations(nested_rows)
        expected_by_key[(security_id, window, q_value)] = {
            (item.trading_date, item.state_name, item.confirmation_k): item.as_dict()
            for item in expected_rows
        }
    mismatch_count = 0
    for sample in samples:
        key = (
            sample["security_id"],
            int(sample["percentile_window_W"]),
            round(float(sample["q"]), 2),
        )
        expected = expected_by_key.get(key, {}).get(
            (
                str(sample["trading_date"]),
                str(sample["state_name"]),
                int(sample["confirmation_k"]),
            )
        )
        if expected is None or not _daily_rows_equivalent(expected, sample):
            mismatch_count += 1
    confirmed_true_count = sum(
        1 for row in samples if row.get("confirmed_state") is True
    )
    raw_false_count = sum(1 for row in samples if row.get("raw_state") is False)
    raw_non_ready_count = sum(
        1 for row in samples if row.get("validity_status") != "valid"
    )
    skipped: list[str] = []
    population = _daily_population(root / DAILY_CONFIRMATION_DUCKDB_NAME)
    if population.get("confirmed_true_count", 0) and confirmed_true_count == 0:
        errors.append("daily_recompute_confirmed_true_missing")
    elif not population.get("confirmed_true_count", 0):
        skipped.append("confirmed_true_absent")
    if population.get("raw_false_count", 0) and raw_false_count == 0:
        errors.append("daily_recompute_raw_false_missing")
    elif not population.get("raw_false_count", 0):
        skipped.append("raw_false_absent")
    if population.get("raw_non_ready_count", 0) and raw_non_ready_count == 0:
        errors.append("daily_recompute_raw_non_ready_missing")
    elif not population.get("raw_non_ready_count", 0):
        skipped.append("raw_non_ready_absent")
    if mismatch_count:
        errors.append("daily_recompute_mismatch")
    return {
        "sample_count": len(samples),
        "mismatch_count": mismatch_count,
        "W_coverage": sorted({int(row["percentile_window_W"]) for row in samples}),
        "q_coverage": sorted({round(float(row["q"]), 2) for row in samples}),
        "K_coverage": sorted({int(row["confirmation_k"]) for row in samples}),
        "state_name_coverage": sorted({str(row["state_name"]) for row in samples}),
        "confirmed_true_sample_count": confirmed_true_count,
        "raw_false_sample_count": raw_false_count,
        "raw_non_ready_sample_count": raw_non_ready_count,
        "skipped_reasons": skipped,
    }


def _validate_deterministic_interval_recompute(
    *, root: Path, errors: list[str]
) -> dict[str, Any]:
    samples = _select_interval_recompute_samples(root / CONFIRMED_INTERVAL_DUCKDB_NAME)
    daily_cache: dict[
        tuple[str, int, float, float, int, str], dict[str, dict[str, Any]]
    ] = {}
    mismatch_count = 0
    for sample in samples:
        key = (
            str(sample["security_id"]),
            int(sample["percentile_window_W"]),
            round(float(sample["q"]), 2),
            round(float(sample["weak_delta"]), 2),
            int(sample["confirmation_k"]),
            str(sample["state_name"]),
        )
        if key not in daily_cache:
            daily_rows = _load_daily_confirmation_group(
                root / DAILY_CONFIRMATION_DUCKDB_NAME, key
            )
            intervals = compute_confirmed_intervals(daily_rows)
            daily_cache[key] = {
                item.interval_id: _interval_as_formal_dict(item) for item in intervals
            }
        expected = daily_cache[key].get(str(sample["interval_id"]))
        if expected is None or not _interval_rows_equivalent(expected, sample):
            mismatch_count += 1
    open_count = sum(1 for row in samples if row.get("is_open_interval") is True)
    closed_count = sum(1 for row in samples if row.get("is_open_interval") is False)
    false_count = sum(
        1 for row in samples if row.get("termination_reason") == "raw_state_false"
    )
    non_ready_count = sum(
        1
        for row in samples
        if row.get("termination_reason")
        in {"raw_state_unknown", "raw_state_diagnostic_required", "raw_state_blocked"}
    )
    skipped: list[str] = []
    population = _interval_population(root / CONFIRMED_INTERVAL_DUCKDB_NAME)
    for key, count, reason in (
        ("open_count", open_count, "open_interval_absent"),
        ("closed_count", closed_count, "closed_interval_absent"),
        ("false_termination_count", false_count, "false_termination_absent"),
        (
            "non_ready_termination_count",
            non_ready_count,
            "non_ready_termination_absent",
        ),
    ):
        if population.get(key, 0) and count == 0:
            errors.append(f"interval_recompute_{reason.replace('_absent', '_missing')}")
        elif not population.get(key, 0):
            skipped.append(reason)
    if mismatch_count:
        errors.append("interval_recompute_mismatch")
    return {
        "sample_count": len(samples),
        "mismatch_count": mismatch_count,
        "open_interval_sample_count": open_count,
        "closed_interval_sample_count": closed_count,
        "false_termination_sample_count": false_count,
        "non_ready_termination_sample_count": non_ready_count,
        "skipped_reasons": skipped,
    }


def _select_daily_recompute_samples(path: Path) -> list[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            f"""
            WITH chosen_security AS (
              SELECT security_id
              FROM {quote_ident(DAILY_CONFIRMATION_TABLE_NAME)}
              GROUP BY security_id
              ORDER BY security_id
              LIMIT 8
            ), candidate AS (
              SELECT d.*
              FROM {quote_ident(DAILY_CONFIRMATION_TABLE_NAME)} d
              JOIN chosen_security s USING (security_id)
            ), ranked AS (
              SELECT *,
                row_number() OVER (
                  PARTITION BY percentile_window_W, q, confirmation_k, state_name
                  ORDER BY security_id, trading_date
                ) AS coverage_rank,
                row_number() OVER (
                  PARTITION BY confirmed_state
                  ORDER BY security_id, trading_date, percentile_window_W, q, state_name, confirmation_k
                ) AS confirmed_rank,
                row_number() OVER (
                  PARTITION BY raw_state
                  ORDER BY security_id, trading_date, percentile_window_W, q, state_name, confirmation_k
                ) AS raw_rank,
                row_number() OVER (
                  PARTITION BY validity_status
                  ORDER BY security_id, trading_date, percentile_window_W, q, state_name, confirmation_k
                ) AS status_rank
              FROM candidate
            )
            SELECT DISTINCT *
            FROM ranked
            WHERE coverage_rank = 1
               OR (confirmed_state = true AND confirmed_rank <= 3)
               OR (raw_state = false AND raw_rank <= 3)
               OR (validity_status != 'valid' AND status_rank <= 3)
            ORDER BY security_id, trading_date, percentile_window_W, q, state_name, confirmation_k
            LIMIT 128
            """
        ).fetchall()
        columns = [item[0] for item in conn.description]
    finally:
        conn.close()
    return [_row_dict(columns, row) for row in rows]


def _select_interval_recompute_samples(path: Path) -> list[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            f"""
            WITH ranked AS (
              SELECT *,
                row_number() OVER (
                  PARTITION BY is_open_interval
                  ORDER BY security_id, confirmation_date, state_name, confirmation_k
                ) AS open_rank,
                row_number() OVER (
                  PARTITION BY termination_reason
                  ORDER BY security_id, confirmation_date, state_name, confirmation_k
                ) AS termination_rank
              FROM {quote_ident(CONFIRMED_INTERVAL_TABLE_NAME)}
            )
            SELECT DISTINCT *
            FROM ranked
            WHERE open_rank <= 3 OR termination_rank <= 3
            ORDER BY security_id, confirmation_date, state_name, confirmation_k
            LIMIT 64
            """
        ).fetchall()
        columns = [item[0] for item in conn.description]
    finally:
        conn.close()
    return [_row_dict(columns, row) for row in rows]


def _load_nested_rows(
    path: Path, security_id: str, window: int, q_value: float
) -> list[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM {quote_ident(NESTED_DAILY_TABLE_NAME)}
            WHERE security_id = ?
              AND percentile_window_W = ?
              AND abs(q - ?) < 1e-12
            ORDER BY trading_date
            """,
            [security_id, window, q_value],
        ).fetchall()
        columns = [item[0] for item in conn.description]
    finally:
        conn.close()
    return [_row_dict(columns, row) for row in rows]


def _load_daily_confirmation_group(
    path: Path, key: tuple[str, int, float, float, int, str]
) -> list[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    security_id, window, q_value, weak_delta, confirmation_k, state_name = key
    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM {quote_ident(DAILY_CONFIRMATION_TABLE_NAME)}
            WHERE security_id = ?
              AND percentile_window_W = ?
              AND abs(q - ?) < 1e-12
              AND abs(weak_delta - ?) < 1e-12
              AND confirmation_k = ?
              AND state_name = ?
            ORDER BY trading_date
            """,
            [security_id, window, q_value, weak_delta, confirmation_k, state_name],
        ).fetchall()
        columns = [item[0] for item in conn.description]
    finally:
        conn.close()
    return [_row_dict(columns, row) for row in rows]


def _daily_population(path: Path) -> dict[str, int]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        row = conn.execute(
            f"""
            SELECT
              sum(CASE WHEN confirmed_state = true THEN 1 ELSE 0 END),
              sum(CASE WHEN raw_state = false THEN 1 ELSE 0 END),
              sum(CASE WHEN validity_status != 'valid' OR raw_state IS NULL THEN 1 ELSE 0 END)
            FROM {quote_ident(DAILY_CONFIRMATION_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    return {
        "confirmed_true_count": int(row[0] or 0),
        "raw_false_count": int(row[1] or 0),
        "raw_non_ready_count": int(row[2] or 0),
    }


def _interval_population(path: Path) -> dict[str, int]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        row = conn.execute(
            f"""
            SELECT
              sum(CASE WHEN is_open_interval = true THEN 1 ELSE 0 END),
              sum(CASE WHEN is_open_interval = false THEN 1 ELSE 0 END),
              sum(CASE WHEN termination_reason = 'raw_state_false' THEN 1 ELSE 0 END),
              sum(CASE WHEN termination_reason IN (
                'raw_state_unknown',
                'raw_state_diagnostic_required',
                'raw_state_blocked'
              ) THEN 1 ELSE 0 END)
            FROM {quote_ident(CONFIRMED_INTERVAL_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    return {
        "open_count": int(row[0] or 0),
        "closed_count": int(row[1] or 0),
        "false_termination_count": int(row[2] or 0),
        "non_ready_termination_count": int(row[3] or 0),
    }


def _daily_rows_equivalent(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> bool:
    fields = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "state_name",
        "confirmation_k",
        "raw_state",
        "raw_streak",
        "raw_streak_start_date",
        "confirmed_state",
        "confirmation_start_date",
        "confirmation_date",
        "validity_status",
    )
    for field in fields:
        if expected.get(field) != actual.get(field):
            return False
    return (
        abs(float(expected["q"]) - float(actual["q"])) < 1e-12
        and abs(float(expected["weak_delta"]) - float(actual["weak_delta"])) < 1e-12
    )


def _interval_rows_equivalent(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> bool:
    fields = (
        "interval_id",
        "security_id",
        "percentile_window_W",
        "state_name",
        "confirmation_k",
        "raw_start_date",
        "confirmation_date",
        "confirmed_start_date",
        "interval_end_date",
        "last_observed_date",
        "raw_duration_observations",
        "confirmed_duration_observations",
        "is_open_interval",
        "termination_reason",
        "validity_status",
    )
    for field in fields:
        if expected.get(field) != actual.get(field):
            return False
    return (
        abs(float(expected["q"]) - float(actual["q"])) < 1e-12
        and abs(float(expected["weak_delta"]) - float(actual["weak_delta"])) < 1e-12
    )


def _interval_as_formal_dict(item: Any) -> dict[str, Any]:
    payload = item.as_dict()
    payload["raw_duration_observations"] = payload.pop("duration_raw_days")
    payload["confirmed_duration_observations"] = payload.pop("duration_confirmed_days")
    return payload


def _coverage(conn: Any, table_name: str) -> dict[str, list[Any]]:
    return {
        "W_coverage": [
            int(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT percentile_window_W FROM {quote_ident(table_name)} ORDER BY 1"
            ).fetchall()
        ],
        "q_coverage": [
            round(float(row[0]), 2)
            for row in conn.execute(
                f"SELECT DISTINCT q FROM {quote_ident(table_name)} ORDER BY 1"
            ).fetchall()
        ],
        "weak_delta_coverage": [
            round(float(row[0]), 2)
            for row in conn.execute(
                f"SELECT DISTINCT weak_delta FROM {quote_ident(table_name)} ORDER BY 1"
            ).fetchall()
        ],
        "K_coverage": [
            int(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT confirmation_k FROM {quote_ident(table_name)} ORDER BY 1"
            ).fetchall()
        ],
        "state_name_coverage": [
            str(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT state_name FROM {quote_ident(table_name)} ORDER BY 1"
            ).fetchall()
        ],
    }


def _distribution(
    conn: Any, table_name: str, column_name: str
) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        f"""
        SELECT CAST({quote_ident(column_name)} AS VARCHAR), count(*)
        FROM {quote_ident(table_name)}
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    return {
        f"{column_name}_distribution": {
            ("NULL" if key is None else str(key)): int(count) for key, count in rows
        }
    }


def _field_guard_stats(schema: Sequence[Mapping[str, str]]) -> dict[str, int]:
    names = {str(row["column_name"]) for row in schema}
    lowered = {name.lower() for name in names}
    forbidden_hits = [
        name
        for name in lowered
        if any(fragment in name for fragment in FORBIDDEN_FIELD_FRAGMENTS)
    ]
    legacy_hits = [name for name in names if name in LEGACY_V1_FIELD_NAMES]
    old_v1_hits = [name for name in names if name == "V1_VolShrink20_60"]
    return {
        "forbidden_field_hit_count": len(forbidden_hits),
        "legacy_v1_hit_count": len(legacy_hits) + len(old_v1_hits),
    }


def _schema(conn: Any, table_name: str) -> list[dict[str, str]]:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return [{"column_name": str(row[1]), "data_type": str(row[2])} for row in rows]


def _check_no_row_payload(
    payload: Mapping[str, Any], label: str, errors: list[str]
) -> None:
    for key, value in payload.items():
        if str(key) in {
            "rows",
            "row_payload",
            "daily_confirmation_results",
            "confirmed_interval_results",
        } and isinstance(value, list):
            errors.append(f"{label}_contains_row_payload")


def _parse_r0_t06_evidence(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise R0T10ConfirmationIntervalValidationError("r0_t06_evidence_missing")
    text = path.read_text(encoding="utf-8")
    keys = ("nested_daily_state_duckdb_sha256", "R0-T07_allowed_to_start")
    return {key: _evidence_value(text, key) for key in keys}


def _evidence_value(text: str, key: str) -> str:
    match = re.search(rf"`{re.escape(key)}`:\s*`?([^`\n]+)`?", text)
    if not match:
        raise R0T10ConfirmationIntervalValidationError(f"r0_t06_evidence_missing_{key}")
    return match.group(1).strip()


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10ConfirmationIntervalValidationError(f"expected JSON object: {path}")
    return payload


def _row_dict(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {str(column): value for column, value in zip(columns, row, strict=True)}
