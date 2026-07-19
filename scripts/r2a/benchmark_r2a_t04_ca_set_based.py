"""Local-only real-Score benchmark for the R2A-T04 CA transfer repair."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t03_output_contract import (  # noqa: E402
    validate_dynamic_evaluation_output,
)
from src.r2a.r2a_t04_real_data_audit import (  # noqa: E402
    canonical_table_profiles,
    compare_output_databases,
    evaluate_request_with_threads,
    sha256_file,
)
from src.r2a.r2a_t04_request_panel import (  # noqa: E402
    build_request_panel,
    canonical_envelope,
)
from src.r2a.r2a_t04_set_based_evaluator import (  # noqa: E402
    evaluate_request_set_based_with_threads,
)

SCHEMA = ROOT / "schemas/r2a/r2a_t04_ca_set_based_benchmark_receipt.schema.json"
SCORE_SHA256 = "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3"
SCORE_BYTES = 4_255_395_840
SECURITY_IDS = ("603345.SH", "603233.SH", "688220.SH", "300316.SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--implementation-head", required=True)
    parser.add_argument("--implementation-quality", required=True)
    return parser.parse_args()


def _compact_profiles(value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        table: {
            key: profile[key]
            for key in ("row_count", "schema_fingerprint", "canonical_fingerprint")
        }
        for table, profile in value.items()
    }


def _comparison_counts(comparison: dict[str, Any]) -> dict[str, int]:
    tables = comparison["tables"].values()
    return {
        "schema_mismatch_count": sum(
            not item["schema_comparison"]["equal"] for item in tables
        ),
        "row_count_mismatch_count": sum(
            not item["row_count_comparison"]["equal"] for item in tables
        ),
        "left_only_key_count": sum(
            int(item["primary_key_comparison"]["left_only_key_count"] or 0)
            for item in tables
        ),
        "right_only_key_count": sum(
            int(item["primary_key_comparison"]["right_only_key_count"] or 0)
            for item in tables
        ),
        "value_mismatch_row_count": sum(
            int(item["value_comparison"]["value_mismatch_row_count"] or 0)
            for item in tables
        ),
        "column_mismatch_count": sum(
            sum(
                int(count)
                for count in item["value_comparison"][
                    "per_column_mismatch_count"
                ].values()
            )
            for item in tables
        ),
    }


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    if args.output_root.exists():
        raise ValueError("benchmark_output_root_already_exists")
    if args.receipt.exists():
        raise ValueError("benchmark_receipt_already_exists")
    if not args.score_db.is_file():
        raise ValueError("score_database_missing")
    before_sha = sha256_file(args.score_db)
    before_size = args.score_db.stat().st_size
    if before_sha != SCORE_SHA256 or before_size != SCORE_BYTES:
        raise ValueError("score_identity_mismatch")
    panel = build_request_panel()
    receipt: dict[str, Any] = {
        "receipt_version": "r2a_t04_ca_set_based_benchmark_receipt.v1",
        "task_id": "R2A-T04",
        "status": "blocked",
        "reason_codes": [],
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "implementation_head": args.implementation_head,
        "implementation_quality": args.implementation_quality,
        "scope_id": "r2a_t04_ca_q15_q25_k5_response_audit.v1",
        "panel_id": "r2a_t04_ca_q15_q25_k5_panel.v1",
        "request_count": 2,
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "score_database_sha256": before_sha,
        "score_database_byte_size": before_size,
        "requests": [
            {
                "logical_request_name": item["logical_request_name"],
                "request_id": item["request_id"],
                "request_hash": item["request_hash"],
                "canonical_spec": item["spec"],
            }
            for item in panel
        ],
        "equivalence": {
            "security_ids": list(SECURITY_IDS),
            "duckdb_thread_count": 4,
            "request_results": [],
            "all_tables_logically_equal": False,
            "canonical_profiles_equal": False,
        },
        "full_universe": {
            "duckdb_thread_count": 4,
            "security_count": 800,
            "request_results": [],
            "combined_wall_seconds": 0.0,
            "performance_gate_passed": False,
        },
        "formal_run_started": False,
        "formal_attempt_consumed": False,
        "scientific_result_generated": False,
        "contains_absolute_paths": False,
        "source_database_modified": False,
        "residual_output_count": 0,
    }
    args.output_root.mkdir(parents=True)
    try:
        equivalence_passed = True
        profile_passed = True
        for item in panel:
            name = str(item["logical_request_name"])
            old_path = args.output_root / f"equivalence_{name}_old.duckdb"
            new_path = args.output_root / f"equivalence_{name}_new.duckdb"
            old_summary = evaluate_request_with_threads(
                score_database=args.score_db,
                canonical_request=canonical_envelope(item),
                output_database=old_path,
                duckdb_thread_count=4,
                security_ids=SECURITY_IDS,
            )[0]
            new_summary = evaluate_request_set_based_with_threads(
                score_database=args.score_db,
                canonical_request=canonical_envelope(item),
                output_database=new_path,
                duckdb_thread_count=4,
                security_ids=SECURITY_IDS,
            )[0]
            with (
                duckdb.connect(str(old_path), read_only=True) as old_db,
                duckdb.connect(str(new_path), read_only=True) as new_db,
            ):
                validate_dynamic_evaluation_output(old_db)
                validate_dynamic_evaluation_output(new_db)
                old_profiles = _compact_profiles(canonical_table_profiles(old_db))
                new_profiles = _compact_profiles(canonical_table_profiles(new_db))
            comparison = compare_output_databases(
                left_database=old_path,
                right_database=new_path,
                left_threads=4,
                right_threads=4,
            )
            counts = _comparison_counts(comparison)
            profiles_equal = old_profiles == new_profiles
            equivalence_passed = (
                equivalence_passed and comparison["status"] == "logically_equal"
            )
            profile_passed = profile_passed and profiles_equal
            receipt["equivalence"]["request_results"].append(
                {
                    "logical_request_name": name,
                    "old_request_id": old_summary.request_id,
                    "new_request_id": new_summary.request_id,
                    "comparison_status": comparison["status"],
                    "mismatch_counts": counts,
                    "canonical_profiles_equal": profiles_equal,
                    "old_output_profiles": old_profiles,
                    "new_output_profiles": new_profiles,
                }
            )
            old_path.unlink()
            new_path.unlink()
        receipt["equivalence"]["all_tables_logically_equal"] = equivalence_passed
        receipt["equivalence"]["canonical_profiles_equal"] = profile_passed
        if not (equivalence_passed and profile_passed):
            receipt["reason_codes"].append("four_security_equivalence_failed")
            return 1

        combined_wall = 0.0
        performance_passed = True
        for item in panel:
            name = str(item["logical_request_name"])
            result_path = args.output_root / f"full_{name}.duckdb"
            summary, wall, peak, temporary_bytes = (
                evaluate_request_set_based_with_threads(
                    score_database=args.score_db,
                    canonical_request=canonical_envelope(item),
                    output_database=result_path,
                    duckdb_thread_count=4,
                    security_ids=None,
                )
            )
            with duckdb.connect(str(result_path), read_only=True) as result:
                validate_dynamic_evaluation_output(result)
                evaluated_security_count = int(
                    result.execute(
                        "SELECT evaluated_security_count FROM evaluation_scope"
                    ).fetchone()[0]
                )
                profiles = _compact_profiles(canonical_table_profiles(result))
            request_passed = (
                evaluated_security_count == 800
                and wall <= 600
                and peak <= 6_442_450_944
            )
            performance_passed = performance_passed and request_passed
            combined_wall += wall
            receipt["full_universe"]["request_results"].append(
                {
                    "logical_request_name": name,
                    "request_id": summary.request_id,
                    "request_hash": summary.request_hash,
                    "validator_status": "passed",
                    "evaluated_security_count": evaluated_security_count,
                    "wall_seconds": wall,
                    "peak_rss_bytes": peak,
                    "temporary_output_bytes": temporary_bytes,
                    "performance_gate_passed": request_passed,
                    "output_profiles": profiles,
                }
            )
            result_path.unlink()
        performance_passed = performance_passed and combined_wall <= 1200
        receipt["full_universe"]["combined_wall_seconds"] = combined_wall
        receipt["full_universe"]["performance_gate_passed"] = performance_passed
        if not performance_passed:
            receipt["reason_codes"].append("full_universe_performance_gate_failed")
            return 1
        if (
            sha256_file(args.score_db) != before_sha
            or args.score_db.stat().st_size != before_size
        ):
            receipt["source_database_modified"] = True
            receipt["reason_codes"].append("score_source_mutated")
            return 1
        receipt["status"] = "passed"
        receipt["reason_codes"] = ["passed"]
        return 0
    except Exception as error:
        reason = getattr(error, "reason_code", type(error).__name__)
        receipt["reason_codes"].append(str(reason))
        return 1
    finally:
        receipt["source_database_modified"] = (
            sha256_file(args.score_db) != before_sha
            or args.score_db.stat().st_size != before_size
        )
        receipt["residual_output_count"] = sum(
            path.is_file() for path in args.output_root.rglob("*")
        )
        _write_receipt(args.receipt, receipt)
        if receipt["status"] == "passed":
            shutil.rmtree(args.output_root)


if __name__ == "__main__":
    raise SystemExit(main())
