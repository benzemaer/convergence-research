from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r0.candidate_artifact_engine import LEGACY_V1_FIELD_NAMES  # noqa: E402
from src.r0.percentile_score_engine import (  # noqa: E402
    ACTIVE_INDICATORS,
    DIMENSION_COMPONENTS,
    PERCENTILE_WINDOWS,
)
from src.r0.r0_t10_score_materializer import (  # noqa: E402
    COMMON_DUCKDB_NAME,
    COMMON_TABLE_NAME,
    DIMENSION_DUCKDB_NAME,
    DIMENSION_TABLE_NAME,
    INDICATOR_DUCKDB_NAME,
    INDICATOR_TABLE_NAME,
    MANIFEST_NAME,
    SUMMARY_NAME,
)
from src.r0.upstream_artifact_io import sha256_file  # noqa: E402

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
}


class R0T10ScoreValidationError(RuntimeError):
    pass


def validate_materialization(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = root / MANIFEST_NAME
    summary_path = root / SUMMARY_NAME
    manifest = _load_json_object(manifest_path)
    summary = _load_json_object(summary_path)
    errors: list[str] = []
    _check_no_row_payload(manifest, "manifest", errors)
    _check_no_row_payload(summary, "summary", errors)
    _validate_manifest_hashes(root, manifest, errors)
    shard_counts = _validate_shards(manifest, errors)
    stats = {
        "indicator": _duckdb_stats(
            root / INDICATOR_DUCKDB_NAME, INDICATOR_TABLE_NAME, errors
        ),
        "dimension": _duckdb_stats(
            root / DIMENSION_DUCKDB_NAME, DIMENSION_TABLE_NAME, errors
        ),
        "common_eligible": _duckdb_stats(
            root / COMMON_DUCKDB_NAME, COMMON_TABLE_NAME, errors
        ),
    }
    _validate_counts(manifest, summary, shard_counts, stats, errors)
    _validate_coverage(stats, errors)
    _validate_strict_past(stats["indicator"], errors)
    _validate_forbidden_and_legacy(stats, errors)
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
            "indicator": sha256_file(root / INDICATOR_DUCKDB_NAME)
            if (root / INDICATOR_DUCKDB_NAME).exists()
            else None,
            "dimension": sha256_file(root / DIMENSION_DUCKDB_NAME)
            if (root / DIMENSION_DUCKDB_NAME).exists()
            else None,
            "common_eligible": sha256_file(root / COMMON_DUCKDB_NAME)
            if (root / COMMON_DUCKDB_NAME).exists()
            else None,
        },
        "manifest_counts": {
            "indicator": int(manifest.get("indicator_score_row_count", -1)),
            "dimension": int(manifest.get("dimension_score_row_count", -1)),
            "common_eligible": int(manifest.get("common_eligible_row_count", -1)),
        },
        "shard_counts": shard_counts,
        "duckdb_stats": stats,
        "strict_past_validator_status": "passed" if not errors else "failed",
        "current_value_in_reference_set_check": "passed"
        if not stats["indicator"].get("current_value_hit_count")
        else "blocked",
        "future_leakage_check": "passed"
        if not stats["indicator"].get("future_leakage_hit_count")
        else "blocked",
        "midrank_tie_check": "passed"
        if not stats["indicator"].get("midrank_mismatch_count")
        else "blocked",
        "amount_level_repeated_percentile_check": "passed"
        if not stats["indicator"].get("amount_level_repeated_hit_count")
        else "blocked",
        "forbidden_field_check": "passed"
        if not any(item.get("forbidden_field_hit_count") for item in stats.values())
        else "blocked",
        "legacy_v1_check": "passed"
        if not any(item.get("legacy_v1_hit_count") for item in stats.values())
        else "blocked",
        "errors": errors,
    }
    if errors:
        raise R0T10ScoreValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def _validate_manifest_hashes(
    root: Path, manifest: Mapping[str, Any], errors: list[str]
) -> None:
    expected = manifest.get("output_hashes", {})
    if not isinstance(expected, Mapping):
        errors.append("manifest_output_hashes_missing")
        return
    for key, name in {
        "indicator": INDICATOR_DUCKDB_NAME,
        "dimension": DIMENSION_DUCKDB_NAME,
        "common_eligible": COMMON_DUCKDB_NAME,
    }.items():
        path = root / name
        if not path.exists():
            errors.append(f"duckdb_missing:{key}")
        elif expected.get(key) != sha256_file(path):
            errors.append(f"duckdb_hash_mismatch:{key}")


def _validate_shards(manifest: Mapping[str, Any], errors: list[str]) -> dict[str, int]:
    shards = manifest.get("shards")
    counts = {"indicator": 0, "dimension": 0, "common_eligible": 0}
    if not isinstance(shards, list):
        errors.append("manifest_shards_missing")
        return counts
    for shard in shards:
        if not isinstance(shard, Mapping):
            errors.append("manifest_shard_not_object")
            continue
        done_marker_path = shard.get("done_marker_path")
        if not done_marker_path:
            errors.append(f"done_marker_path_missing:{shard.get('chunk_id')}")
        else:
            done_path = Path(str(done_marker_path))
            if not done_path.is_file():
                errors.append(f"done_marker_missing:{shard.get('chunk_id')}")
                done_path = None
        if done_marker_path and done_path is not None:
            done = _load_json_object(done_path)
            if done.get("chunk_hash") != shard.get("chunk_hash"):
                errors.append(
                    f"done_marker_chunk_hash_mismatch:{shard.get('chunk_id')}"
                )
        for manifest_key, count_key in (
            ("indicator_score", "indicator"),
            ("dimension_score", "dimension"),
            ("common_eligible", "common_eligible"),
        ):
            section = shard.get(manifest_key)
            if not isinstance(section, Mapping):
                errors.append(f"shard_section_missing:{manifest_key}")
                continue
            path = Path(str(section.get("path", "")))
            if not path.exists():
                errors.append(f"shard_missing:{path}")
                continue
            if section.get("file_sha256") != sha256_file(path):
                errors.append(f"shard_file_hash_mismatch:{path.name}")
            actual_rows = _count_jsonl_gz_rows(path)
            if actual_rows != int(section.get("row_count", -1)):
                errors.append(f"shard_row_count_mismatch:{path.name}")
            counts[count_key] += actual_rows
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
        stats = {
            "table_exists": True,
            "columns": columns,
            "row_count": row_count,
            "security_count": security_count,
            "date_min": None if date_min is None else str(date_min),
            "date_max": None if date_max is None else str(date_max),
            "forbidden_field_hit_count": len(
                [column for column in columns if column.lower() in FORBIDDEN_FIELDS]
            ),
            "legacy_v1_hit_count": len(
                [column for column in columns if column in LEGACY_V1_FIELD_NAMES]
            ),
        }
        if "percentile_window_W" in columns:
            stats["W_coverage"] = [
                int(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT percentile_window_W FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        if "indicator_id" in columns:
            stats["indicator_coverage"] = [
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT indicator_id FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
            stats.update(_indicator_strict_past_stats(conn, quoted))
        if "dimension" in columns:
            stats["dimension_coverage"] = [
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT dimension FROM {quoted} ORDER BY 1"
                ).fetchall()
            ]
        return stats
    finally:
        conn.close()


def _indicator_strict_past_stats(conn: Any, quoted: str) -> dict[str, Any]:
    current_hit = int(
        conn.execute(
            f"SELECT count(*) FROM {quoted} WHERE current_value_in_reference_set = true"
        ).fetchone()[0]
    )
    future_hit = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {quoted}
            WHERE reference_window_end IS NOT NULL
              AND reference_window_end >= trading_date
            """
        ).fetchone()[0]
    )
    eligible_bad_count = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {quoted}
            WHERE eligible = true AND reference_observation_count != percentile_window_W
            """
        ).fetchone()[0]
    )
    insufficient_bad_count = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {quoted}
            WHERE eligible = false
              AND list_contains(reason_codes, 'insufficient_strict_past_history')
              AND reference_observation_count >= percentile_window_W
            """
        ).fetchone()[0]
    )
    amount_repeated = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {quoted}
            WHERE indicator_id = 'V2_AmountLevel20Pct'
              AND list_contains(
                reason_codes,
                'amount_level_repeated_percentile_forbidden'
              )
            """
        ).fetchone()[0]
    )
    midrank_mismatch = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {quoted}
            WHERE eligible = true
              AND (tie_method IS NULL OR tie_method != 'midrank')
            """
        ).fetchone()[0]
    )
    return {
        "current_value_hit_count": current_hit,
        "future_leakage_hit_count": future_hit,
        "eligible_reference_count_mismatch_count": eligible_bad_count,
        "insufficient_history_reference_count_mismatch_count": insufficient_bad_count,
        "amount_level_repeated_hit_count": amount_repeated,
        "midrank_mismatch_count": midrank_mismatch,
    }


def _validate_counts(
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    shard_counts: Mapping[str, int],
    stats: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    expected = {
        "indicator": int(manifest.get("indicator_score_row_count", -1)),
        "dimension": int(manifest.get("dimension_score_row_count", -1)),
        "common_eligible": int(manifest.get("common_eligible_row_count", -1)),
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
    if set(stats["indicator"].get("W_coverage", ())) != set(PERCENTILE_WINDOWS):
        errors.append("indicator_W_coverage_mismatch")
    if set(stats["dimension"].get("W_coverage", ())) != set(PERCENTILE_WINDOWS):
        errors.append("dimension_W_coverage_mismatch")
    if set(stats["indicator"].get("indicator_coverage", ())) != set(ACTIVE_INDICATORS):
        errors.append("indicator_coverage_mismatch")
    if set(stats["dimension"].get("dimension_coverage", ())) != set(
        DIMENSION_COMPONENTS
    ):
        errors.append("dimension_coverage_mismatch")


def _validate_strict_past(stats: Mapping[str, Any], errors: list[str]) -> None:
    for key in (
        "current_value_hit_count",
        "future_leakage_hit_count",
        "eligible_reference_count_mismatch_count",
        "insufficient_history_reference_count_mismatch_count",
        "amount_level_repeated_hit_count",
        "midrank_mismatch_count",
    ):
        if int(stats.get(key, 0)):
            errors.append(f"strict_past_check_failed:{key}")


def _validate_forbidden_and_legacy(
    stats: Mapping[str, Mapping[str, Any]], errors: list[str]
) -> None:
    for key, item in stats.items():
        if int(item.get("forbidden_field_hit_count", 0)):
            errors.append(f"forbidden_field_check_failed:{key}")
        if int(item.get("legacy_v1_hit_count", 0)):
            errors.append(f"legacy_v1_check_failed:{key}")


def _check_no_row_payload(payload: Any, label: str, errors: list[str]) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in {
                "rows",
                "indicator_score_results",
                "dimension_score_results",
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
        raise R0T10ScoreValidationError(f"expected JSON object: {path}")
    return payload


def _count_jsonl_gz_rows(path: Path) -> int:
    count = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate R0-T10-02 generated R0-T05 score artifacts."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_materialization(args.output_dir)
    except R0T10ScoreValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
