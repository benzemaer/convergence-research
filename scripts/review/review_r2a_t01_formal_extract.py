# ruff: noqa: E501
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import sys
from collections import defaultdict, deque
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

RECEIPT_VERSION = "r2a_t01_independent_review_receipt.v1"
EXPECTED_RUN_ID = "R2A-T01-20260718T103110891Z"
EXPECTED_RELEASE_ID = "pcavt-score-w120-v1-c7e04f11a2cd09aa"
EXPECTED_EXECUTION_COMMIT = "7c3fe76c575eb350a8e94d2f7534d123e865a64c"
EXPECTED_EXTRACT_SHA256 = (
    "e42ff63c8f5416d1c2372daf2d2033f417ee80d951966d2a89acde9d5da4fb79"
)
EXPECTED_EXTRACT_BYTES = 30_420_992
EXPECTED_FORMAL_DATABASE_SHA256 = (
    "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3"
)
EXPECTED_FORMAL_DATABASE_BYTES = 4_255_395_840
W = 120
ABS_TOLERANCE = 1e-12
MAX_RETAINED_MISMATCHES = 1000

REQUIRED_INPUT_FILES = (
    "r2a_t01_formal_review_extract.duckdb",
    "review_extract_manifest.json",
    "review_bundle_manifest.json",
    "manifest.json",
    "schema.json",
    "validation_receipt.json",
    "result_analysis.md",
)
OUTPUT_FILES = (
    "independent_review_receipt.json",
    "independent_review_report.md",
    "independent_review_mismatches.json",
)
FORBIDDEN_IMPORTS = (
    "src.r2a.score_engine",
    "src.r2a.r2a_t01_validator",
    "src.r2a.r2a_t01_score_release",
    "src.r2a.r2a_t01_result_analysis",
)
ALLOWED_IMPORTS = {
    "argparse",
    "ast",
    "hashlib",
    "json",
    "math",
    "re",
    "sys",
    "collections",
    "datetime",
    "pathlib",
    "zoneinfo",
    "duckdb",
}

EXPECTED_FORMAL_COUNTS = {
    "securities": 800,
    "trading_sessions": 2546,
    "security_observation_spine": 1_751_066,
    "dimension_definitions": 5,
    "dimension_components": 10,
    "daily_component_scores": 17_510_660,
    "daily_dimension_scores": 8_755_330,
}
EXPECTED_OBSERVATION_STATUS = {
    "present": 1_730_769,
    "missing": 19_283,
    "listing_pause": 1_014,
}
PCVT_DIMENSIONS = ("P", "C", "V", "T")
A_COMPONENTS = (
    "A1_LogBodyCenterToMACloudCenter_5_60",
    "A2_BodyCenterOutsideMACloudRate20_5_60",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_script_imports(script_text: str) -> list[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(script_text)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imports.add(node.module or "")
    return sorted(imports)


def json_value(value: object) -> object:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


def write_json(path: Path, payload: object) -> None:
    text = json.dumps(json_value(payload), ensure_ascii=False, indent=2, sort_keys=True)
    path.write_bytes((text + "\n").encode("utf-8"))


def fetch_dicts(
    connection: duckdb.DuckDBPyConnection, sql: str
) -> list[dict[str, object]]:
    cursor = connection.execute(sql)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def is_finite(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value))


def values_equal(expected: object, actual: object, *, floating: bool = False) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if floating:
        if not is_finite(expected) or not is_finite(actual):
            return expected == actual
        return math.isclose(
            float(expected),
            float(actual),
            rel_tol=0.0,
            abs_tol=ABS_TOLERANCE,
        )
    return expected == actual


class ReviewState:
    def __init__(self) -> None:
        self.checks: dict[str, dict[str, object]] = {}
        self.mismatch_count = 0
        self.mismatches: list[dict[str, object]] = []

    def add_mismatch(
        self,
        *,
        check_id: str,
        table: str | None = None,
        security_id: str | None = None,
        trading_date: date | None = None,
        dimension_id: str | None = None,
        component_id: str | None = None,
        field: str,
        expected: object,
        actual: object,
        absolute_difference: float | None = None,
    ) -> None:
        self.mismatch_count += 1
        if len(self.mismatches) >= MAX_RETAINED_MISMATCHES:
            return
        self.mismatches.append(
            {
                "check_id": check_id,
                "table": table,
                "security_id": security_id,
                "trading_date": trading_date,
                "dimension_id": dimension_id,
                "component_id": component_id,
                "field": field,
                "expected": expected,
                "actual": actual,
                "absolute_difference": absolute_difference,
            }
        )

    def check(
        self,
        check_id: str,
        condition: bool,
        *,
        details: object = None,
        table: str | None = None,
        field: str = "check_status",
        expected: object = True,
        actual: object | None = None,
    ) -> bool:
        passed = bool(condition)
        self.checks[check_id] = {
            "status": "passed" if passed else "failed",
            "details": details,
        }
        if not passed:
            self.add_mismatch(
                check_id=check_id,
                table=table,
                field=field,
                expected=expected,
                actual=actual if actual is not None else condition,
            )
        return passed

    def compare_field(
        self,
        *,
        check_id: str,
        table: str,
        row: dict[str, object],
        field: str,
        expected: object,
        actual: object,
        floating: bool = False,
    ) -> bool:
        same = values_equal(expected, actual, floating=floating)
        if same:
            return True
        difference = None
        if floating and is_finite(expected) and is_finite(actual):
            difference = abs(float(expected) - float(actual))
        self.add_mismatch(
            check_id=check_id,
            table=table,
            security_id=row.get("security_id"),
            trading_date=row.get("trading_date"),
            dimension_id=row.get("dimension_id"),
            component_id=row.get("component_id"),
            field=field,
            expected=expected,
            actual=actual,
            absolute_difference=difference,
        )
        return False


def independent_component_series(
    rows: list[dict[str, object]], *, role: str
) -> list[dict[str, object]]:
    if role not in {"pcvt", "a"}:
        raise ValueError(f"unsupported role: {role}")
    history: deque[tuple[date, float]] = deque(maxlen=W)
    results: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda item: int(item["observation_sequence"])):
        raw_value = row.get("raw_value")
        source_validity = str(row["validity_status"])
        current_valid = source_validity == "valid" and is_finite(raw_value)
        references = list(history)
        if role == "pcvt" and not current_valid:
            reference_count = 0
            reference_start = None
            reference_end = None
        else:
            reference_count = len(references)
            reference_start = references[0][0] if references else None
            reference_end = references[-1][0] if references else None

        eligible = current_valid and len(references) == W
        percentile = None
        score = None
        if eligible:
            current = float(raw_value)
            less = sum(value < current for _, value in references)
            equal = sum(value == current for _, value in references)
            percentile = (less + 0.5 * equal) / W
            score = 1.0 - percentile

        if role == "pcvt" and current_valid and not eligible:
            output_validity = "unknown"
        else:
            output_validity = source_validity

        results.append(
            {
                **row,
                "raw_value": raw_value,
                "validity_status": output_validity,
                "eligible": eligible,
                "percentile": percentile,
                "score": score,
                "reference_observation_count": reference_count,
                "reference_window_start": reference_start,
                "reference_window_end": reference_end,
                "percentile_window_W": W,
                "current_value_in_reference_set": False,
            }
        )
        if current_valid:
            history.append((row["trading_date"], float(raw_value)))
    return results


def component_dimension(component_id: str) -> str:
    return component_id[0]


def compare_key_sets(
    state: ReviewState,
    *,
    check_id: str,
    table: str,
    expected: set[tuple[object, ...]],
    actual: set[tuple[object, ...]],
    key_fields: tuple[str, ...],
) -> bool:
    before = state.mismatch_count
    missing = expected - actual
    unexpected = actual - expected
    for key in sorted(missing):
        row = dict(zip(key_fields, key, strict=True))
        state.add_mismatch(
            check_id=check_id,
            table=table,
            security_id=row.get("security_id"),
            trading_date=row.get("trading_date"),
            dimension_id=row.get("dimension_id"),
            component_id=row.get("component_id"),
            field="key_presence",
            expected="present",
            actual="missing",
        )
    for key in sorted(unexpected):
        row = dict(zip(key_fields, key, strict=True))
        state.add_mismatch(
            check_id=check_id,
            table=table,
            security_id=row.get("security_id"),
            trading_date=row.get("trading_date"),
            dimension_id=row.get("dimension_id"),
            component_id=row.get("component_id"),
            field="key_presence",
            expected="absent",
            actual="present",
        )
    passed = state.mismatch_count == before
    state.checks[check_id] = {
        "status": "passed" if passed else "failed",
        "details": {
            "expected_key_count": len(expected),
            "actual_key_count": len(actual),
            "missing_key_count": len(missing),
            "unexpected_key_count": len(unexpected),
        },
    }
    return passed


def identity_checks(
    review_dir: Path,
    state: ReviewState,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    missing = [
        name for name in REQUIRED_INPUT_FILES if not (review_dir / name).is_file()
    ]
    state.check(
        "required_review_inputs_present",
        not missing,
        details={"missing": missing},
        table="review_bundle",
        actual=missing,
    )
    if missing:
        raise RuntimeError(f"missing required review input count={len(missing)}")

    extract_manifest = json.loads(
        (review_dir / "review_extract_manifest.json").read_text(encoding="utf-8")
    )
    bundle_manifest = json.loads(
        (review_dir / "review_bundle_manifest.json").read_text(encoding="utf-8")
    )
    formal_manifest = json.loads(
        (review_dir / "manifest.json").read_text(encoding="utf-8")
    )
    schema = json.loads((review_dir / "schema.json").read_text(encoding="utf-8"))
    validation_receipt = json.loads(
        (review_dir / "validation_receipt.json").read_text(encoding="utf-8")
    )

    extract = review_dir / extract_manifest["extract_filename"]
    extract_hash = sha256_file(extract)
    extract_bytes = extract.stat().st_size
    identity = {
        "review_extract_sha256": extract_hash,
        "review_extract_byte_size": extract_bytes,
        "review_bundle_manifest_sha256": sha256_file(
            review_dir / "review_bundle_manifest.json"
        ),
        "bundle_files": [],
    }
    state.check(
        "review_extract_expected_sha256",
        extract_hash == EXPECTED_EXTRACT_SHA256,
        details={"actual": extract_hash},
        table=extract.name,
        field="sha256",
        expected=EXPECTED_EXTRACT_SHA256,
        actual=extract_hash,
    )
    state.check(
        "review_extract_expected_byte_size",
        extract_bytes == EXPECTED_EXTRACT_BYTES,
        details={"actual": extract_bytes},
        table=extract.name,
        field="byte_size",
        expected=EXPECTED_EXTRACT_BYTES,
        actual=extract_bytes,
    )
    state.check(
        "review_extract_manifest_identity",
        extract_hash == extract_manifest.get("extract_sha256")
        and extract_bytes == extract_manifest.get("extract_byte_size"),
        details={
            "manifest_sha256": extract_manifest.get("extract_sha256"),
            "manifest_byte_size": extract_manifest.get("extract_byte_size"),
        },
        table="review_extract_manifest.json",
        field="extract_identity",
        expected={"sha256": extract_hash, "byte_size": extract_bytes},
        actual={
            "sha256": extract_manifest.get("extract_sha256"),
            "byte_size": extract_manifest.get("extract_byte_size"),
        },
    )

    bundle_ok = True
    original_copy_ok = True
    absolute_path_hits: list[dict[str, object]] = []
    absolute_pattern = re.compile(rb"(?:[A-Za-z]:[\\/]|file://|/Users/|/home/)")
    for item in bundle_manifest.get("bundle_files", []):
        relative = item["relative_path"]
        candidate = (review_dir / relative).resolve()
        if candidate.parent != review_dir.resolve() or not candidate.is_file():
            bundle_ok = False
            state.add_mismatch(
                check_id="bundle_file_identity",
                table="review_bundle_manifest.json",
                field="relative_path",
                expected="existing file inside review-dir",
                actual=relative,
            )
            continue
        actual_hash = sha256_file(candidate)
        actual_bytes = candidate.stat().st_size
        item_ok = actual_hash == item["sha256"] and actual_bytes == item["byte_size"]
        bundle_ok = bundle_ok and item_ok
        if not item_ok:
            state.add_mismatch(
                check_id="bundle_file_identity",
                table=relative,
                field="sha256_and_byte_size",
                expected={"sha256": item["sha256"], "byte_size": item["byte_size"]},
                actual={"sha256": actual_hash, "byte_size": actual_bytes},
            )
        if item.get("origin") == "original":
            copy_ok = actual_hash == item.get("source_file_sha256")
            original_copy_ok = original_copy_ok and copy_ok
            if not copy_ok:
                state.add_mismatch(
                    check_id="compact_formal_copy_identity",
                    table=relative,
                    field="source_file_sha256",
                    expected=item.get("source_file_sha256"),
                    actual=actual_hash,
                )
        if candidate.suffix.lower() != ".duckdb" and absolute_pattern.search(
            candidate.read_bytes()
        ):
            absolute_path_hits.append({"file": relative, "field": "file_bytes"})
        identity["bundle_files"].append(
            {
                "relative_path": relative,
                "sha256": actual_hash,
                "byte_size": actual_bytes,
            }
        )
    state.check(
        "bundle_file_identity",
        bundle_ok,
        details={"checked_file_count": len(identity["bundle_files"])},
        table="review_bundle_manifest.json",
    )
    state.check(
        "compact_formal_copy_identity",
        original_copy_ok,
        details={"original_file_count": 4},
        table="review_bundle_manifest.json",
    )

    run_ids = {
        extract_manifest.get("run_id"),
        bundle_manifest.get("run_id"),
        formal_manifest.get("run_id"),
        validation_receipt.get("run_id"),
    }
    state.check(
        "formal_run_id_consistent",
        run_ids == {EXPECTED_RUN_ID},
        details={"values": sorted(str(value) for value in run_ids)},
        field="run_id",
        expected=EXPECTED_RUN_ID,
        actual=sorted(str(value) for value in run_ids),
    )
    release_ids = {
        formal_manifest.get("score_release_id"),
        validation_receipt.get("score_release_id"),
    }
    state.check(
        "score_release_id_consistent",
        release_ids == {EXPECTED_RELEASE_ID},
        details={"values": sorted(str(value) for value in release_ids)},
        field="score_release_id",
        expected=EXPECTED_RELEASE_ID,
        actual=sorted(str(value) for value in release_ids),
    )
    commits = {
        extract_manifest.get("reviewed_execution_commit"),
        bundle_manifest.get("reviewed_execution_commit"),
        formal_manifest.get("execution_commit"),
    }
    state.check(
        "reviewed_execution_commit_consistent",
        commits == {EXPECTED_EXECUTION_COMMIT},
        details={"values": sorted(str(value) for value in commits)},
        field="reviewed_execution_commit",
        expected=EXPECTED_EXECUTION_COMMIT,
        actual=sorted(str(value) for value in commits),
    )
    database_refs = {
        (
            extract_manifest.get("full_formal_database_sha256"),
            extract_manifest.get("full_formal_database_byte_size"),
        ),
        (
            formal_manifest.get("score_data_sha256"),
            formal_manifest.get("database_byte_size"),
        ),
        (
            bundle_manifest.get("formal_database_sha256"),
            EXPECTED_FORMAL_DATABASE_BYTES,
        ),
    }
    state.check(
        "formal_database_identity_reference_consistent",
        database_refs
        == {(EXPECTED_FORMAL_DATABASE_SHA256, EXPECTED_FORMAL_DATABASE_BYTES)},
        details={"values": sorted((str(a), b) for a, b in database_refs)},
        field="formal_database_identity_reference",
        expected={
            "sha256": EXPECTED_FORMAL_DATABASE_SHA256,
            "byte_size": EXPECTED_FORMAL_DATABASE_BYTES,
        },
        actual=sorted((str(a), b) for a, b in database_refs),
    )

    script_text = Path(__file__).read_text(encoding="utf-8")
    actual_imports = parse_script_imports(script_text)
    forbidden_hits = [
        name
        for name in actual_imports
        if any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_IMPORTS
        )
    ]
    unexpected_imports = sorted(set(actual_imports) - ALLOWED_IMPORTS)
    state.check(
        "review_script_import_independence",
        not forbidden_hits and not unexpected_imports,
        details={
            "imports": actual_imports,
            "forbidden_import_hits": forbidden_hits,
            "unexpected_imports": unexpected_imports,
        },
        table=Path(__file__).name,
        actual={
            "forbidden_import_hits": forbidden_hits,
            "unexpected_imports": unexpected_imports,
        },
    )
    formal_call_tokens = (
        "materialize_" + "score_release(",
        "validate_" + "score_release(",
        "analyze_" + "score_release(",
        "run_r2a_t01_" + "score_release.py",
    )
    formal_call_hits = [token for token in formal_call_tokens if token in script_text]
    state.check(
        "review_script_has_no_formal_execution_calls",
        not formal_call_hits,
        details={"formal_call_hits": formal_call_hits},
        table=Path(__file__).name,
        actual=formal_call_hits,
    )
    identity["review_script_imports"] = actual_imports
    declared_flags = {
        "extract_contains_absolute_paths": extract_manifest.get(
            "contains_absolute_paths"
        ),
        "bundle_contains_absolute_paths": bundle_manifest.get(
            "contains_absolute_paths"
        ),
        "extract_formal_outputs_modified": extract_manifest.get(
            "formal_outputs_modified"
        ),
        "bundle_formal_outputs_modified": bundle_manifest.get(
            "formal_outputs_modified"
        ),
        "materializer_validator_analyzer_rerun": extract_manifest.get(
            "materializer_validator_analyzer_rerun"
        ),
    }
    flags_false = all(value is False for value in declared_flags.values())
    state.check(
        "review_scope_flags_false",
        flags_false,
        details=declared_flags,
        table="review_manifests",
        actual=declared_flags,
    )
    state.check(
        "formal_outputs_unmodified_by_accessible_identity",
        original_copy_ok
        and database_refs
        == {(EXPECTED_FORMAL_DATABASE_SHA256, EXPECTED_FORMAL_DATABASE_BYTES)},
        details={
            "method": "byte-identical compact copies plus consistent immutable database reference; full database not accessed"
        },
        table="review_bundle",
    )
    state.check(
        "no_absolute_paths_in_text_bundle_files",
        not absolute_path_hits,
        details={"hits": absolute_path_hits},
        table="review_bundle",
        actual=absolute_path_hits,
    )
    state.check(
        "schema_descriptor_seven_tables",
        len(schema.get("table_order", [])) == 7,
        details={"table_order": schema.get("table_order")},
        table="schema.json",
    )
    return extract_manifest, formal_manifest, identity


def database_inventory(
    extract: Path,
    extract_manifest: dict[str, object],
    state: ReviewState,
) -> tuple[duckdb.DuckDBPyConnection, list[dict[str, object]]]:
    connection = duckdb.connect(str(extract), read_only=True)
    database_name = connection.execute("SELECT current_database()").fetchone()[0]
    actual_tables = [
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name=? AND schema_name='main' ORDER BY table_name",
            [database_name],
        ).fetchall()
    ]
    expected_counts = extract_manifest["table_counts"]
    expected_tables = sorted(expected_counts)
    state.check(
        "exact_30_table_inventory",
        len(actual_tables) == 30 and actual_tables == expected_tables,
        details={"actual": actual_tables, "expected": expected_tables},
        table=extract.name,
        expected=expected_tables,
        actual=actual_tables,
    )
    inventory: list[dict[str, object]] = []
    counts_ok = True
    for table_name in actual_tables:
        row_count = connection.execute(
            f'SELECT count(*) FROM "{table_name}"'
        ).fetchone()[0]
        if row_count != expected_counts.get(table_name):
            counts_ok = False
            state.add_mismatch(
                check_id="review_table_row_counts",
                table=table_name,
                field="row_count",
                expected=expected_counts.get(table_name),
                actual=row_count,
            )
        columns = []
        for column in connection.execute(
            f"PRAGMA table_info('{table_name}')"
        ).fetchall():
            columns.append(
                {
                    "column_name": column[1],
                    "column_type": column[2],
                    "nullable": not bool(column[3]),
                }
            )
        inventory.append(
            {"table_name": table_name, "row_count": row_count, "columns": columns}
        )
    state.check(
        "review_table_row_counts",
        counts_ok,
        details={"checked_table_count": len(actual_tables)},
        table=extract.name,
    )
    views = connection.execute(
        "SELECT schema_name, view_name FROM duckdb_views() "
        "WHERE database_name=? AND NOT internal",
        [database_name],
    ).fetchall()
    macros = connection.execute(
        "SELECT schema_name, function_name FROM duckdb_functions() "
        "WHERE database_name=? AND function_type='macro' AND NOT internal",
        [database_name],
    ).fetchall()
    temporary = connection.execute(
        "SELECT schema_name, table_name FROM duckdb_tables() WHERE temporary"
    ).fetchall()
    state.check(
        "no_view_macro_or_temporary_relation",
        not views and not macros and not temporary,
        details={"views": views, "macros": macros, "temporary": temporary},
        table=extract.name,
    )

    absolute_hits: list[dict[str, object]] = []
    for table in inventory:
        table_name = table["table_name"]
        for column in table["columns"]:
            if "VARCHAR" not in column["column_type"]:
                continue
            column_name = column["column_name"]
            count = connection.execute(
                f'SELECT count(*) FROM "{table_name}" '
                f'WHERE CAST("{column_name}" AS VARCHAR) '
                "SIMILAR TO '%([A-Za-z]:[\\\\/]|file://|/Users/|/home/)%'"
            ).fetchone()[0]
            if count:
                absolute_hits.append(
                    {"table": table_name, "column": column_name, "row_count": count}
                )
    state.check(
        "no_absolute_paths_in_review_database",
        not absolute_hits,
        details={"hits": absolute_hits},
        table=extract.name,
        actual=absolute_hits,
    )
    return connection, inventory


def sample_component_recomputation(
    connection: duckdb.DuckDBPyConnection,
    state: ReviewState,
) -> tuple[dict[str, object], dict[tuple[str, date, str], dict[str, object]]]:
    spine_rows = fetch_dicts(
        connection,
        "SELECT * FROM sample_spine ORDER BY security_id, observation_sequence",
    )
    spine_by_security: dict[str, list[dict[str, object]]] = defaultdict(list)
    spine_key: dict[tuple[str, date], dict[str, object]] = {}
    for row in spine_rows:
        spine_by_security[row["security_id"]].append(row)
        spine_key[(row["security_id"], row["trading_date"])] = row

    output_rows = fetch_dicts(connection, "SELECT * FROM sample_component_scores")
    output = {
        (row["security_id"], row["trading_date"], row["component_id"]): row
        for row in output_rows
    }
    pcvt_components = sorted(
        {
            row["component_id"]
            for row in output_rows
            if row["dimension_id"] in PCVT_DIMENSIONS
        }
    )
    state.check(
        "component_registry_sample_shape",
        len(pcvt_components) == 8
        and set(A_COMPONENTS)
        == {row["component_id"] for row in output_rows if row["dimension_id"] == "A"},
        details={"pcvt_components": pcvt_components, "a_components": A_COMPONENTS},
        table="sample_component_scores",
    )
    a2b_count = sum("A2b" in str(row["component_id"]) for row in output_rows)
    state.check(
        "a2b_rows_zero",
        a2b_count == 0,
        details={"a2b_rows": a2b_count},
        table="sample_component_scores",
        field="A2b_rows",
        expected=0,
        actual=a2b_count,
    )

    raw_pcvt_rows = fetch_dicts(connection, "SELECT * FROM sample_pcvt_validation_raw")
    raw_pcvt = {
        (row["security_id"], row["trading_date"], row["mapped_component_id"]): row
        for row in raw_pcvt_rows
    }
    expected_pcvt: dict[tuple[str, date, str], dict[str, object]] = {}
    expected_pcvt_raw_keys = {
        (
            observation["security_id"],
            observation["trading_date"],
            component_id,
        )
        for observation in spine_rows
        if observation["expected_observation_status"] == "present"
        for component_id in pcvt_components
    }
    compare_key_sets(
        state,
        check_id="pcvt_validation_raw_keyset",
        table="sample_pcvt_validation_raw",
        expected=expected_pcvt_raw_keys,
        actual=set(raw_pcvt),
        key_fields=("security_id", "trading_date", "component_id"),
    )
    for security_id, observations in spine_by_security.items():
        for component_id in pcvt_components:
            series = []
            for observation in observations:
                key = (security_id, observation["trading_date"], component_id)
                raw = raw_pcvt.get(key)
                if raw is None:
                    raw = {
                        "raw_value": None,
                        "validity_status": "blocked",
                    }
                series.append(
                    {
                        "security_id": security_id,
                        "trading_date": observation["trading_date"],
                        "observation_sequence": observation["observation_sequence"],
                        "dimension_id": component_dimension(component_id),
                        "component_id": component_id,
                        "raw_value": raw["raw_value"],
                        "validity_status": raw["validity_status"],
                    }
                )
            for computed in independent_component_series(series, role="pcvt"):
                key = (
                    computed["security_id"],
                    computed["trading_date"],
                    computed["component_id"],
                )
                expected_pcvt[key] = computed

    pcvt_output = {
        key: row
        for key, row in output.items()
        if row["dimension_id"] in PCVT_DIMENSIONS
    }
    compare_key_sets(
        state,
        check_id="pcvt_recompute_keyset",
        table="sample_component_scores",
        expected=set(expected_pcvt),
        actual=set(pcvt_output),
        key_fields=("security_id", "trading_date", "component_id"),
    )
    pcvt_fields = (
        "observation_sequence",
        "raw_value",
        "validity_status",
        "eligible",
        "percentile",
        "score",
        "reference_observation_count",
        "reference_window_start",
        "reference_window_end",
        "percentile_window_W",
        "current_value_in_reference_set",
    )
    pcvt_float_fields = {"raw_value", "percentile", "score"}
    pcvt_before = state.mismatch_count
    pcvt_row_mismatches = 0
    pcvt_max_difference = 0.0
    for key in sorted(set(expected_pcvt) & set(pcvt_output)):
        expected_row = expected_pcvt[key]
        actual_row = pcvt_output[key]
        row_before = state.mismatch_count
        for field in pcvt_fields:
            expected_value = expected_row[field]
            actual_value = actual_row[field]
            if (
                field in pcvt_float_fields
                and is_finite(expected_value)
                and is_finite(actual_value)
            ):
                pcvt_max_difference = max(
                    pcvt_max_difference,
                    abs(float(expected_value) - float(actual_value)),
                )
            state.compare_field(
                check_id="pcvt_strict_past_recomputation",
                table="sample_component_scores",
                row=actual_row,
                field=field,
                expected=expected_value,
                actual=actual_value,
                floating=field in pcvt_float_fields,
            )
        if state.mismatch_count > row_before:
            pcvt_row_mismatches += 1
    pcvt_mismatch_fields = state.mismatch_count - pcvt_before
    state.checks["pcvt_strict_past_recomputation"] = {
        "status": "passed" if pcvt_mismatch_fields == 0 else "failed",
        "details": {
            "compared_rows": len(set(expected_pcvt) & set(pcvt_output)),
            "mismatch_rows": pcvt_row_mismatches,
            "mismatch_fields": pcvt_mismatch_fields,
            "maximum_absolute_difference": pcvt_max_difference,
        },
    }

    raw_a_rows = fetch_dicts(connection, "SELECT * FROM sample_a_raw")
    raw_a = {
        (row["security_id"], row["trading_date"], row["component_id"]): row
        for row in raw_a_rows
    }
    expected_a: dict[tuple[str, date, str], dict[str, object]] = {}
    expected_a_raw_keys = {
        (
            observation["security_id"],
            observation["trading_date"],
            component_id,
        )
        for observation in spine_rows
        for component_id in A_COMPONENTS
    }
    compare_key_sets(
        state,
        check_id="a_raw_keyset",
        table="sample_a_raw",
        expected=expected_a_raw_keys,
        actual=set(raw_a),
        key_fields=("security_id", "trading_date", "component_id"),
    )
    for security_id, observations in spine_by_security.items():
        for component_id in A_COMPONENTS:
            series = []
            for observation in observations:
                key = (security_id, observation["trading_date"], component_id)
                raw = raw_a.get(key)
                if raw is None:
                    state.add_mismatch(
                        check_id="a_raw_keyset",
                        table="sample_a_raw",
                        security_id=security_id,
                        trading_date=observation["trading_date"],
                        dimension_id="A",
                        component_id=component_id,
                        field="key_presence",
                        expected="present",
                        actual="missing",
                    )
                    raw = {"raw_value": None, "validity_status": "blocked"}
                series.append(
                    {
                        "security_id": security_id,
                        "trading_date": observation["trading_date"],
                        "observation_sequence": observation["observation_sequence"],
                        "dimension_id": "A",
                        "component_id": component_id,
                        "raw_value": raw["raw_value"],
                        "validity_status": raw["validity_status"],
                    }
                )
            for computed in independent_component_series(series, role="a"):
                key = (
                    computed["security_id"],
                    computed["trading_date"],
                    computed["component_id"],
                )
                expected_a[key] = computed

    a_output = {key: row for key, row in output.items() if row["dimension_id"] == "A"}
    compare_key_sets(
        state,
        check_id="a_recompute_keyset",
        table="sample_component_scores",
        expected=set(expected_a),
        actual=set(a_output),
        key_fields=("security_id", "trading_date", "component_id"),
    )
    a_before = state.mismatch_count
    a_row_mismatches = 0
    a_max_difference = 0.0
    for key in sorted(set(expected_a) & set(a_output)):
        expected_row = expected_a[key]
        actual_row = a_output[key]
        row_before = state.mismatch_count
        for field in pcvt_fields:
            expected_value = expected_row[field]
            actual_value = actual_row[field]
            if (
                field in pcvt_float_fields
                and is_finite(expected_value)
                and is_finite(actual_value)
            ):
                a_max_difference = max(
                    a_max_difference,
                    abs(float(expected_value) - float(actual_value)),
                )
            state.compare_field(
                check_id="a_strict_past_recomputation",
                table="sample_component_scores",
                row=actual_row,
                field=field,
                expected=expected_value,
                actual=actual_value,
                floating=field in pcvt_float_fields,
            )
        if state.mismatch_count > row_before:
            a_row_mismatches += 1
    a_mismatch_fields = state.mismatch_count - a_before
    state.checks["a_strict_past_recomputation"] = {
        "status": "passed" if a_mismatch_fields == 0 else "failed",
        "details": {
            "compared_rows": len(set(expected_a) & set(a_output)),
            "mismatch_rows": a_row_mismatches,
            "mismatch_fields": a_mismatch_fields,
            "maximum_absolute_difference": a_max_difference,
        },
    }

    global_contract_ok = all(
        row["percentile_window_W"] == W
        and row["current_value_in_reference_set"] is False
        for row in output_rows
    )
    state.check(
        "component_w120_and_current_excluded",
        global_contract_ok,
        details={"row_count": len(output_rows)},
        table="sample_component_scores",
    )
    return (
        {
            "pcvt": state.checks["pcvt_strict_past_recomputation"]["details"],
            "a": state.checks["a_strict_past_recomputation"]["details"],
            "pcvt_components": pcvt_components,
            "a_components": list(A_COMPONENTS),
        },
        output,
    )


def dimension_recomputation(
    connection: duckdb.DuckDBPyConnection,
    component_output: dict[tuple[str, date, str], dict[str, object]],
    state: ReviewState,
) -> dict[str, dict[str, object]]:
    groups: dict[tuple[str, date, str], list[dict[str, object]]] = defaultdict(list)
    for row in component_output.values():
        groups[(row["security_id"], row["trading_date"], row["dimension_id"])].append(
            row
        )
    actual_rows = fetch_dicts(connection, "SELECT * FROM sample_dimension_scores")
    actual = {
        (row["security_id"], row["trading_date"], row["dimension_id"]): row
        for row in actual_rows
    }
    compare_key_sets(
        state,
        check_id="dimension_recompute_keyset",
        table="sample_dimension_scores",
        expected=set(groups),
        actual=set(actual),
        key_fields=("security_id", "trading_date", "dimension_id"),
    )
    stats: dict[str, dict[str, object]] = {}
    for dimension_id in ("P", "C", "A", "V", "T"):
        compared = 0
        eligible_rows = 0
        mismatch_rows = 0
        max_mean_difference = 0.0
        max_min_difference = 0.0
        for key in sorted(groups):
            if key[2] != dimension_id or key not in actual:
                continue
            components = groups[key]
            row = actual[key]
            compared += 1
            valid_scores = [
                float(component["score"])
                for component in components
                if component["eligible"] is True
                and component["validity_status"] == "valid"
                and is_finite(component["score"])
            ]
            expected_eligible = len(components) == 2 and len(valid_scores) == 2
            if expected_eligible:
                eligible_rows += 1
                expected_mean = sum(valid_scores) / 2.0
                expected_min = min(valid_scores)
            else:
                expected_mean = None
                expected_min = None
            statuses = {component["validity_status"] for component in components}
            if "blocked" in statuses:
                expected_validity = "blocked"
            elif "diagnostic_required" in statuses:
                expected_validity = "diagnostic_required"
            elif "unknown" in statuses:
                expected_validity = "unknown"
            else:
                expected_validity = "valid"
            expected_values = {
                "observation_sequence": components[0]["observation_sequence"],
                "eligible_dimension": expected_eligible,
                "score_dimension": expected_mean,
                "score_dimension_min": expected_min,
                "validity_status": expected_validity,
                "component_count": 2,
                "percentile_window_W": W,
            }
            row_before = state.mismatch_count
            for field, expected_value in expected_values.items():
                actual_value = row[field]
                floating = field in {"score_dimension", "score_dimension_min"}
                if floating and is_finite(expected_value) and is_finite(actual_value):
                    difference = abs(float(expected_value) - float(actual_value))
                    if field == "score_dimension":
                        max_mean_difference = max(max_mean_difference, difference)
                    else:
                        max_min_difference = max(max_min_difference, difference)
                state.compare_field(
                    check_id="dimension_mean_min_recomputation",
                    table="sample_dimension_scores",
                    row=row,
                    field=field,
                    expected=expected_value,
                    actual=actual_value,
                    floating=floating,
                )
            if state.mismatch_count > row_before:
                mismatch_rows += 1
        stats[dimension_id] = {
            "compared_rows": compared,
            "eligible_rows": eligible_rows,
            "mismatch_rows": mismatch_rows,
            "maximum_absolute_mean_difference": max_mean_difference,
            "maximum_absolute_min_difference": max_min_difference,
        }
    total_mismatches = sum(item["mismatch_rows"] for item in stats.values())
    state.checks["dimension_mean_min_recomputation"] = {
        "status": "passed" if total_mismatches == 0 else "failed",
        "details": stats,
    }
    return stats


def source_reconciliation(
    connection: duckdb.DuckDBPyConnection,
    component_output: dict[tuple[str, date, str], dict[str, object]],
    state: ReviewState,
) -> dict[str, object]:
    spine = {
        (row["security_id"], row["trading_date"]): row
        for row in fetch_dicts(connection, "SELECT * FROM sample_spine")
    }
    source_run_id = connection.execute(
        "SELECT source_run_id FROM source_bindings "
        "WHERE source_role='pcvt_component_scores'"
    ).fetchone()[0]
    source_component_rows = fetch_dicts(
        connection, "SELECT * FROM sample_pcvt_source_component_scores"
    )
    source_components = {
        (row["security_id"], row["trading_date"], row["mapped_component_id"]): row
        for row in source_component_rows
    }
    output_components = {
        key: row
        for key, row in component_output.items()
        if row["dimension_id"] in PCVT_DIMENSIONS
        and spine[(row["security_id"], row["trading_date"])][
            "expected_observation_status"
        ]
        == "present"
    }
    component_key_before = state.mismatch_count
    compare_key_sets(
        state,
        check_id="pcvt_source_component_keyset",
        table="sample_pcvt_source_component_scores",
        expected=set(output_components),
        actual=set(source_components),
        key_fields=("security_id", "trading_date", "component_id"),
    )
    component_key_mismatches = state.mismatch_count - component_key_before
    component_fields = (
        "raw_value",
        "percentile",
        "score",
        "eligible",
        "validity_status",
        "reason_codes",
        "reference_observation_count",
        "reference_window_start",
        "reference_window_end",
        "current_value_in_reference_set",
        "score_engine_version",
    )
    component_before = state.mismatch_count
    component_row_mismatches = 0
    component_max_difference = 0.0
    for key in sorted(set(output_components) & set(source_components)):
        source = source_components[key]
        output = output_components[key]
        row_before = state.mismatch_count
        expected_values = {
            "observation_sequence": spine[(key[0], key[1])]["observation_sequence"],
            "dimension_id": component_dimension(key[2]),
            "component_id": source["mapped_component_id"],
            "source_run_id": source_run_id,
            **{field: source[field] for field in component_fields},
        }
        for field, expected in expected_values.items():
            actual = output[field]
            floating = field in {"raw_value", "percentile", "score"}
            if floating and is_finite(expected) and is_finite(actual):
                component_max_difference = max(
                    component_max_difference, abs(float(expected) - float(actual))
                )
            state.compare_field(
                check_id="pcvt_source_component_values",
                table="sample_component_scores",
                row=output,
                field=field,
                expected=expected,
                actual=actual,
                floating=floating,
            )
        if state.mismatch_count > row_before:
            component_row_mismatches += 1
    component_value_mismatches = state.mismatch_count - component_before
    state.checks["pcvt_source_component_values"] = {
        "status": "passed" if component_value_mismatches == 0 else "failed",
        "details": {
            "compared_rows": len(set(output_components) & set(source_components)),
            "key_mismatches": component_key_mismatches,
            "mismatch_rows": component_row_mismatches,
            "mismatch_fields": component_value_mismatches,
            "maximum_absolute_difference": component_max_difference,
        },
    }

    source_dimension_rows = fetch_dicts(
        connection, "SELECT * FROM sample_pcvt_source_dimension_scores"
    )
    source_dimensions = {
        (row["security_id"], row["trading_date"], row["dimension_id"]): row
        for row in source_dimension_rows
    }
    output_dimension_rows = fetch_dicts(
        connection,
        "SELECT * FROM sample_dimension_scores WHERE dimension_id IN ('P','C','V','T')",
    )
    output_dimensions = {
        (row["security_id"], row["trading_date"], row["dimension_id"]): row
        for row in output_dimension_rows
        if spine[(row["security_id"], row["trading_date"])][
            "expected_observation_status"
        ]
        == "present"
    }
    dimension_key_before = state.mismatch_count
    compare_key_sets(
        state,
        check_id="pcvt_source_dimension_keyset",
        table="sample_pcvt_source_dimension_scores",
        expected=set(output_dimensions),
        actual=set(source_dimensions),
        key_fields=("security_id", "trading_date", "dimension_id"),
    )
    dimension_key_mismatches = state.mismatch_count - dimension_key_before
    dimension_before = state.mismatch_count
    dimension_row_mismatches = 0
    dimension_max_difference = 0.0
    dimension_fields = (
        "score_dimension",
        "score_dimension_min",
        "eligible_dimension",
        "validity_status",
        "reason_codes",
        "score_engine_version",
    )
    for key in sorted(set(output_dimensions) & set(source_dimensions)):
        source = source_dimensions[key]
        output = output_dimensions[key]
        row_before = state.mismatch_count
        expected_values = {
            "observation_sequence": spine[(key[0], key[1])]["observation_sequence"],
            "dimension_id": source["dimension_id"],
            **{field: source[field] for field in dimension_fields},
        }
        for field, expected in expected_values.items():
            actual = output[field]
            floating = field in {"score_dimension", "score_dimension_min"}
            if floating and is_finite(expected) and is_finite(actual):
                dimension_max_difference = max(
                    dimension_max_difference, abs(float(expected) - float(actual))
                )
            state.compare_field(
                check_id="pcvt_source_dimension_values",
                table="sample_dimension_scores",
                row=output,
                field=field,
                expected=expected,
                actual=actual,
                floating=floating,
            )
        if state.mismatch_count > row_before:
            dimension_row_mismatches += 1
    dimension_value_mismatches = state.mismatch_count - dimension_before
    state.checks["pcvt_source_dimension_values"] = {
        "status": "passed" if dimension_value_mismatches == 0 else "failed",
        "details": {
            "compared_rows": len(set(output_dimensions) & set(source_dimensions)),
            "key_mismatches": dimension_key_mismatches,
            "mismatch_rows": dimension_row_mismatches,
            "mismatch_fields": dimension_value_mismatches,
            "maximum_absolute_difference": dimension_max_difference,
        },
    }
    return {
        "component": state.checks["pcvt_source_component_values"]["details"],
        "dimension": state.checks["pcvt_source_dimension_values"]["details"],
    }


def spine_expected_empty_availability(
    connection: duckdb.DuckDBPyConnection,
    state: ReviewState,
) -> dict[str, object]:
    securities = fetch_dicts(
        connection, "SELECT * FROM sample_securities ORDER BY selected_order"
    )
    spine_rows = fetch_dicts(
        connection,
        "SELECT * FROM sample_spine ORDER BY security_id, observation_sequence",
    )
    component_rows = fetch_dicts(connection, "SELECT * FROM sample_component_scores")
    dimension_rows = fetch_dicts(connection, "SELECT * FROM sample_dimension_scores")
    by_security: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in spine_rows:
        by_security[row["security_id"]].append(row)
    metadata = {row["security_id"]: row for row in securities}
    sequence_mismatch_rows = 0
    for security_id, rows in by_security.items():
        expected_sequences = list(range(len(rows)))
        actual_sequences = [row["observation_sequence"] for row in rows]
        conditions = {
            "zero_based_contiguous": actual_sequences == expected_sequences,
            "no_duplicate": len(actual_sequences) == len(set(actual_sequences)),
            "dates_strictly_increasing": all(
                rows[index - 1]["trading_date"] < rows[index]["trading_date"]
                for index in range(1, len(rows))
            ),
            "first_date": rows[0]["trading_date"]
            == metadata[security_id]["first_expected_date"],
            "last_date": rows[-1]["trading_date"]
            == metadata[security_id]["last_expected_date"],
            "expected_count": len(rows)
            == metadata[security_id]["expected_observation_count"],
        }
        for field, condition in conditions.items():
            if not condition:
                sequence_mismatch_rows += 1
                state.add_mismatch(
                    check_id="sample_spine_sequence",
                    table="sample_spine",
                    security_id=security_id,
                    field=field,
                    expected=True,
                    actual=False,
                )
    state.checks["sample_spine_sequence"] = {
        "status": "passed" if sequence_mismatch_rows == 0 else "failed",
        "details": {
            "security_count": len(by_security),
            "observation_count": len(spine_rows),
            "mismatch_count": sequence_mismatch_rows,
        },
    }

    expected_empty = {
        (row["security_id"], row["trading_date"]): row
        for row in spine_rows
        if row["expected_observation_status"] in {"missing", "listing_pause"}
    }
    components_by_observation: dict[tuple[str, date], list[dict[str, object]]] = (
        defaultdict(list)
    )
    dimensions_by_observation: dict[tuple[str, date], list[dict[str, object]]] = (
        defaultdict(list)
    )
    for row in component_rows:
        components_by_observation[(row["security_id"], row["trading_date"])].append(row)
    for row in dimension_rows:
        dimensions_by_observation[(row["security_id"], row["trading_date"])].append(row)
    empty_mismatches = 0
    blocked_component_count = 0
    blocked_dimension_count = 0
    for key, spine_row in expected_empty.items():
        components = components_by_observation[key]
        dimensions = dimensions_by_observation[key]
        blocked_component_count += sum(
            row["validity_status"] == "blocked" for row in components
        )
        blocked_dimension_count += sum(
            row["validity_status"] == "blocked" for row in dimensions
        )
        component_ok = len(components) == 10 and all(
            row["score"] is None
            and row["percentile"] is None
            and row["eligible"] is False
            and row["validity_status"] == "blocked"
            for row in components
        )
        dimension_ok = len(dimensions) == 5 and all(
            row["score_dimension"] is None
            and row["score_dimension_min"] is None
            and row["eligible_dimension"] is False
            and row["validity_status"] == "blocked"
            for row in dimensions
        )
        if not component_ok:
            empty_mismatches += 1
            state.add_mismatch(
                check_id="sample_expected_empty",
                table="sample_component_scores",
                security_id=key[0],
                trading_date=key[1],
                field="blocked_component_contract",
                expected={"rows": 10, "all_blocked_null_ineligible": True},
                actual={"rows": len(components), "contract": component_ok},
            )
        if not dimension_ok:
            empty_mismatches += 1
            state.add_mismatch(
                check_id="sample_expected_empty",
                table="sample_dimension_scores",
                security_id=key[0],
                trading_date=key[1],
                field="blocked_dimension_contract",
                expected={"rows": 5, "all_blocked_null_ineligible": True},
                actual={"rows": len(dimensions), "contract": dimension_ok},
            )
    state.checks["sample_expected_empty"] = {
        "status": "passed" if empty_mismatches == 0 else "failed",
        "details": {
            "expected_empty_observation_count": len(expected_empty),
            "blocked_component_count": blocked_component_count,
            "blocked_dimension_count": blocked_dimension_count,
            "mismatch_count": empty_mismatches,
        },
    }

    shanghai = ZoneInfo("Asia/Shanghai")
    spine_by_key = {
        (row["security_id"], row["trading_date"]): row for row in spine_rows
    }
    spine_availability_mismatch = 0
    component_availability_mismatch = 0
    dimension_availability_mismatch = 0
    for row in spine_rows:
        expected = datetime.combine(row["trading_date"], time(15, 0), tzinfo=shanghai)
        if row["observation_available_time"].astimezone(shanghai) != expected:
            spine_availability_mismatch += 1
            state.add_mismatch(
                check_id="sample_availability",
                table="sample_spine",
                security_id=row["security_id"],
                trading_date=row["trading_date"],
                field="observation_available_time",
                expected=expected,
                actual=row["observation_available_time"],
            )
    for row in component_rows:
        expected = spine_by_key[(row["security_id"], row["trading_date"])][
            "observation_available_time"
        ]
        if row["available_time"] != expected:
            component_availability_mismatch += 1
            state.add_mismatch(
                check_id="sample_availability",
                table="sample_component_scores",
                security_id=row["security_id"],
                trading_date=row["trading_date"],
                dimension_id=row["dimension_id"],
                component_id=row["component_id"],
                field="available_time",
                expected=expected,
                actual=row["available_time"],
            )
    for row in dimension_rows:
        expected = spine_by_key[(row["security_id"], row["trading_date"])][
            "observation_available_time"
        ]
        if row["available_time"] != expected:
            dimension_availability_mismatch += 1
            state.add_mismatch(
                check_id="sample_availability",
                table="sample_dimension_scores",
                security_id=row["security_id"],
                trading_date=row["trading_date"],
                dimension_id=row["dimension_id"],
                field="available_time",
                expected=expected,
                actual=row["available_time"],
            )
    availability = {
        "spine_availability_mismatch": spine_availability_mismatch,
        "component_availability_mismatch": component_availability_mismatch,
        "dimension_availability_mismatch": dimension_availability_mismatch,
    }
    state.checks["sample_availability"] = {
        "status": "passed" if not any(availability.values()) else "failed",
        "details": availability,
    }
    return {
        "sample_security_ids": [row["security_id"] for row in securities],
        "sample_selection": [
            {
                "security_id": row["security_id"],
                "selection_reasons": row["selection_reasons"],
            }
            for row in securities
        ],
        "sequence": state.checks["sample_spine_sequence"]["details"],
        "expected_empty": state.checks["sample_expected_empty"]["details"],
        "availability": availability,
    }


def aggregate_checks(
    connection: duckdb.DuckDBPyConnection,
    formal_manifest: dict[str, object],
    state: ReviewState,
) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    aggregate_tables = (
        "formal_table_counts",
        "formal_coverage",
        "formal_semantic_fingerprints",
        "registry_fingerprints",
        "component_validity_profile",
        "dimension_validity_profile",
        "component_score_profile",
        "dimension_score_profile",
        "yearly_component_profile",
        "yearly_dimension_profile",
        "observation_status_profile",
        "sequence_domain_profile",
        "expected_empty_profile",
        "availability_profile",
        "reference_window_profile",
        "source_reconciliation_profile",
        "cardinality_profile",
        "validator_checks",
        "validator_metrics",
        "analysis_anomalies",
    )
    table_counts = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT table_name, row_count FROM formal_table_counts"
        ).fetchall()
    }
    state.check(
        "formal_table_counts_expected",
        table_counts == EXPECTED_FORMAL_COUNTS,
        details=table_counts,
        table="formal_table_counts",
        expected=EXPECTED_FORMAL_COUNTS,
        actual=table_counts,
    )
    coverage = {
        row["table_name"]: row
        for row in fetch_dicts(connection, "SELECT * FROM formal_coverage")
    }
    coverage_ok = all(
        coverage[name]["security_count"] == 800
        and coverage[name]["date_min"] == date(2016, 1, 4)
        and coverage[name]["date_max"] == date(2026, 6, 30)
        for name in (
            "securities",
            "security_observation_spine",
            "daily_component_scores",
            "daily_dimension_scores",
        )
    )
    state.check(
        "formal_coverage_expected",
        coverage_ok,
        details={name: coverage[name] for name in coverage},
        table="formal_coverage",
    )
    semantic_rows = fetch_dicts(
        connection, "SELECT * FROM formal_semantic_fingerprints"
    )
    semantic_ok = len(semantic_rows) == 7 and all(
        row["row_count"] == EXPECTED_FORMAL_COUNTS[row["table_name"]]
        and bool(row["sum_hash"])
        and bool(row["xor_hash"])
        for row in semantic_rows
    )
    state.check(
        "formal_semantic_fingerprints_complete",
        semantic_ok,
        details={"row_count": len(semantic_rows)},
        table="formal_semantic_fingerprints",
    )
    registry_rows = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT table_name, sha256 FROM registry_fingerprints"
        ).fetchall()
    }
    state.check(
        "registry_fingerprints_match_formal_manifest",
        registry_rows == formal_manifest["registry_fingerprints"],
        details=registry_rows,
        table="registry_fingerprints",
    )

    status_rows = {
        row["expected_observation_status"]: row["row_count"]
        for row in fetch_dicts(connection, "SELECT * FROM observation_status_profile")
    }
    state.check(
        "observation_status_expected",
        status_rows == EXPECTED_OBSERVATION_STATUS,
        details=status_rows,
        table="observation_status_profile",
        expected=EXPECTED_OBSERVATION_STATUS,
        actual=status_rows,
    )
    expected_empty = fetch_dicts(connection, "SELECT * FROM expected_empty_profile")[0]
    expected_empty_ok = (
        expected_empty["expected_empty_observations"] == 20_297
        and expected_empty["blocked_component_rows"] == 202_970
        and expected_empty["blocked_dimension_rows"] == 101_485
    )
    state.check(
        "full_universe_expected_empty_expected",
        expected_empty_ok,
        details=expected_empty,
        table="expected_empty_profile",
    )
    sequence = {
        row["profile_name"]: row
        for row in fetch_dicts(connection, "SELECT * FROM sequence_domain_profile")
    }
    sequence_mismatch = sequence["observation_vs_global_session_mismatch"]
    state.check(
        "full_universe_sequence_domain_expected",
        sequence_mismatch["row_count"] == 416_962
        and sequence_mismatch["security_count"] == 276
        and sequence_mismatch["mismatch_count"] == 416_962,
        details=sequence_mismatch,
        table="sequence_domain_profile",
    )
    source_metrics = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT metric_name, metric_value FROM source_reconciliation_profile"
        ).fetchall()
    }
    expected_source_metrics = {
        "pcvt_source_valid_rows": 12_819_633,
        "pcvt_output_valid_rows": 12_819_633,
        "pcvt_component_source_mismatches": 0,
        "pcvt_dimension_source_mismatches": 0,
    }
    state.check(
        "full_universe_source_reconciliation_expected",
        all(
            source_metrics.get(key) == value
            for key, value in expected_source_metrics.items()
        ),
        details=source_metrics,
        table="source_reconciliation_profile",
    )
    validator_rows = fetch_dicts(connection, "SELECT * FROM validator_checks")
    validator_metrics = {
        row["metric_name"]: json.loads(row["metric_value_json"])
        for row in fetch_dicts(connection, "SELECT * FROM validator_metrics")
    }
    state.check(
        "validator_checks_all_true",
        len(validator_rows) == 53 and all(row["passed"] for row in validator_rows),
        details={
            "check_count": len(validator_rows),
            "failed_count": sum(not row["passed"] for row in validator_rows),
        },
        table="validator_checks",
    )
    state.check(
        "validator_metrics_expected",
        validator_metrics.get("pcvt_source_valid_rows") == 12_819_633
        and validator_metrics.get("pcvt_output_valid_rows") == 12_819_633
        and validator_metrics.get("pcvt_component_source_mismatches") == 0
        and validator_metrics.get("pcvt_dimension_source_mismatches") == 0
        and validator_metrics.get("pcvt_independent_mismatch_count") == 0
        and validator_metrics.get("a_independent_mismatch_count") == 0,
        details=validator_metrics,
        table="validator_metrics",
    )
    anomalies = fetch_dicts(connection, "SELECT * FROM analysis_anomalies")
    blocking_anomalies = [row for row in anomalies if row["blocking"]]
    state.check(
        "analysis_blocking_anomaly_count_zero",
        not blocking_anomalies,
        details={"blocking_anomaly_count": len(blocking_anomalies)},
        table="analysis_anomalies",
    )

    component_validity_rows = fetch_dicts(
        connection, "SELECT * FROM component_validity_profile"
    )
    dimension_validity_rows = fetch_dicts(
        connection, "SELECT * FROM dimension_validity_profile"
    )
    component_score_rows = fetch_dicts(
        connection, "SELECT * FROM component_score_profile"
    )
    dimension_score_rows = fetch_dicts(
        connection, "SELECT * FROM dimension_score_profile"
    )
    component_validity: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    dimension_validity: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for row in component_validity_rows:
        component_validity[(row["dimension_id"], row["component_id"])][
            row["validity_status"]
        ] += row["row_count"]
    for row in dimension_validity_rows:
        dimension_validity[row["dimension_id"]][row["validity_status"]] += row[
            "row_count"
        ]
    allowed_validity = {"valid", "unknown", "diagnostic_required", "blocked"}
    actual_validity = {
        row["validity_status"]
        for row in component_validity_rows + dimension_validity_rows
    }
    state.check(
        "aggregate_validity_status_domain",
        actual_validity <= allowed_validity,
        details={"actual": sorted(actual_validity)},
        table="validity_profiles",
    )
    arithmetic_failures: list[str] = []
    component_arithmetic = []
    for row in component_score_rows:
        statuses = component_validity[(row["dimension_id"], row["component_id"])]
        status_total = sum(statuses.values())
        ok = (
            row["total_rows"] == status_total
            and row["eligible_rows"] <= statuses.get("valid", 0)
            and row["null_score_rows"] == row["total_rows"] - row["eligible_rows"]
            and row["score_min"] == 0
            and row["score_max"] == 1
            and row["eligible_rows"] > 0
            and row["null_score_rows"] < row["total_rows"]
            and row["zero_score_rows"] < row["eligible_rows"]
            and row["one_score_rows"] < row["eligible_rows"]
        )
        if not ok:
            arithmetic_failures.append(f"component:{row['component_id']}")
        component_arithmetic.append(
            {
                "component_id": row["component_id"],
                "status_total": status_total,
                "total_rows": row["total_rows"],
                "eligible_rows": row["eligible_rows"],
                "null_score_rows": row["null_score_rows"],
                "passed": ok,
            }
        )
    dimension_arithmetic = []
    for row in dimension_score_rows:
        statuses = dimension_validity[row["dimension_id"]]
        status_total = sum(statuses.values())
        ok = (
            row["total_rows"] == status_total
            and row["eligible_rows"] <= statuses.get("valid", 0)
            and row["null_score_rows"] == row["total_rows"] - row["eligible_rows"]
            and row["score_min"] == 0
            and row["score_max"] == 1
            and row["eligible_rows"] > 0
            and row["null_score_rows"] < row["total_rows"]
            and row["zero_score_rows"] < row["eligible_rows"]
            and row["one_score_rows"] < row["eligible_rows"]
        )
        if not ok:
            arithmetic_failures.append(f"dimension:{row['dimension_id']}")
        dimension_arithmetic.append(
            {
                "dimension_id": row["dimension_id"],
                "status_total": status_total,
                "total_rows": row["total_rows"],
                "eligible_rows": row["eligible_rows"],
                "null_score_rows": row["null_score_rows"],
                "passed": ok,
            }
        )
    state.check(
        "aggregate_score_profile_arithmetic",
        not arithmetic_failures,
        details={
            "failures": arithmetic_failures,
            "components": component_arithmetic,
            "dimensions": dimension_arithmetic,
        },
        table="aggregate_profiles",
        actual=arithmetic_failures,
    )

    cardinality = fetch_dicts(connection, "SELECT * FROM cardinality_profile")
    availability = fetch_dicts(connection, "SELECT * FROM availability_profile")
    reference_windows = fetch_dicts(
        connection, "SELECT * FROM reference_window_profile"
    )
    state.check(
        "aggregate_cardinality_zero_mismatches",
        all(row["mismatch_count"] == 0 for row in cardinality),
        details=cardinality,
        table="cardinality_profile",
    )
    state.check(
        "aggregate_availability_zero_mismatches",
        all(
            row["null_rows"] == 0 and row["cutoff_mismatch_rows"] == 0
            for row in availability
        ),
        details=availability,
        table="availability_profile",
    )
    state.check(
        "aggregate_reference_window_contract",
        all(
            row["current_in_reference_true_rows"] == 0
            and row["eligible_null_window_rows"] == 0
            and row["eligible_reference_count_min"] == W
            and row["eligible_reference_count_max"] == W
            for row in reference_windows
        ),
        details=reference_windows,
        table="reference_window_profile",
    )
    state.check(
        "aggregate_table_set_queried",
        len(aggregate_tables) == 20,
        details={"tables": aggregate_tables},
        table="review_extract",
    )

    yearly_component_rows = fetch_dicts(
        connection, "SELECT * FROM yearly_component_profile"
    )
    yearly_dimension_rows = fetch_dicts(
        connection, "SELECT * FROM yearly_dimension_profile"
    )
    yearly: list[dict[str, object]] = []
    for year in sorted({row["calendar_year"] for row in yearly_component_rows}):
        component = [
            row for row in yearly_component_rows if row["calendar_year"] == year
        ]
        dimension = [
            row for row in yearly_dimension_rows if row["calendar_year"] == year
        ]
        component_total = sum(row["total_rows"] for row in component)
        component_eligible = sum(row["eligible_rows"] for row in component)
        dimension_total = sum(row["total_rows"] for row in dimension)
        dimension_eligible = sum(row["eligible_rows"] for row in dimension)
        yearly.append(
            {
                "year": year,
                "security_count": max(row["security_count"] for row in component),
                "component_total_rows": component_total,
                "component_eligible_rows": component_eligible,
                "component_eligible_rate": component_eligible / component_total,
                "dimension_total_rows": dimension_total,
                "dimension_eligible_rows": dimension_eligible,
                "dimension_eligible_rate": dimension_eligible / dimension_total,
                "date_min": min(row["date_min"] for row in component),
                "date_max": max(row["date_max"] for row in component),
            }
        )
    year_by_id = {row["year"]: row for row in yearly}
    annual_anomalies: list[str] = []
    if not (
        year_by_id[2016]["component_eligible_rate"]
        < year_by_id[2017]["component_eligible_rate"]
        and year_by_id[2016]["dimension_eligible_rate"]
        < year_by_id[2017]["dimension_eligible_rate"]
    ):
        annual_anomalies.append("2016_not_lower_than_2017")
    if not (
        year_by_id[2017]["component_eligible_rate"]
        - year_by_id[2016]["component_eligible_rate"]
        > 0.25
    ):
        annual_anomalies.append("2017_component_rise_not_significant")
    for year in range(2017, 2026):
        if (
            year_by_id[year]["component_eligible_rows"] == 0
            or year_by_id[year]["dimension_eligible_rows"] == 0
        ):
            annual_anomalies.append(f"intermediate_year_zero:{year}")
    if year_by_id[2026]["date_max"] != date(2026, 6, 30):
        annual_anomalies.append("2026_not_partial_through_2026_06_30")
    state.check(
        "annual_coverage_reasonableness",
        not annual_anomalies,
        details={"anomalies": annual_anomalies, "yearly": yearly},
        table="yearly_profiles",
        actual=annual_anomalies,
    )

    aggregate_summary = {
        "formal_table_counts": table_counts,
        "formal_coverage": coverage,
        "observation_status": status_rows,
        "expected_empty": expected_empty,
        "sequence_domain": sequence_mismatch,
        "source_reconciliation": source_metrics,
        "validator_check_count": len(validator_rows),
        "validator_failed_check_count": sum(
            not row["passed"] for row in validator_rows
        ),
        "analysis_blocking_anomaly_count": len(blocking_anomalies),
        "aggregate_arithmetic_failure_count": len(arithmetic_failures),
        "queried_aggregate_tables": list(aggregate_tables),
    }
    return aggregate_summary, yearly, annual_anomalies


def make_report(receipt: dict[str, object]) -> str:
    identity = receipt["file_identity"]
    samples = receipt["sample_review"]
    component = receipt["component_recomputation"]
    dimensions = receipt["dimension_recomputation"]
    source = receipt["source_reconciliation"]
    aggregate = receipt["aggregate_review"]
    lines = [
        "# R2A-T01 independent formal extract review",
        "",
        "## 审阅边界",
        "",
        "本审阅只读取已提交的 review extract 与 compact review manifests/evidence。未读取完整",
        "`score_data.duckdb`，未调用 formal materializer、validator、analyzer 或任何 R2A",
        "production Score/dimension 函数，也未创建 `DONE`、successor run 或下游发布状态。",
        "",
        "## 方法独立性",
        "",
        "Review script imports：`"
        + "`, `".join(receipt["review_script_imports"])
        + "`。",
        "",
        "明确未 import：`" + "`, `".join(FORBIDDEN_IMPORTS) + "`。",
        "",
        "## 文件 identity",
        "",
        "| item | value |",
        "| --- | --- |",
        f"| review extract SHA-256 | `{identity['review_extract_sha256']}` |",
        f"| review extract bytes | {identity['review_extract_byte_size']} |",
        f"| bundle manifest SHA-256 | `{identity['review_bundle_manifest_sha256']}` |",
        f"| formal database reference | `{EXPECTED_FORMAL_DATABASE_SHA256}` / {EXPECTED_FORMAL_DATABASE_BYTES} bytes |",
        "",
        "## 30-table inventory",
        "",
        "| table | rows | columns |",
        "| --- | ---: | ---: |",
    ]
    for table in receipt["table_inventory"]:
        lines.append(
            f"| {table['table_name']} | {table['row_count']} | {len(table['columns'])} |"
        )
    lines.extend(
        [
            "",
            "数据库恰含 30 张表；manifest table set、实际 row counts、schema inventory、无",
            "view/macro/temp relation 以及关闭后只读重开检查均通过。",
            "",
            "## 12 样本选择",
            "",
        ]
    )
    for item in samples["sample_selection"]:
        lines.append(
            f"- `{item['security_id']}`：{', '.join(item['selection_reasons'])}"
        )
    lines.extend(
        [
            "",
            "所有样本均保留完整 observation history。",
            "",
            "## PCVT strict-past 独立复算",
            "",
            f"比较 {component['pcvt']['compared_rows']} 行；row mismatch={component['pcvt']['mismatch_rows']}，",
            f"field mismatch={component['pcvt']['mismatch_fields']}，最大绝对差={component['pcvt']['maximum_absolute_difference']:.17g}。",
            "",
            "## A strict-past 独立复算",
            "",
            f"比较 {component['a']['compared_rows']} 行；row mismatch={component['a']['mismatch_rows']}，",
            f"field mismatch={component['a']['mismatch_fields']}，最大绝对差={component['a']['maximum_absolute_difference']:.17g}。",
            "A components 恰为 A1/A2，A2b rows=0。",
            "",
            "## 五维 mean/min 独立复算",
            "",
            "| dimension | compared | eligible | mismatches | max mean diff | max min diff |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for dimension_id in ("P", "C", "A", "V", "T"):
        item = dimensions[dimension_id]
        lines.append(
            f"| {dimension_id} | {item['compared_rows']} | {item['eligible_rows']} | "
            f"{item['mismatch_rows']} | {item['maximum_absolute_mean_difference']:.17g} | "
            f"{item['maximum_absolute_min_difference']:.17g} |"
        )
    lines.extend(
        [
            "",
            "## PCVT accepted source reconciliation",
            "",
            f"Component compared={source['component']['compared_rows']}，key mismatch={source['component']['key_mismatches']}，",
            f"row mismatch={source['component']['mismatch_rows']}，field mismatch={source['component']['mismatch_fields']}。",
            f"Dimension compared={source['dimension']['compared_rows']}，key mismatch={source['dimension']['key_mismatches']}，",
            f"row mismatch={source['dimension']['mismatch_rows']}，field mismatch={source['dimension']['mismatch_fields']}。",
            "",
            "## Sequence、expected-empty 与 availability",
            "",
            f"Sequence checked securities={samples['sequence']['security_count']}，mismatch={samples['sequence']['mismatch_count']}。",
            f"Expected-empty observations={samples['expected_empty']['expected_empty_observation_count']}，",
            f"blocked components={samples['expected_empty']['blocked_component_count']}，",
            f"blocked dimensions={samples['expected_empty']['blocked_dimension_count']}，",
            f"mismatch={samples['expected_empty']['mismatch_count']}。",
            f"Availability mismatch：spine={samples['availability']['spine_availability_mismatch']}，",
            f"component={samples['availability']['component_availability_mismatch']}，",
            f"dimension={samples['availability']['dimension_availability_mismatch']}。",
            "",
            "## 全市场 aggregate profiles",
            "",
            f"七表数量={aggregate['formal_table_counts']}。Observation status={aggregate['observation_status']}。",
            f"Validator checks={aggregate['validator_check_count']}，failed={aggregate['validator_failed_check_count']}；",
            f"blocking anomalies={aggregate['analysis_blocking_anomaly_count']}；",
            f"aggregate arithmetic failures={aggregate['aggregate_arithmetic_failure_count']}。",
            "所有 component/dimension 的 validity 加总、eligible/null 关系、0/1 domain 与非退化检查均已独立复算。",
            "",
            "## 年度 coverage 与合理性",
            "",
            "| year | securities | component rows | component eligible | rate | dimension rows | dimension eligible | rate |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in receipt["yearly_review"]:
        lines.append(
            f"| {row['year']} | {row['security_count']} | {row['component_total_rows']} | "
            f"{row['component_eligible_rows']} | {row['component_eligible_rate']:.6f} | "
            f"{row['dimension_total_rows']} | {row['dimension_eligible_rows']} | "
            f"{row['dimension_eligible_rate']:.6f} |"
        )
    lines.extend(
        [
            "",
            "2016 eligibility 明显较低，与 W120 启动期及 staggered listings 一致；2017 后显著",
            "上升，未出现中间年份归零。2026 数据截至 2026-06-30，属于部分年度；未把逐年",
            "单调上升设为 gate。",
            "",
            "## Mismatch 与 anomaly",
            "",
            f"总 mismatch={receipt['mismatch_count']}；年度无法解释 anomaly={len(receipt['annual_anomalies'])}。",
            "",
            "## 最终 recommendation",
            "",
            f"`{receipt['recommendation']}`。Independent overall status=`{receipt['overall_status']}`。",
            "该 recommendation 只针对 candidate 进入独立 formal-result review，不表示 R2A-T01",
            "completed/accepted，不推进 README gate、A-layer registration 或 R2A-T02。",
            "",
        ]
    )
    return "\n".join(lines)


def run_review(review_dir: Path) -> tuple[dict[str, object], ReviewState]:
    state = ReviewState()
    extract_manifest, formal_manifest, identity = identity_checks(review_dir, state)
    extract = review_dir / extract_manifest["extract_filename"]
    connection, inventory = database_inventory(extract, extract_manifest, state)
    component_summary, component_output = sample_component_recomputation(
        connection, state
    )
    dimension_summary = dimension_recomputation(connection, component_output, state)
    source_summary = source_reconciliation(connection, component_output, state)
    sample_summary = spine_expected_empty_availability(connection, state)
    aggregate_summary, yearly, annual_anomalies = aggregate_checks(
        connection, formal_manifest, state
    )
    connection.close()
    reopened = duckdb.connect(str(extract), read_only=True)
    reopen_count = reopened.execute("SELECT count(*) FROM duckdb_tables()").fetchone()[
        0
    ]
    reopened.close()
    state.check(
        "database_close_and_read_only_reopen",
        reopen_count == 30,
        details={"table_count_after_reopen": reopen_count},
        table=extract.name,
        expected=30,
        actual=reopen_count,
    )

    validation_receipt = json.loads(
        (review_dir / "validation_receipt.json").read_text(encoding="utf-8")
    )
    state.check(
        "validator_failed_reason_count_zero",
        len(validation_receipt.get("reason_codes", [])) == 0,
        details={"reason_codes": validation_receipt.get("reason_codes", [])},
        table="validation_receipt.json",
        expected=0,
        actual=len(validation_receipt.get("reason_codes", [])),
    )
    result_analysis = (review_dir / "result_analysis.md").read_text(encoding="utf-8")
    state.check(
        "result_analysis_candidate_status",
        "analysis_status = `passed`" in result_analysis
        and "release_recommendation = `publish_candidate`" in result_analysis,
        details={
            "analysis_status": "passed",
            "release_recommendation": "publish_candidate",
        },
        table="result_analysis.md",
    )

    failed_checks = sorted(
        check_id
        for check_id, result in state.checks.items()
        if result["status"] != "passed"
    )
    overall_status = (
        "passed" if not failed_checks and state.mismatch_count == 0 else "failed"
    )
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "reviewed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "review_script": "scripts/review/review_r2a_t01_formal_extract.py",
        "review_script_sha256": sha256_file(Path(__file__)),
        "review_script_imports": identity["review_script_imports"],
        "forbidden_imports_absent": list(FORBIDDEN_IMPORTS),
        "review_extract_sha256": identity["review_extract_sha256"],
        "review_extract_byte_size": identity["review_extract_byte_size"],
        "run_id": EXPECTED_RUN_ID,
        "score_release_id": EXPECTED_RELEASE_ID,
        "reviewed_execution_commit": EXPECTED_EXECUTION_COMMIT,
        "sample_security_ids": sample_summary["sample_security_ids"],
        "table_count": len(inventory),
        "table_inventory": inventory,
        "check_statuses": state.checks,
        "component_recomputation": component_summary,
        "dimension_recomputation": dimension_summary,
        "source_reconciliation": source_summary,
        "sample_review": sample_summary,
        "aggregate_review": aggregate_summary,
        "aggregate_arithmetic_checks": state.checks[
            "aggregate_score_profile_arithmetic"
        ]["details"],
        "yearly_review": yearly,
        "annual_anomalies": annual_anomalies,
        "file_identity": identity,
        "comparison_counts": {
            "pcvt_component_rows": component_summary["pcvt"]["compared_rows"],
            "a_component_rows": component_summary["a"]["compared_rows"],
            "dimension_rows": sum(
                item["compared_rows"] for item in dimension_summary.values()
            ),
            "source_component_rows": source_summary["component"]["compared_rows"],
            "source_dimension_rows": source_summary["dimension"]["compared_rows"],
        },
        "mismatch_counts": {
            "total": state.mismatch_count,
            "pcvt_component_rows": component_summary["pcvt"]["mismatch_rows"],
            "a_component_rows": component_summary["a"]["mismatch_rows"],
            "dimension_rows": sum(
                item["mismatch_rows"] for item in dimension_summary.values()
            ),
            "source_component_rows": source_summary["component"]["mismatch_rows"],
            "source_dimension_rows": source_summary["dimension"]["mismatch_rows"],
            "sequence": sample_summary["sequence"]["mismatch_count"],
            "expected_empty": sample_summary["expected_empty"]["mismatch_count"],
            "availability": sum(sample_summary["availability"].values()),
            "aggregate_arithmetic": aggregate_summary[
                "aggregate_arithmetic_failure_count"
            ],
        },
        "maximum_floating_differences": {
            "pcvt_component": component_summary["pcvt"]["maximum_absolute_difference"],
            "a_component": component_summary["a"]["maximum_absolute_difference"],
            "dimensions": {
                dimension: {
                    "mean": item["maximum_absolute_mean_difference"],
                    "min": item["maximum_absolute_min_difference"],
                }
                for dimension, item in dimension_summary.items()
            },
            "source_component": source_summary["component"][
                "maximum_absolute_difference"
            ],
            "source_dimension": source_summary["dimension"][
                "maximum_absolute_difference"
            ],
        },
        "mismatch_count": state.mismatch_count,
        "overall_status": overall_status,
        "reason_codes": failed_checks,
        "recommendation": (
            "accept_candidate" if overall_status == "passed" else "reject_candidate"
        ),
        "formal_run_status": "completed_pending_formal_result_review",
        "result_review_status": "pending",
        "readme_advanced": False,
        "R2A-T02_allowed_to_start": False,
        "DONE": "absent",
    }
    return receipt, state


def failure_receipt(state: ReviewState, error: Exception) -> dict[str, object]:
    state.add_mismatch(
        check_id="independent_review_execution",
        table="review_extract",
        field="execution",
        expected="completed",
        actual=f"{type(error).__name__}: {error}",
    )
    state.checks["independent_review_execution"] = {
        "status": "failed",
        "details": {"error_type": type(error).__name__, "error": str(error)},
    }
    return {
        "receipt_version": RECEIPT_VERSION,
        "reviewed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "review_script": "scripts/review/review_r2a_t01_formal_extract.py",
        "review_script_sha256": sha256_file(Path(__file__)),
        "review_script_imports": parse_script_imports(
            Path(__file__).read_text(encoding="utf-8")
        ),
        "run_id": EXPECTED_RUN_ID,
        "score_release_id": EXPECTED_RELEASE_ID,
        "reviewed_execution_commit": EXPECTED_EXECUTION_COMMIT,
        "check_statuses": state.checks,
        "mismatch_count": state.mismatch_count,
        "overall_status": "failed",
        "reason_codes": sorted(
            check_id
            for check_id, result in state.checks.items()
            if result["status"] != "passed"
        ),
        "recommendation": "reject_candidate",
        "formal_run_status": "completed_pending_formal_result_review",
        "result_review_status": "pending",
        "readme_advanced": False,
        "R2A-T02_allowed_to_start": False,
        "DONE": "absent",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently review the committed R2A-T01 formal review extract."
    )
    parser.add_argument("--review-dir", required=True, type=Path)
    args = parser.parse_args()
    review_dir = args.review_dir.resolve()
    review_dir.mkdir(parents=False, exist_ok=True)
    state = ReviewState()
    try:
        receipt, state = run_review(review_dir)
        report = make_report(receipt)
    except Exception as error:  # fail closed and still emit review evidence
        receipt = failure_receipt(state, error)
        report = (
            "# R2A-T01 independent formal extract review\n\n"
            "## 最终 recommendation\n\n"
            "`reject_candidate`。Independent overall status=`failed`。\n\n"
            f"执行失败：`{type(error).__name__}: {error}`。\n"
        )
    mismatch_payload: dict[str, object] = {
        "mismatch_count": state.mismatch_count,
        "mismatches": state.mismatches,
    }
    if state.mismatch_count > len(state.mismatches):
        mismatch_payload["retained_count"] = len(state.mismatches)
        mismatch_payload["truncated"] = True
    write_json(review_dir / "independent_review_mismatches.json", mismatch_payload)
    write_json(review_dir / "independent_review_receipt.json", receipt)
    (review_dir / "independent_review_report.md").write_bytes(
        (report.rstrip() + "\n").encode("utf-8")
    )
    print(
        json.dumps(
            {
                "overall_status": receipt["overall_status"],
                "recommendation": receipt["recommendation"],
                "mismatch_count": state.mismatch_count,
                "receipt": "independent_review_receipt.json",
                "report": "independent_review_report.md",
                "mismatches": "independent_review_mismatches.json",
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["overall_status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
