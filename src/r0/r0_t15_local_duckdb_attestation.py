# ruff: noqa: E501
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import (
    DAILY_DB,
    DAILY_TABLE,
    DIMENSION_DB,
    DIMENSION_TABLE,
    INTERVAL_DB,
    INTERVAL_TABLE,
    NESTED_DB,
    NESTED_TABLE,
    ROOT,
    TASK_ID,
    git_commit,
)

OUTPUTS = {
    "dimension_state": (DIMENSION_DB, DIMENSION_TABLE),
    "nested_daily_state": (NESTED_DB, NESTED_TABLE),
    "daily_confirmation": (DAILY_DB, DAILY_TABLE),
    "confirmed_interval": (INTERVAL_DB, INTERVAL_TABLE),
}

PRIMARY_KEYS = {
    "dimension_state": "formal_vector_id,security_id,trading_date,dimension",
    "nested_daily_state": "formal_vector_id,security_id,trading_date",
    "daily_confirmation": ("formal_vector_id,security_id,trading_date,state_name"),
    "confirmed_interval": "interval_id",
}


def build_r0_t15_local_duckdb_attestation(
    *,
    run_dir: str | Path,
    output_path: str | Path | None = None,
    revision_code_commit: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest = _load_json(run_dir / "r0_t15_artifact_manifest.json")
    import duckdb  # noqa: PLC0415

    outputs: dict[str, dict[str, Any]] = {}
    for key, (filename, table) in OUTPUTS.items():
        path = run_dir / filename
        record = manifest.get("outputs", {}).get(key, {})
        actual_sha256 = sha256_file(path)
        con = duckdb.connect(str(path), read_only=True)
        try:
            row_count, vector_count, security_count = con.execute(
                f"SELECT count(*),count(DISTINCT formal_vector_id),"
                f"count(DISTINCT security_id) FROM {table}"
            ).fetchone()
            duplicate_count = con.execute(
                f"SELECT count(*)-count(DISTINCT ({PRIMARY_KEYS[key]})) FROM {table}"
            ).fetchone()[0]
            schema = [
                {"column_name": str(row[1]), "data_type": str(row[2])}
                for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
            ]
        finally:
            con.close()
        outputs[key] = {
            "path": _rel(path),
            "table": table,
            "file_size_bytes": path.stat().st_size,
            "expected_sha256": record.get("sha256"),
            "actual_sha256": actual_sha256,
            "expected_row_count": int(record.get("row_count", -1)),
            "actual_row_count": int(row_count),
            "expected_vector_count": int(record.get("vector_count", -1)),
            "actual_vector_count": int(vector_count),
            "expected_security_count": int(record.get("security_count", -1)),
            "actual_security_count": int(security_count),
            "primary_key_duplicate_count": int(duplicate_count),
            "schema": schema,
        }

    nested_path = run_dir / NESTED_DB
    nested_con = duckdb.connect(str(nested_path), read_only=True)
    try:
        raw_parent_child = nested_con.execute(
            f"""
            SELECT
              sum(CASE WHEN S_PC_raw AND NOT coalesce(S_P_raw,false) THEN 1 ELSE 0 END),
              sum(CASE WHEN S_PCT_raw AND NOT coalesce(S_PC_raw,false) THEN 1 ELSE 0 END),
              sum(CASE WHEN S_PCVT_raw AND NOT coalesce(S_PCT_raw,false) THEN 1 ELSE 0 END)
            FROM {NESTED_TABLE}
            """
        ).fetchone()
    finally:
        nested_con.close()

    daily_path = run_dir / DAILY_DB
    daily_con = duckdb.connect(str(daily_path), read_only=True)
    try:
        confirmed_parent_child = daily_con.execute(
            f"""
            WITH states AS (
              SELECT formal_vector_id,security_id,trading_date,
                bool_or(confirmed_state) FILTER (WHERE state_name='S_P') AS s_p,
                bool_or(confirmed_state) FILTER (WHERE state_name='S_PC') AS s_pc,
                bool_or(confirmed_state) FILTER (WHERE state_name='S_PCT') AS s_pct,
                bool_or(confirmed_state) FILTER (WHERE state_name='S_PCVT') AS s_pcvt
              FROM {DAILY_TABLE}
              GROUP BY formal_vector_id,security_id,trading_date
            )
            SELECT
              sum(CASE WHEN s_pc AND NOT coalesce(s_p,false) THEN 1 ELSE 0 END),
              sum(CASE WHEN s_pct AND NOT coalesce(s_pc,false) THEN 1 ELSE 0 END),
              sum(CASE WHEN s_pcvt AND NOT coalesce(s_pct,false) THEN 1 ELSE 0 END)
            FROM states
            """
        ).fetchone()
    finally:
        daily_con.close()

    cross = duckdb.connect()
    try:
        cross.execute(f"ATTACH '{daily_path.as_posix()}' AS dailydb (READ_ONLY)")
        interval_path = run_dir / INTERVAL_DB
        cross.execute(f"ATTACH '{interval_path.as_posix()}' AS intervaldb (READ_ONLY)")
        duration_mismatches = cross.execute(
            f"""
            WITH daily AS (
              SELECT formal_vector_id,state_name,
                sum(CASE WHEN confirmed_state THEN 1 ELSE 0 END) AS confirmed_days
              FROM dailydb.{DAILY_TABLE}
              GROUP BY formal_vector_id,state_name
            ), intervals AS (
              SELECT formal_vector_id,state_name,
                sum(confirmed_duration_observations) AS interval_days
              FROM intervaldb.{INTERVAL_TABLE}
              GROUP BY formal_vector_id,state_name
            )
            SELECT count(*)
            FROM daily FULL OUTER JOIN intervals USING(formal_vector_id,state_name)
            WHERE coalesce(confirmed_days,0) <> coalesce(interval_days,0)
            """
        ).fetchone()[0]
    finally:
        cross.close()

    raw_counts = {
        "S_PC_without_S_P": int(raw_parent_child[0] or 0),
        "S_PCT_without_S_PC": int(raw_parent_child[1] or 0),
        "S_PCVT_without_S_PCT": int(raw_parent_child[2] or 0),
    }
    confirmed_counts = {
        "S_PC_without_S_P": int(confirmed_parent_child[0] or 0),
        "S_PCT_without_S_PC": int(confirmed_parent_child[1] or 0),
        "S_PCVT_without_S_PCT": int(confirmed_parent_child[2] or 0),
    }
    checks = {
        "all_output_hashes_match_manifest": all(
            item["actual_sha256"] == item["expected_sha256"]
            for item in outputs.values()
        ),
        "all_output_row_counts_match_manifest": all(
            item["actual_row_count"] == item["expected_row_count"]
            for item in outputs.values()
        ),
        "all_output_vector_counts_match_manifest": all(
            item["actual_vector_count"] == item["expected_vector_count"] == 8
            for item in outputs.values()
        ),
        "all_output_security_counts_match_manifest": all(
            item["actual_security_count"] == item["expected_security_count"]
            for item in outputs.values()
        ),
        "all_primary_keys_unique": all(
            item["primary_key_duplicate_count"] == 0 for item in outputs.values()
        ),
        "raw_parent_child_invariant": sum(raw_counts.values()) == 0,
        "confirmed_parent_child_invariant": sum(confirmed_counts.values()) == 0,
        "confirmation_interval_duration_conservation": int(duration_mismatches) == 0,
    }
    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "attestation_schema_version": "r0_t15_local_duckdb_attestation.v1",
        "task_id": TASK_ID,
        "run_id": manifest.get("run_id"),
        "source_execution_code_commit": manifest.get("code_commit"),
        "validator_code_commit": revision_code_commit or git_commit(),
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "validation_scope": "canonical_local_outputs",
        "local_duckdb_byte_access": True,
        "delivery_status": "local_only_not_committed_or_uploaded",
        "external_direct_duckdb_byte_review_performed": False,
        "independent_byte_validation_status": "not_performed",
        "claim_boundary": (
            "implementation-side fresh reread of local DuckDB bytes; external review "
            "may inspect only committed manifests, code, reconciliation, and this attestation"
        ),
        "outputs": outputs,
        "raw_parent_child_violation_counts": raw_counts,
        "confirmed_parent_child_violation_counts": confirmed_counts,
        "confirmation_interval_duration_mismatch_count": int(duration_mismatches),
        "checks": checks,
        "failures": failures,
        "status": "passed" if not failures else "failed",
    }
    if output_path is not None:
        write_json_atomic(output_path, result)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
