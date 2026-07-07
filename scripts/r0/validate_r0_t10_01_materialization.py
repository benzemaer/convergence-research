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
from src.r0.r0_t10_raw_metric_materializer import (  # noqa: E402
    OUTPUT_DUCKDB_NAME,
    OUTPUT_MANIFEST_NAME,
    OUTPUT_SUMMARY_NAME,
    OUTPUT_TABLE_NAME,
)
from src.r0.raw_metric_engine import RAW_METRIC_IDS  # noqa: E402
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


class R0T10ValidationError(RuntimeError):
    pass


def validate_materialization(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    manifest_path = root / OUTPUT_MANIFEST_NAME
    summary_path = root / OUTPUT_SUMMARY_NAME
    duckdb_path = root / OUTPUT_DUCKDB_NAME
    manifest = _load_json_object(manifest_path)
    summary = _load_json_object(summary_path)
    errors: list[str] = []

    _check_no_row_payload(manifest, "manifest", errors)
    _check_no_row_payload(summary, "summary", errors)
    _expect_file(duckdb_path, errors)
    _expect_file(manifest_path, errors)
    _expect_file(summary_path, errors)

    if duckdb_path.exists() and manifest.get("output_artifact_hash") != sha256_file(
        duckdb_path
    ):
        errors.append("manifest_output_duckdb_hash_mismatch")
    shard_summaries = _validate_shards(manifest, errors)
    shard_row_count = sum(int(item.get("row_count", 0)) for item in shard_summaries)
    manifest_row_count = int(manifest.get("row_count", -1))
    if shard_row_count != manifest_row_count:
        errors.append("shard_row_count_sum_mismatch")

    duckdb_stats = _duckdb_stats(duckdb_path, errors)
    if duckdb_stats.get("table_exists"):
        if duckdb_stats["row_count"] != manifest_row_count:
            errors.append("duckdb_row_count_mismatch")
        if duckdb_stats["security_count"] != int(manifest.get("security_count", -1)):
            errors.append("security_count_mismatch")
        if duckdb_stats["date_min"] != manifest.get("date_min"):
            errors.append("date_min_mismatch")
        if duckdb_stats["date_max"] != manifest.get("date_max"):
            errors.append("date_max_mismatch")
        if set(duckdb_stats["indicator_ids"]) != set(RAW_METRIC_IDS):
            errors.append("required_indicator_id_coverage_mismatch")
        if duckdb_stats["forbidden_field_hit_count"]:
            errors.append("forbidden_field_check_failed")
        if duckdb_stats["legacy_v1_hit_count"]:
            errors.append("legacy_v1_check_failed")

    if int(manifest.get("security_count", 0)) <= 0:
        errors.append("security_count_nonpositive")
    if int(manifest.get("row_count", 0)) <= 0:
        errors.append("row_count_nonpositive")
    if int(summary.get("row_count", -1)) != manifest_row_count:
        errors.append("summary_row_count_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_status_not_completed")
    if int(manifest.get("security_count", -1)) != int(
        summary.get("security_count", -2)
    ):
        errors.append("summary_security_count_mismatch")

    result = {
        "status": "passed" if not errors else "failed",
        "output_dir": str(root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path)
        if manifest_path.exists()
        else None,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path) if summary_path.exists() else None,
        "duckdb_path": str(duckdb_path),
        "duckdb_sha256": sha256_file(duckdb_path) if duckdb_path.exists() else None,
        "manifest_row_count": manifest_row_count,
        "shard_row_count": shard_row_count,
        "shard_count": len(shard_summaries),
        "duckdb_stats": duckdb_stats,
        "forbidden_field_check": (
            "passed" if not duckdb_stats.get("forbidden_field_hit_count") else "blocked"
        ),
        "legacy_v1_check": (
            "passed" if not duckdb_stats.get("legacy_v1_hit_count") else "blocked"
        ),
        "errors": errors,
    }
    if errors:
        raise R0T10ValidationError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate R0-T10-01 generated R0-T04 materialization artifacts."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_materialization(args.output_dir)
    except R0T10ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _validate_shards(
    manifest: Mapping[str, Any], errors: list[str]
) -> list[dict[str, Any]]:
    shards = manifest.get("shards")
    if not isinstance(shards, list):
        errors.append("manifest_shards_missing")
        return []
    summaries: list[dict[str, Any]] = []
    for shard in shards:
        if not isinstance(shard, Mapping):
            errors.append("manifest_shard_not_object")
            continue
        shard_path = Path(str(shard.get("path", "")))
        if not shard_path.exists():
            errors.append(f"shard_missing:{shard_path}")
            continue
        if shard.get("file_sha256") != sha256_file(shard_path):
            errors.append(f"shard_file_hash_mismatch:{shard_path.name}")
        actual_rows = _count_jsonl_gz_rows(shard_path)
        if actual_rows != int(shard.get("row_count", -1)):
            errors.append(f"shard_row_count_mismatch:{shard_path.name}")
        done_path = Path(
            str(shard_path.parent.parent / "status" / f"{shard['chunk_id']}.DONE.json")
        )
        if not done_path.exists():
            errors.append(f"done_marker_missing:{shard['chunk_id']}")
        else:
            done = _load_json_object(done_path)
            if done.get("file_sha256") != shard.get("file_sha256"):
                errors.append(f"done_marker_file_hash_mismatch:{shard['chunk_id']}")
            if int(done.get("row_count", -1)) != int(shard.get("row_count", -2)):
                errors.append(f"done_marker_row_count_mismatch:{shard['chunk_id']}")
        summaries.append(dict(shard))
    return summaries


def _duckdb_stats(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"table_exists": False}
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        table_exists = (
            conn.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [OUTPUT_TABLE_NAME],
            ).fetchone()[0]
            == 1
        )
        if not table_exists:
            errors.append("duckdb_table_missing")
            return {"table_exists": False}
        columns = [
            str(row[1])
            for row in conn.execute(
                f"PRAGMA table_info('{OUTPUT_TABLE_NAME}')"
            ).fetchall()
        ]
        missing = [
            field
            for field in (
                "security_id",
                "trading_date",
                "indicator_id",
                "raw_metric_name",
                "validity_status",
            )
            if field not in columns
        ]
        if missing:
            errors.append("duckdb_required_columns_missing:" + ",".join(missing))
            return {"table_exists": True, "columns": columns}
        quoted = '"' + OUTPUT_TABLE_NAME.replace('"', '""') + '"'
        row_count = int(conn.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])
        security_count = int(
            conn.execute(
                f"SELECT count(DISTINCT security_id) FROM {quoted}"
            ).fetchone()[0]
        )
        date_min, date_max = conn.execute(
            f"SELECT min(trading_date), max(trading_date) FROM {quoted}"
        ).fetchone()
        indicator_ids = [
            str(row[0])
            for row in conn.execute(
                f"SELECT DISTINCT indicator_id FROM {quoted} ORDER BY 1"
            ).fetchall()
        ]
        forbidden_hits = [
            column for column in columns if column.lower() in FORBIDDEN_FIELDS
        ]
        legacy_hits = [column for column in columns if column in LEGACY_V1_FIELD_NAMES]
        indicator_legacy_hits = [
            value for value in indicator_ids if value in LEGACY_V1_FIELD_NAMES
        ]
        return {
            "table_exists": True,
            "columns": columns,
            "row_count": row_count,
            "security_count": security_count,
            "date_min": None if date_min is None else str(date_min),
            "date_max": None if date_max is None else str(date_max),
            "indicator_ids": indicator_ids,
            "forbidden_field_hit_count": len(forbidden_hits),
            "forbidden_field_hits": forbidden_hits,
            "legacy_v1_hit_count": len(legacy_hits) + len(indicator_legacy_hits),
            "legacy_v1_hits": sorted({*legacy_hits, *indicator_legacy_hits}),
        }
    finally:
        conn.close()


def _check_no_row_payload(payload: Any, label: str, errors: list[str]) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in {"rows", "raw_metric_results"} and isinstance(value, list):
                errors.append(f"{label}_contains_row_payload:{key}")
            _check_no_row_payload(value, label, errors)
    elif isinstance(payload, list):
        for value in payload:
            _check_no_row_payload(value, label, errors)


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10ValidationError(f"expected JSON object: {path}")
    return payload


def _count_jsonl_gz_rows(path: Path) -> int:
    count = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _expect_file(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing_file:{path}")


if __name__ == "__main__":
    raise SystemExit(main())
