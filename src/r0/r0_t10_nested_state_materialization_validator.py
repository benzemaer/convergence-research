from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import LEGACY_V1_FIELD_NAMES
from src.r0.daily_state_engine import DIMENSIONS, Q_VALUES, WEAK_DELTA
from src.r0.percentile_score_engine import ACTIVE_INDICATORS, PERCENTILE_WINDOWS
from src.r0.r0_t10_nested_state_materializer import (
    DIMENSION_STATE_DUCKDB_NAME,
    DIMENSION_STATE_TABLE_NAME,
    INDICATOR_STATE_DUCKDB_NAME,
    INDICATOR_STATE_TABLE_NAME,
    MANIFEST_NAME,
    NESTED_DAILY_DUCKDB_NAME,
    NESTED_DAILY_TABLE_NAME,
    SUMMARY_NAME,
)
from src.r0.r0_t10_score_materializer import DIMENSION_TABLE_NAME
from src.r0.upstream_artifact_io import quote_ident, sha256_file

FORBIDDEN_FIELDS = {
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "future_volatility",
    "breakout_direction",
    "release_direction",
    "return",
    "returns",
    "backtest",
    "portfolio",
    "trade_signal",
    "buy_signal",
    "sell_signal",
    "confirmation",
    "confirmed_state",
    "streak",
    "interval",
    "state_interval",
    "K",
}
EXCLUSIVE_LAYERS = {
    "NONE",
    "P_ONLY",
    "PC_ONLY",
    "PCT_ONLY",
    "PCVT",
    "UNKNOWN",
    "BLOCKED",
    "DIAGNOSTIC_REQUIRED",
}
NESTED_FIELDS = {
    "P_raw",
    "C_raw",
    "T_raw",
    "V_raw",
    "S_P_raw",
    "S_PC_raw",
    "S_PCT_raw",
    "S_PCVT_raw",
    "S_P_validity_status",
    "S_PC_validity_status",
    "S_PCT_validity_status",
    "S_PCVT_validity_status",
    "S_P_reason_codes",
    "S_PC_reason_codes",
    "S_PCT_reason_codes",
    "S_PCVT_reason_codes",
    "exclusive_state_layer",
}


class R0T10NestedStateValidationError(RuntimeError):
    pass


def validate_materialization(
    output_dir: str | Path,
    *,
    r0_t05_evidence: str | Path,
    indicator_score_duckdb: str | Path,
    dimension_score_duckdb: str | Path,
    common_eligible_duckdb: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = root / MANIFEST_NAME
    summary_path = root / SUMMARY_NAME
    manifest = _load_json_object(manifest_path)
    summary = _load_json_object(summary_path)
    evidence = _parse_evidence(Path(r0_t05_evidence))
    errors: list[str] = []

    _validate_input_hashes(
        evidence,
        Path(indicator_score_duckdb),
        Path(dimension_score_duckdb),
        None if common_eligible_duckdb is None else Path(common_eligible_duckdb),
        errors,
    )
    _check_no_row_payload(manifest, "manifest", errors)
    _check_no_row_payload(summary, "summary", errors)
    _validate_output_hashes(root, manifest, errors)
    shard_counts = _validate_shards(manifest, errors)
    stats = {
        "indicator_state": _duckdb_stats(
            root / INDICATOR_STATE_DUCKDB_NAME, INDICATOR_STATE_TABLE_NAME, errors
        ),
        "dimension_state": _duckdb_stats(
            root / DIMENSION_STATE_DUCKDB_NAME, DIMENSION_STATE_TABLE_NAME, errors
        ),
        "nested_daily_state": _duckdb_stats(
            root / NESTED_DAILY_DUCKDB_NAME, NESTED_DAILY_TABLE_NAME, errors
        ),
    }
    _validate_counts(manifest, summary, shard_counts, stats, errors)
    _validate_coverage(stats, errors)
    _validate_semantics(stats, errors)
    _validate_forbidden_and_legacy(stats, errors)
    recompute = _validate_deterministic_nested_recompute(
        root=root,
        dimension_score_duckdb=Path(dimension_score_duckdb),
        errors=errors,
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
            "indicator_state": sha256_file(root / INDICATOR_STATE_DUCKDB_NAME)
            if (root / INDICATOR_STATE_DUCKDB_NAME).exists()
            else None,
            "dimension_state": sha256_file(root / DIMENSION_STATE_DUCKDB_NAME)
            if (root / DIMENSION_STATE_DUCKDB_NAME).exists()
            else None,
            "nested_daily_state": sha256_file(root / NESTED_DAILY_DUCKDB_NAME)
            if (root / NESTED_DAILY_DUCKDB_NAME).exists()
            else None,
        },
        "manifest_counts": {
            "indicator_state": int(manifest.get("indicator_state_row_count", -1)),
            "dimension_state": int(manifest.get("dimension_state_row_count", -1)),
            "nested_daily_state": int(manifest.get("nested_daily_state_row_count", -1)),
        },
        "shard_counts": shard_counts,
        "duckdb_stats": stats,
        "nested_recompute_sample_count": recompute["sample_count"],
        "nested_recompute_mismatch_count": recompute["mismatch_count"],
        "nested_recompute_W_coverage": recompute["W_coverage"],
        "nested_recompute_q_coverage": recompute["q_coverage"],
        "nested_recompute_dimension_coverage": recompute["dimension_coverage"],
        "exclusive_layer_recompute_coverage": recompute["exclusive_layer_coverage"],
        "exclusive_layer_non_none_sample_count": recompute[
            "exclusive_layer_non_none_sample_count"
        ],
        "nested_recompute_check": "passed"
        if recompute["sample_count"] > 0 and recompute["mismatch_count"] == 0
        else "blocked",
        "exclusive_layer_recompute_check": "passed"
        if recompute["sample_count"] > 0
        and recompute["mismatch_count"] == 0
        and "exclusive_layer_recompute_non_none_missing" not in errors
        else "blocked",
        "nested_invariant_check": "passed"
        if not stats["nested_daily_state"].get("nested_invariant_hit_count")
        else "blocked",
        "exclusive_layer_uniqueness_check": "passed"
        if not stats["nested_daily_state"].get("duplicate_key_hit_count")
        else "blocked",
        "state_specific_validity_schema_check": "passed"
        if NESTED_FIELDS.issubset(set(stats["nested_daily_state"].get("columns", ())))
        else "blocked",
        "forbidden_field_check": "passed"
        if not any(item.get("forbidden_field_hit_count") for item in stats.values())
        else "blocked",
        "legacy_v1_check": "passed"
        if not any(item.get("legacy_v1_hit_count") for item in stats.values())
        else "blocked",
        "confirmation_field_absence_check": "passed"
        if not any(item.get("confirmation_field_hit_count") for item in stats.values())
        else "blocked",
        "K_absence_check": "passed"
        if not any(item.get("K_field_hit_count") for item in stats.values())
        else "blocked",
        "R0-T07_allowed_to_start": not errors,
        "errors": errors,
    }
    if errors:
        raise R0T10NestedStateValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def _validate_input_hashes(
    evidence: Mapping[str, Any],
    indicator_path: Path,
    dimension_path: Path,
    common_path: Path | None,
    errors: list[str],
) -> None:
    if evidence.get("R0-T06_allowed_to_start") != "true":
        errors.append("r0_t05_evidence_gate_not_open")
    for key, path, expected in (
        ("indicator", indicator_path, evidence.get("indicator_score_duckdb_sha256")),
        ("dimension", dimension_path, evidence.get("dimension_score_duckdb_sha256")),
        (
            "common_eligible",
            common_path,
            evidence.get("common_eligible_duckdb_sha256"),
        ),
    ):
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"input_{key}_duckdb_missing")
        elif expected and sha256_file(path) != expected:
            errors.append(f"input_{key}_duckdb_hash_mismatch")


def _validate_output_hashes(
    root: Path, manifest: Mapping[str, Any], errors: list[str]
) -> None:
    expected = manifest.get("output_hashes", {})
    if not isinstance(expected, Mapping):
        errors.append("manifest_output_hashes_missing")
        return
    for key, name in {
        "indicator_state": INDICATOR_STATE_DUCKDB_NAME,
        "dimension_state": DIMENSION_STATE_DUCKDB_NAME,
        "nested_daily_state": NESTED_DAILY_DUCKDB_NAME,
    }.items():
        path = root / name
        if not path.exists():
            errors.append(f"duckdb_missing:{key}")
        elif expected.get(key) != sha256_file(path):
            errors.append(f"duckdb_hash_mismatch:{key}")


def _validate_shards(manifest: Mapping[str, Any], errors: list[str]) -> dict[str, int]:
    counts = {"indicator_state": 0, "dimension_state": 0, "nested_daily_state": 0}
    shards = manifest.get("shards")
    if not isinstance(shards, list):
        errors.append("manifest_shards_missing")
        return counts
    for shard in shards:
        if not isinstance(shard, Mapping):
            errors.append("manifest_shard_not_object")
            continue
        done_path = Path(str(shard.get("done_marker_path", "")))
        if not done_path.is_file():
            errors.append(f"done_marker_missing:{shard.get('chunk_id')}")
        else:
            done = _load_json_object(done_path)
            if done.get("chunk_hash") != shard.get("chunk_hash"):
                errors.append(
                    f"done_marker_chunk_hash_mismatch:{shard.get('chunk_id')}"
                )
        for section in ("indicator_state", "dimension_state", "nested_daily_state"):
            payload = shard.get(section)
            if not isinstance(payload, Mapping):
                errors.append(f"shard_section_missing:{section}")
                continue
            path = Path(str(payload.get("path", "")))
            if not path.exists():
                errors.append(f"shard_missing:{section}:{path}")
                continue
            if payload.get("file_sha256") != sha256_file(path):
                errors.append(f"shard_file_hash_mismatch:{path.name}")
            actual_rows = _parquet_count(path)
            if actual_rows != int(payload.get("row_count", -1)):
                errors.append(f"shard_row_count_mismatch:{path.name}")
            counts[section] += actual_rows
    return counts


def _duckdb_stats(path: Path, table_name: str, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"table_exists": False}
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        exists = (
            conn.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table_name],
            ).fetchone()[0]
            == 1
        )
        if not exists:
            errors.append(f"duckdb_table_missing:{table_name}")
            return {"table_exists": False}
        quoted = '"' + table_name.replace('"', '""') + '"'
        columns = [
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        ]
        row_count = int(conn.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])
        security_count = int(
            conn.execute(
                f"SELECT count(DISTINCT security_id) FROM {quoted}"
            ).fetchone()[0]
        )
        date_min, date_max = conn.execute(
            f"SELECT min(trading_date), max(trading_date) FROM {quoted}"
        ).fetchone()
        stats: dict[str, Any] = {
            "table_exists": True,
            "columns": columns,
            "row_count": row_count,
            "security_count": security_count,
            "date_min": None if date_min is None else str(date_min),
            "date_max": None if date_max is None else str(date_max),
            "forbidden_field_hit_count": len(
                [column for column in columns if column in FORBIDDEN_FIELDS]
            ),
            "confirmation_field_hit_count": len(
                [
                    column
                    for column in columns
                    if column
                    in {"confirmation", "confirmed_state", "streak", "interval"}
                ]
            ),
            "K_field_hit_count": len([column for column in columns if column == "K"]),
            "legacy_v1_hit_count": len(
                [column for column in columns if column in LEGACY_V1_FIELD_NAMES]
            ),
            "legacy_volume_name_hit_count": len(
                [column for column in columns if column == "V1_VolShrink20_60"]
            ),
        }
        if "percentile_window_W" in columns:
            stats["W_coverage"] = [
                int(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT percentile_window_W FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "q" in columns:
            stats["q_coverage"] = [
                round(float(row[0]), 2)
                for row in conn.execute(
                    f"SELECT DISTINCT q FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "weak_delta" in columns:
            stats["weak_delta_coverage"] = [
                round(float(row[0]), 2)
                for row in conn.execute(
                    f"SELECT DISTINCT weak_delta FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "indicator_id" in columns:
            stats["indicator_coverage"] = [
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT indicator_id FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "dimension" in columns:
            stats["dimension_coverage"] = [
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT dimension FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "exclusive_state_layer" in columns:
            stats.update(_nested_stats(conn, quoted))
        if "dimension_active_weak" in columns:
            stats.update(_dimension_rule_stats(conn, quoted))
        if "indicator_active" in columns:
            stats.update(_indicator_rule_stats(conn, quoted))
        return stats
    finally:
        conn.close()


def _nested_stats(conn: Any, quoted: str) -> dict[str, Any]:
    return {
        "exclusive_layers": [
            str(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT exclusive_state_layer FROM {quoted} ORDER BY 1"
            ).fetchall()
        ],
        "duplicate_key_hit_count": int(
            conn.execute(
                f"""
                SELECT count(*)
                FROM (
                  SELECT security_id, trading_date, percentile_window_W, q, count(*) c
                  FROM {quoted}
                  GROUP BY 1,2,3,4
                  HAVING c > 1
                )
                """
            ).fetchone()[0]
        ),
        "nested_invariant_hit_count": int(
            conn.execute(
                f"""
                SELECT count(*)
                FROM {quoted}
                WHERE (S_PCVT_raw = true AND S_PCT_raw IS DISTINCT FROM true)
                   OR (S_PCT_raw = true AND S_PC_raw IS DISTINCT FROM true)
                   OR (S_PC_raw = true AND S_P_raw IS DISTINCT FROM true)
                   OR (P_raw = false AND (
                        S_PC_raw = true OR S_PCT_raw = true OR S_PCVT_raw = true
                   ))
                   OR (S_PCVT_raw = true AND (
                        P_raw IS DISTINCT FROM true
                        OR C_raw IS DISTINCT FROM true
                        OR T_raw IS DISTINCT FROM true
                        OR V_raw IS DISTINCT FROM true
                   ))
                """
            ).fetchone()[0]
        ),
        "bad_exclusive_layer_hit_count": int(
            conn.execute(
                f"""
                SELECT count(*)
                FROM {quoted}
                WHERE exclusive_state_layer NOT IN {tuple(sorted(EXCLUSIVE_LAYERS))}
                """
            ).fetchone()[0]
        ),
    }


def _dimension_rule_stats(conn: Any, quoted: str) -> dict[str, Any]:
    return {
        "dimension_rule_mismatch_count": int(
            conn.execute(
                f"""
                SELECT count(*)
                FROM {quoted}
                WHERE eligible_dimension = true
                  AND validity_status = 'valid'
                  AND score_dimension IS NOT NULL
                  AND score_dimension_min IS NOT NULL
                  AND dimension_active_weak IS DISTINCT FROM (
                    score_dimension + 1e-12 >= 1.0 - q
                    AND score_dimension_min + 1e-12 >= 1.0 - q - weak_delta
                  )
                """
            ).fetchone()[0]
        )
    }


def _indicator_rule_stats(conn: Any, quoted: str) -> dict[str, Any]:
    return {
        "indicator_rule_mismatch_count": int(
            conn.execute(
                f"""
                SELECT count(*)
                FROM {quoted}
                WHERE eligible = true
                  AND validity_status = 'valid'
                  AND score IS NOT NULL
                  AND indicator_active IS DISTINCT FROM (score + 1e-12 >= 1.0 - q)
                """
            ).fetchone()[0]
        )
    }


def _validate_counts(
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    shard_counts: Mapping[str, int],
    stats: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    expected = {
        "indicator_state": int(manifest.get("indicator_state_row_count", -1)),
        "dimension_state": int(manifest.get("dimension_state_row_count", -1)),
        "nested_daily_state": int(manifest.get("nested_daily_state_row_count", -1)),
    }
    for key, expected_count in expected.items():
        if shard_counts.get(key) != expected_count:
            errors.append(f"shard_count_mismatch:{key}")
        if int(stats[key].get("row_count", -2)) != expected_count:
            errors.append(f"duckdb_count_mismatch:{key}")
    if summary.get("status") != "completed":
        errors.append("summary_status_not_completed")
    if summary.get("downstream_gate_allowed") is not True:
        errors.append("summary_downstream_gate_not_open")


def _validate_coverage(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    for key in ("indicator_state", "dimension_state", "nested_daily_state"):
        if set(stats[key].get("W_coverage", ())) != set(PERCENTILE_WINDOWS):
            errors.append(f"W_coverage_mismatch:{key}")
        if set(stats[key].get("q_coverage", ())) != {round(q, 2) for q in Q_VALUES}:
            errors.append(f"q_coverage_mismatch:{key}")
    if set(stats["dimension_state"].get("weak_delta_coverage", ())) != {
        round(WEAK_DELTA, 2)
    }:
        errors.append("weak_delta_coverage_mismatch")
    if set(stats["indicator_state"].get("indicator_coverage", ())) != set(
        ACTIVE_INDICATORS
    ):
        errors.append("indicator_coverage_mismatch")
    if set(stats["dimension_state"].get("dimension_coverage", ())) != set(DIMENSIONS):
        errors.append("dimension_coverage_mismatch")
    nested_columns = set(stats["nested_daily_state"].get("columns", ()))
    if not NESTED_FIELDS.issubset(nested_columns):
        errors.append("nested_state_fields_missing")


def _validate_semantics(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    if int(stats["indicator_state"].get("indicator_rule_mismatch_count", 0)):
        errors.append("indicator_active_rule_mismatch")
    if int(stats["dimension_state"].get("dimension_rule_mismatch_count", 0)):
        errors.append("dimension_weak_rule_mismatch")
    nested = stats["nested_daily_state"]
    if int(nested.get("nested_invariant_hit_count", 0)):
        errors.append("nested_invariant_mismatch")
    if int(nested.get("duplicate_key_hit_count", 0)):
        errors.append("nested_duplicate_key")
    if int(nested.get("bad_exclusive_layer_hit_count", 0)):
        errors.append("bad_exclusive_state_layer")


def _validate_forbidden_and_legacy(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    for key, item in stats.items():
        if int(item.get("forbidden_field_hit_count", 0)):
            errors.append(f"forbidden_field_check_failed:{key}")
        if int(item.get("legacy_v1_hit_count", 0)):
            errors.append(f"legacy_v1_check_failed:{key}")
        if int(item.get("legacy_volume_name_hit_count", 0)):
            errors.append(f"legacy_volume_name_check_failed:{key}")


def _validate_deterministic_nested_recompute(
    *, root: Path, dimension_score_duckdb: Path, errors: list[str]
) -> dict[str, Any]:
    import duckdb  # noqa: PLC0415

    result = {
        "sample_count": 0,
        "mismatch_count": 0,
        "W_coverage": set(),
        "q_coverage": set(),
        "dimension_coverage": set(),
        "exclusive_layer_coverage": set(),
        "exclusive_layer_non_none_sample_count": 0,
        "skipped_reasons": {},
    }
    nested_path = root / NESTED_DAILY_DUCKDB_NAME
    if not nested_path.is_file() or not dimension_score_duckdb.is_file():
        errors.append("nested_recompute_input_missing")
        return _finalize_recompute(result)
    nested_conn = duckdb.connect(str(nested_path), read_only=True)
    dimension_conn = duckdb.connect(str(dimension_score_duckdb), read_only=True)
    try:
        population = _exclusive_layer_population(nested_conn)
        samples = _select_nested_recompute_samples(nested_conn)
        if not samples:
            errors.append("nested_recompute_samples_missing")
            if population["non_none_count"] > 0:
                errors.append("exclusive_layer_recompute_non_none_missing")
            else:
                _record_skip(result, "exclusive_layer_non_none_absent")
            return _finalize_recompute(result)
        for row in samples:
            sample = {
                "security_id": str(row[0]),
                "trading_date": str(row[1]),
                "W": int(row[2]),
                "q": round(float(row[3]), 2),
                "P_raw": row[4],
                "C_raw": row[5],
                "T_raw": row[6],
                "V_raw": row[7],
                "S_P_raw": row[8],
                "S_PC_raw": row[9],
                "S_PCT_raw": row[10],
                "S_PCVT_raw": row[11],
                "exclusive_state_layer": str(row[12]),
            }
            expected = _recompute_nested_sample(dimension_conn, sample)
            if expected is None:
                _record_skip(result, "dimension_rows_missing")
                continue
            result["sample_count"] += 1
            result["W_coverage"].add(sample["W"])
            result["q_coverage"].add(sample["q"])
            result["dimension_coverage"].update(expected["dimension_coverage"])
            result["exclusive_layer_coverage"].add(sample["exclusive_state_layer"])
            if sample["exclusive_state_layer"] != "NONE":
                result["exclusive_layer_non_none_sample_count"] += 1
            if any(sample[key] != expected[key] for key in expected["compare_keys"]):
                result["mismatch_count"] += 1
        if result["sample_count"] == 0:
            errors.append("nested_recompute_no_samples")
        if result["W_coverage"] != set(PERCENTILE_WINDOWS):
            errors.append("nested_recompute_W_coverage_mismatch")
        if result["q_coverage"] != {round(q, 2) for q in Q_VALUES}:
            errors.append("nested_recompute_q_coverage_mismatch")
        if result["dimension_coverage"] != set(DIMENSIONS):
            errors.append("nested_recompute_dimension_coverage_mismatch")
        if population["non_none_count"] > 0:
            if result["exclusive_layer_non_none_sample_count"] == 0:
                errors.append("exclusive_layer_recompute_non_none_missing")
        else:
            _record_skip(result, "exclusive_layer_non_none_absent")
        if result["mismatch_count"]:
            errors.append(f"nested_recompute_mismatch:{result['mismatch_count']}")
    finally:
        nested_conn.close()
        dimension_conn.close()
    return _finalize_recompute(result)


def _exclusive_layer_population(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        f"""
        SELECT exclusive_state_layer, count(*)
        FROM {quote_ident(NESTED_DAILY_TABLE_NAME)}
        GROUP BY 1
        """
    ).fetchall()
    return {
        "layers": {str(layer): int(count) for layer, count in rows},
        "non_none_count": sum(
            int(count) for layer, count in rows if str(layer) != "NONE"
        ),
    }


def _select_nested_recompute_samples(conn: Any) -> list[tuple[Any, ...]]:
    seen_keys: set[tuple[str, str, int, float]] = set()
    samples: list[tuple[Any, ...]] = []
    for window in PERCENTILE_WINDOWS:
        for q_value in Q_VALUES:
            row = _fetch_nested_sample(conn, where_clause="", params=[window, q_value])
            if row is not None:
                key = (str(row[0]), str(row[1]), int(row[2]), round(float(row[3]), 2))
                if key not in seen_keys:
                    seen_keys.add(key)
                    samples.append(row)
    for layer_clause in (
        "AND exclusive_state_layer = 'NONE'",
        "AND exclusive_state_layer <> 'NONE'",
    ):
        row = _fetch_nested_sample(conn, where_clause=layer_clause, params=[])
        if row is not None:
            key = (str(row[0]), str(row[1]), int(row[2]), round(float(row[3]), 2))
            if key not in seen_keys:
                seen_keys.add(key)
                samples.append(row)
    return samples


def _fetch_nested_sample(
    conn: Any, *, where_clause: str, params: list[Any]
) -> tuple[Any, ...] | None:
    if params:
        predicate = """
        WHERE percentile_window_W = ?
          AND abs(q - ?) < 0.000000001
        """
    else:
        predicate = "WHERE true"
    rows = conn.execute(
        f"""
        SELECT security_id, trading_date, percentile_window_W, q,
               P_raw, C_raw, T_raw, V_raw,
               S_P_raw, S_PC_raw, S_PCT_raw, S_PCVT_raw,
               exclusive_state_layer
        FROM {quote_ident(NESTED_DAILY_TABLE_NAME)}
        {predicate}
        {where_clause}
        ORDER BY security_id, trading_date, percentile_window_W, q
        LIMIT 1
        """,
        params,
    ).fetchall()
    return rows[0] if rows else None


def _recompute_nested_sample(
    conn: Any, sample: Mapping[str, Any]
) -> dict[str, Any] | None:
    rows = conn.execute(
        f"""
        SELECT dimension, score_dimension, score_dimension_min, eligible_dimension,
               validity_status
        FROM {quote_ident(DIMENSION_TABLE_NAME)}
        WHERE security_id = ?
          AND trading_date = ?
          AND percentile_window_W = ?
        """,
        [sample["security_id"], sample["trading_date"], sample["W"]],
    ).fetchall()
    if not rows:
        return None
    raw: dict[str, bool | None] = {}
    statuses: dict[str, str] = {}
    for dimension, score, score_min, eligible, status in rows:
        dimension_key = str(dimension)
        statuses[dimension_key] = str(status)
        raw[dimension_key] = _dimension_active(
            score_dimension=score,
            score_dimension_min=score_min,
            eligible=eligible is True,
            status=str(status),
            q=float(sample["q"]),
        )
    for dimension in DIMENSIONS:
        raw.setdefault(dimension, None)
        statuses.setdefault(dimension, "unknown")
    s_p = raw["P"]
    s_pc = _chain_and(s_p, raw["C"])
    s_pct = _chain_and(s_pc, raw["T"])
    s_pcvt = _chain_and(s_pct, raw["V"])
    return {
        "P_raw": raw["P"],
        "C_raw": raw["C"],
        "T_raw": raw["T"],
        "V_raw": raw["V"],
        "S_P_raw": s_p,
        "S_PC_raw": s_pc,
        "S_PCT_raw": s_pct,
        "S_PCVT_raw": s_pcvt,
        "exclusive_state_layer": _exclusive_layer(raw, statuses),
        "dimension_coverage": set(rows_item[0] for rows_item in rows),
        "compare_keys": (
            "P_raw",
            "C_raw",
            "T_raw",
            "V_raw",
            "S_P_raw",
            "S_PC_raw",
            "S_PCT_raw",
            "S_PCVT_raw",
            "exclusive_state_layer",
        ),
    }


def _dimension_active(
    *,
    score_dimension: Any,
    score_dimension_min: Any,
    eligible: bool,
    status: str,
    q: float,
) -> bool | None:
    if (
        not eligible
        or status != "valid"
        or score_dimension is None
        or score_dimension_min is None
    ):
        return None
    return bool(
        float(score_dimension) + 1e-12 >= 1.0 - q
        and float(score_dimension_min) + 1e-12 >= 1.0 - q - WEAK_DELTA
    )


def _chain_and(left: bool | None, right: bool | None) -> bool | None:
    if left is False:
        return False
    if left is None:
        return None
    return right


def _exclusive_layer(
    raw: Mapping[str, bool | None], statuses: Mapping[str, str]
) -> str:
    if raw["P"] is None:
        return _state_status_layer(statuses["P"])
    if raw["P"] is False:
        return "NONE"
    if raw["C"] is None:
        return _state_status_layer(statuses["C"])
    if raw["C"] is False:
        return "P_ONLY"
    if raw["T"] is None:
        return _state_status_layer(statuses["T"])
    if raw["T"] is False:
        return "PC_ONLY"
    if raw["V"] is None:
        return _state_status_layer(statuses["V"])
    if raw["V"] is False:
        return "PCT_ONLY"
    return "PCVT"


def _state_status_layer(status: str) -> str:
    normalized = status.upper()
    if normalized in {"BLOCKED", "DIAGNOSTIC_REQUIRED"}:
        return normalized
    return "UNKNOWN"


def _parse_evidence(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise R0T10NestedStateValidationError("r0_t05_evidence_missing")
    text = path.read_text(encoding="utf-8")
    keys = (
        "indicator_score_duckdb_sha256",
        "dimension_score_duckdb_sha256",
        "common_eligible_duckdb_sha256",
        "R0-T06_allowed_to_start",
    )
    return {key: _evidence_value(text, key) for key in keys}


def _evidence_value(text: str, key: str) -> str:
    match = re.search(rf"`{re.escape(key)}`:\s*`?([^`\n]+)`?", text)
    if not match:
        raise R0T10NestedStateValidationError(f"r0_t05_evidence_missing_{key}")
    return match.group(1).strip()


def _parquet_count(path: Path) -> int:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect()
    try:
        return int(
            conn.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(path)]
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _check_no_row_payload(payload: Any, label: str, errors: list[str]) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in {
                "rows",
                "indicator_state_results",
                "dimension_state_results",
                "nested_daily_state_results",
            } and isinstance(value, list):
                errors.append(f"{label}_contains_row_payload:{key}")
            _check_no_row_payload(value, label, errors)
    elif isinstance(payload, list):
        for value in payload:
            _check_no_row_payload(value, label, errors)


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10NestedStateValidationError(f"expected JSON object: {path}")
    return payload


def _record_skip(result: dict[str, Any], reason: str) -> None:
    skipped = result["skipped_reasons"]
    skipped[reason] = int(skipped.get(reason, 0)) + 1


def _finalize_recompute(result: dict[str, Any]) -> dict[str, Any]:
    result["W_coverage"] = sorted(result["W_coverage"])
    result["q_coverage"] = sorted(result["q_coverage"])
    result["dimension_coverage"] = sorted(result["dimension_coverage"])
    result["exclusive_layer_coverage"] = sorted(result["exclusive_layer_coverage"])
    return result
