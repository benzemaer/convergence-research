# ruff: noqa: E501
"""Independent validator for EXP-A03 compact packages.

This module has its own SQL for the common universe, correlations, tails and
variance decomposition.  It does not import producer query builders or
decision functions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

TASK_ID = "EXP-A03"
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "configs/sidecar/exp_a03_candidate_intralayer_redundancy_selection.v1.json"
)
CONFIG_SCHEMA = (
    ROOT
    / "schemas/sidecar/exp_a03_candidate_intralayer_redundancy_selection.schema.json"
)
MANIFEST_SCHEMA = ROOT / "schemas/sidecar/exp_a03_authorized_input_manifest.schema.json"
HANDOFF_SCHEMA = ROOT / "schemas/sidecar/exp_a02_accepted_result_handoff.schema.json"
RAW_TABLE = "exp_a01_raw_metrics"
A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
PAIR_DEFS = {
    "A1_A2": (A1_ID, A2_ID, "a1", "a2"),
    "A1_A2b": (A1_ID, A2B_ID, "a1", "a2b"),
    "A2_A2b": (A2_ID, A2B_ID, "a2", "a2b"),
}
EXPECTED_INPUTS = (
    "exp_a02_accepted_result_handoff",
    "exp_a02_manifest",
    "exp_a02_validator_result",
    "exp_a02_anomaly_scan",
    "exp_a01_raw_metrics",
)
OUTPUT_FILES = (
    "exp_a03_pairwise_overall.csv",
    "exp_a03_pairwise_year.csv",
    "exp_a03_pairwise_security.csv",
    "exp_a03_tail_overlap.csv",
    "exp_a03_a2_a2b_conditional_profile.csv",
    "exp_a03_a2_a2b_variance_decomposition.csv",
    "exp_a03_stability_summary.csv",
    "exp_a03_candidate_disposition.json",
    "exp_a03_manifest.json",
    "exp_a03_validator_result.json",
    "exp_a03_anomaly_scan.json",
    "exp_a03_result_analysis.md",
)
CSV_FIELDS = {
    "exp_a03_pairwise_overall.csv": (
        "pair_id",
        "left_indicator_id",
        "right_indicator_id",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "left_unique_value_count",
        "right_unique_value_count",
        "left_tied_row_count",
        "right_tied_row_count",
    ),
    "exp_a03_pairwise_year.csv": (
        "pair_id",
        "calendar_year",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
    ),
    "exp_a03_pairwise_security.csv": (
        "pair_id",
        "security_id",
        "common_count",
        "eligible",
        "pearson_raw",
        "spearman_midrank",
        "reason",
    ),
    "exp_a03_tail_overlap.csv": (
        "pair_id",
        "tail_fraction",
        "left_indicator_id",
        "right_indicator_id",
        "left_threshold",
        "right_threshold",
        "left_selected_count",
        "left_realized_rate",
        "right_selected_count",
        "right_realized_rate",
        "intersection_count",
        "union_count",
        "jaccard",
        "left_containment",
        "right_containment",
    ),
    "exp_a03_a2_a2b_conditional_profile.csv": (
        "a2_level",
        "row_count",
        "row_share",
        "a2b_min",
        "a2b_q05",
        "a2b_q25",
        "a2b_median",
        "a2b_q75",
        "a2b_q95",
        "a2b_max",
        "a2b_mean",
        "a2b_stddev_pop",
        "a2b_unique_value_count",
    ),
    "exp_a03_a2_a2b_variance_decomposition.csv": (
        "global_mean",
        "total_ss",
        "between_group_ss",
        "within_group_ss",
        "eta_squared",
        "within_variance_ratio",
        "reconciliation_residual",
    ),
    "exp_a03_stability_summary.csv": (
        "pair_id",
        "overall_pearson",
        "overall_spearman",
        "year_count",
        "year_spearman_min",
        "year_spearman_q25",
        "year_spearman_median",
        "year_spearman_q75",
        "year_spearman_max",
        "year_negative_count",
        "security_total_count",
        "security_eligible_count",
        "security_insufficient_count",
        "security_spearman_q10",
        "security_spearman_q25",
        "security_spearman_median",
        "security_spearman_q75",
        "security_spearman_q90",
        "security_negative_count",
    ),
}
SHA64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
A2_GRID_TOLERANCE = 1e-10


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_text_errors(raw: bytes) -> list[str]:
    errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("BOM")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("UTF-8")
    if b"\r" in raw:
        errors.append("CR_or_CRLF")
    if not raw.endswith(b"\n"):
        errors.append("missing_final_LF")
    if raw.endswith(b"\n\n"):
        errors.append("multiple_final_LF")
    return errors


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    errors = canonical_text_errors(raw)
    if errors:
        raise ValueError(f"non-canonical text {path}: {','.join(errors)}")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def validate_static_config(config: Mapping[str, Any]) -> list[str]:
    try:
        schema = load_json(CONFIG_SCHEMA)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(config)
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]
    return []


def _resolve(
    declaration: Mapping[str, Any], manifest_path: Path, input_root: Path | None
) -> Path:
    declared = str(declaration["path"])
    path = Path(declared)
    policy = declaration["path_policy"]
    if policy == "absolute_declared_path":
        if not path.is_absolute():
            raise ValueError("absolute_declared_path requires an absolute path")
    elif policy == "relative_to_manifest":
        if path.is_absolute():
            raise ValueError("relative_to_manifest forbids an absolute path")
        path = manifest_path.parent / path
    elif policy == "basename_local_only":
        if path.name != declared or path.is_absolute():
            raise ValueError("basename_local_only requires a basename")
        path = (input_root or manifest_path.parent) / path.name
    elif policy == "synthetic_fixture":
        path = (input_root or manifest_path.parent) / path.name
    else:
        raise ValueError(f"unsupported path policy: {policy}")
    return path.resolve()


def _require(payload: Mapping[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"{label} missing: {','.join(missing)}")


def _read_csv(path: Path, filename: str) -> list[dict[str, str]]:
    fields = CSV_FIELDS[filename]
    errors = canonical_text_errors(path.read_bytes())
    if errors:
        raise ValueError(f"non-canonical CSV {path}: {','.join(errors)}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f"CSV header mismatch: {filename}")
        return [dict(row) for row in reader]


def _validate_handoff(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    schema = load_json(HANDOFF_SCHEMA)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    return payload


def prepare_input_manifest(
    manifest_path: Path,
    *,
    input_root: Path | None = None,
    allow_synthetic_fixture: bool = False,
    allow_formal_run: bool = False,
    reviewed_implementation_sha: str | None = None,
) -> dict[str, Any]:
    """Check all JSON/text/hash lineage before opening the raw database."""
    manifest_path = manifest_path.resolve()
    manifest = load_json(manifest_path)
    schema = load_json(MANIFEST_SCHEMA)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
    synthetic = manifest["manifest_type"] == "exp_a03_synthetic_input_manifest"
    if synthetic and not allow_synthetic_fixture:
        raise ValueError("synthetic fixture flag is required")
    if not synthetic and not allow_formal_run:
        raise ValueError("formal flag is required")
    auth = manifest["authorization"]
    if synthetic and (
        auth["status"] != "synthetic_fixture_only" or auth["formal_run_allowed"]
    ):
        raise ValueError("synthetic authorization mismatch")
    if not synthetic and (
        auth["status"] != "approved" or not auth["formal_run_allowed"]
    ):
        raise ValueError("formal authorization mismatch")
    if reviewed_implementation_sha is not None and not SHA40.fullmatch(
        reviewed_implementation_sha
    ):
        raise ValueError("reviewed implementation SHA format mismatch")
    if (
        not synthetic
        and auth.get("reviewed_implementation_sha") != reviewed_implementation_sha
    ):
        raise ValueError("manifest reviewed implementation SHA mismatch")
    declarations = manifest["input_artifacts"]
    if set(declarations) != set(EXPECTED_INPUTS) or len(declarations) != 5:
        raise ValueError("A03 manifest must contain exactly five artifacts")
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_id in EXPECTED_INPUTS:
        declaration = declarations[artifact_id]
        if declaration.get("artifact_id") != artifact_id or not SHA64.fullmatch(
            str(declaration.get("sha256", ""))
        ):
            raise ValueError(f"artifact declaration mismatch: {artifact_id}")
        path = _resolve(declaration, manifest_path, input_root)
        if not path.is_file() or path.name != declaration["filename"]:
            raise FileNotFoundError(
                f"missing or filename-mismatched artifact: {artifact_id}"
            )
        actual = sha256_file(path)
        if actual != declaration["sha256"]:
            raise ValueError(f"input artifact SHA mismatch: {artifact_id}")
        paths[artifact_id], hashes[artifact_id] = path, actual
        if (
            declaration["artifact_kind"].endswith("json")
            or declaration["artifact_kind"] == "handoff_json"
        ):
            payloads[artifact_id] = load_json(path)
    handoff = _validate_handoff(paths["exp_a02_accepted_result_handoff"])
    a02_manifest = payloads["exp_a02_manifest"]
    a02_validator = payloads["exp_a02_validator_result"]
    a02_anomaly = payloads["exp_a02_anomaly_scan"]
    if (
        a02_manifest.get("task_id") != "EXP-A02"
        or a02_manifest.get("run_id") != handoff["accepted_run_id"]
        or a02_manifest.get("validator_status") != "passed"
        or a02_manifest.get("anomaly_status") != "passed"
    ):
        raise ValueError("A02 manifest binding/status mismatch")
    if (
        a02_validator.get("status") != "passed"
        or a02_validator.get("valid") is not True
        or a02_anomaly.get("status") != "passed"
    ):
        raise ValueError("A02 validator/anomaly binding/status mismatch")
    binding = manifest["cross_artifact_bindings"]
    expected_artifact_hashes = {
        "a02_manifest_sha256": hashes["exp_a02_manifest"],
        "a02_validator_sha256": hashes["exp_a02_validator_result"],
        "a02_anomaly_sha256": hashes["exp_a02_anomaly_scan"],
    }
    for field, value in expected_artifact_hashes.items():
        if binding[field] != value:
            raise ValueError(f"{field} mismatch")
    raw_declaration = declarations["exp_a01_raw_metrics"]
    if binding["a01_raw_sha256"] != raw_declaration["sha256"]:
        raise ValueError("A01 raw SHA declaration/binding mismatch")
    if synthetic:
        synthetic_bindings = {
            "a01_raw_row_count": raw_declaration.get("row_count"),
            "expected_key_count": raw_declaration.get("expected_key_count"),
            "triple_common_valid_count": raw_declaration.get("expected_key_count"),
            "security_count": raw_declaration.get("security_count"),
            "date_min": raw_declaration.get("date_min"),
            "date_max": raw_declaration.get("date_max"),
        }
        for field, value in synthetic_bindings.items():
            if value is not None and str(binding[field]) != str(value):
                raise ValueError(f"synthetic raw binding mismatch: {field}")
    if not synthetic:
        fixed = {
            "a02_run_id": handoff["accepted_run_id"],
            "a02_reviewed_implementation_sha": handoff["reviewed_implementation_sha"],
            "a02_result_commit": handoff["result_commit"],
            "a02_quality_run_id": handoff["result_commit_quality_run_id"],
            "a01_raw_sha256": handoff["A01_raw_sha256"],
            "a01_raw_row_count": handoff["A01_raw_row_count"],
            "expected_key_count": handoff["expected_key_count"],
            "triple_common_valid_count": handoff["triple_common_valid_count"],
            "security_count": handoff["security_count"],
            "date_min": handoff["date_min"],
            "date_max": handoff["date_max"],
        }
        for field, value in fixed.items():
            if binding[field] != value:
                raise ValueError(f"formal binding mismatch: {field}")
        if binding["a03_reviewed_implementation_sha"] != reviewed_implementation_sha:
            raise ValueError("formal A03 reviewed SHA binding mismatch")
        for artifact_name, artifact_binding in handoff["accepted_artifacts"].items():
            referenced = Path(artifact_binding["path"])
            referenced = referenced if referenced.is_absolute() else ROOT / referenced
            if (
                not referenced.is_file()
                or sha256_file(referenced) != artifact_binding["sha256"]
            ):
                raise ValueError(
                    f"accepted A02 handoff artifact mismatch: {artifact_name}"
                )
    return {
        "manifest_path": manifest_path,
        "manifest": manifest,
        "declarations": declarations,
        "paths": paths,
        "artifact_hashes": hashes,
        "payloads": payloads,
        "handoff": handoff,
        "synthetic_fixture": synthetic,
        "common_valid_count": int(binding["triple_common_valid_count"]),
        "reviewed_implementation_sha": reviewed_implementation_sha,
    }


def _inspect_raw(
    connection: Any, declaration: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    table = declaration.get("table") or RAW_TABLE
    if table not in tables:
        raise ValueError("raw table missing")
    columns = [row[0] for row in connection.execute(f'SUMMARIZE "{table}"').fetchall()]
    required = [
        "run_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "expected_observation_status",
        "indicator_id",
        "raw_metric_name",
        "raw_value",
        "validity_status",
        "reason_codes_json",
        "input_window_start",
        "input_window_end",
        "required_observation_count",
        "actual_valid_observation_count",
        "metric_engine_version",
        "source_ref",
    ]
    if columns != required:
        raise ValueError("raw schema mismatch")
    row_count, key_count, security_count, date_min, date_max = connection.execute(
        f'SELECT COUNT(*),COUNT(DISTINCT (security_id,trading_date,observation_sequence)),COUNT(DISTINCT security_id),MIN(trading_date),MAX(trading_date) FROM "{table}"'
    ).fetchone()
    actual = {
        "raw_row_count": int(row_count),
        "expected_key_count": int(key_count),
        "security_count": int(security_count),
        "date_min": str(date_min),
        "date_max": str(date_max),
    }
    binding_fields = {
        "raw_row_count": "a01_raw_row_count",
        "expected_key_count": "expected_key_count",
        "security_count": "security_count",
        "date_min": "date_min",
        "date_max": "date_max",
    }
    for field, value in actual.items():
        if str(binding[binding_fields[field]]) != str(value):
            raise ValueError(f"raw binding mismatch: {field}")
    return actual


def _invariants(connection: Any, expected_common: int) -> dict[str, int]:
    table = f'"{RAW_TABLE}"'
    results: dict[str, int] = {}
    results["duplicate_common_key"] = int(
        connection.execute(
            f"WITH common AS (SELECT security_id,trading_date,observation_sequence FROM {table} WHERE validity_status='valid' AND indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) SELECT COUNT(*) FROM (SELECT r.security_id,r.trading_date,r.observation_sequence,r.indicator_id,COUNT(*) n FROM {table} r JOIN common c USING(security_id,trading_date,observation_sequence) WHERE r.validity_status='valid' AND r.indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') GROUP BY ALL HAVING n<>1) x"
        ).fetchone()[0]
    )
    results["common_count_mismatch"] = (
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM (SELECT security_id,trading_date,observation_sequence FROM {table} WHERE validity_status='valid' AND indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) x"
            ).fetchone()[0]
        )
        - expected_common
    )
    results["missing_common_value"] = int(
        connection.execute(
            f"SELECT COUNT(*) FROM (SELECT security_id,trading_date,observation_sequence FROM {table} WHERE indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') AND validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=2 AND BOOL_OR(indicator_id='{A2_ID}') AND BOOL_OR(indicator_id='{A2B_ID}') AND NOT BOOL_OR(indicator_id='{A1_ID}')) x"
        ).fetchone()[0]
    )
    results["nonfinite_common_raw"] = int(
        connection.execute(
            f"WITH common AS (SELECT security_id,trading_date,observation_sequence FROM {table} WHERE validity_status='valid' AND indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) SELECT COUNT(*) FROM {table} r JOIN common c USING(security_id,trading_date,observation_sequence) WHERE r.validity_status='valid' AND r.indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') AND (r.raw_value IS NULL OR NOT isfinite(r.raw_value))"
        ).fetchone()[0]
    )
    results["a2_grid_violation"] = int(
        connection.execute(
            f"WITH common AS (SELECT security_id,trading_date,observation_sequence FROM {table} WHERE validity_status='valid' AND indicator_id IN ('{A1_ID}','{A2_ID}','{A2B_ID}') GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) SELECT COUNT(*) FROM {table} r JOIN common c USING(security_id,trading_date,observation_sequence) WHERE r.indicator_id='{A2_ID}' AND r.validity_status='valid' AND ABS(r.raw_value*20-ROUND(r.raw_value*20))>{A2_GRID_TOLERANCE}"
        ).fetchone()[0]
    )
    results["a2_a2b_valid_set_mismatch"] = int(
        connection.execute(
            f"WITH a AS (SELECT DISTINCT security_id,trading_date,observation_sequence FROM {table} WHERE indicator_id='{A2_ID}' AND validity_status='valid'), b AS (SELECT DISTINCT security_id,trading_date,observation_sequence FROM {table} WHERE indicator_id='{A2B_ID}' AND validity_status='valid') SELECT COUNT(*) FROM ((SELECT * FROM a EXCEPT SELECT * FROM b) UNION ALL (SELECT * FROM b EXCEPT SELECT * FROM a))"
        ).fetchone()[0]
    )
    return results


def _ranked_pair(
    connection: Any, left: str, right: str, where: str = ""
) -> tuple[int, float | None, float | None]:
    row = connection.execute(f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM "{RAW_TABLE}" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), r AS (SELECT *,RANK() OVER(ORDER BY {left})+(COUNT(*) OVER(PARTITION BY {left})-1)/2.0 lm,RANK() OVER(ORDER BY {right})+(COUNT(*) OVER(PARTITION BY {right})-1)/2.0 rm,COUNT(*) OVER() n FROM c {where}), p AS (SELECT *, (lm-.5)/n lp,(rm-.5)/n rp FROM r) SELECT COUNT(*),CORR({left},{right}),CORR(lp,rp) FROM p
    """).fetchone()
    return int(row[0]), row[1], row[2]


def _float_equal(actual: str | None, expected: float | None) -> bool:
    if expected is None:
        return actual in (None, "")
    if actual in (None, ""):
        return False
    return abs(float(actual) - expected) <= 1e-8 * max(1.0, abs(expected))


def _json_value_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return (
            isinstance(actual, Mapping)
            and set(actual) == set(expected)
            and all(
                _json_value_equal(actual[key], value) for key, value in expected.items()
            )
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _json_value_equal(left, right)
                for left, right in zip(actual, expected, strict=True)
            )
        )
    if expected is None:
        return actual in (None, "")
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            return math.isclose(
                float(actual), float(expected), rel_tol=1e-8, abs_tol=1e-8
            )
        except (TypeError, ValueError):
            return False
    return actual == expected


def _grouped_pair_rows(
    connection: Any, left: str, right: str, group: str
) -> dict[Any, tuple[int, float | None, float | None]]:
    value_left = f"PARTITION BY {group},{left}"
    value_right = f"PARTITION BY {group},{right}"
    query = f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM "{RAW_TABLE}" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), r AS (SELECT *,RANK() OVER(PARTITION BY {group} ORDER BY {left})+(COUNT(*) OVER({value_left})-1)/2.0 lm,RANK() OVER(PARTITION BY {group} ORDER BY {right})+(COUNT(*) OVER({value_right})-1)/2.0 rm,COUNT(*) OVER(PARTITION BY {group}) n FROM c), p AS (SELECT *, (lm-.5)/n lp,(rm-.5)/n rp FROM r)
      SELECT {group} group_value,COUNT(*) common_count,CORR({left},{right}) pearson_raw,CORR(lp,rp) spearman_midrank FROM p GROUP BY {group}
    """
    return {
        row[0]: (int(row[1]), row[2], row[3])
        for row in connection.execute(query).fetchall()
    }


def _independent_tail(
    connection: Any, left: str, right: str, fraction: float
) -> tuple[Any, ...]:
    return connection.execute(f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM "{RAW_TABLE}" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), t AS (SELECT QUANTILE_DISC({left},{fraction}) lt,QUANTILE_DISC({right},{fraction}) rt FROM c), f AS (SELECT {left}<=(SELECT lt FROM t) l,{right}<=(SELECT rt FROM t) r FROM c)
      SELECT (SELECT lt FROM t),(SELECT rt FROM t),COUNT(*) FILTER(WHERE l),COUNT(*) FILTER(WHERE l)::DOUBLE/COUNT(*),COUNT(*) FILTER(WHERE r),COUNT(*) FILTER(WHERE r)::DOUBLE/COUNT(*),COUNT(*) FILTER(WHERE l AND r),COUNT(*) FILTER(WHERE l OR r),COUNT(*) FILTER(WHERE l AND r)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE l OR r),0),COUNT(*) FILTER(WHERE l AND r)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE l),0),COUNT(*) FILTER(WHERE l AND r)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE r),0) FROM f
    """).fetchone()


def _independent_conditional(
    connection: Any, config: Mapping[str, Any]
) -> list[tuple[Any, ...]]:
    levels = ",".join(
        f"({value})" for value in config["conditional_profile"]["a2_levels"]
    )
    return connection.execute(f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM "{RAW_TABLE}" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), levels(a2_level) AS (VALUES {levels})
      SELECT l.a2_level,COUNT(c.a2b),COUNT(c.a2b)::DOUBLE/(SELECT COUNT(*) FROM c),MIN(c.a2b),QUANTILE_CONT(c.a2b,.05),QUANTILE_CONT(c.a2b,.25),QUANTILE_CONT(c.a2b,.5),QUANTILE_CONT(c.a2b,.75),QUANTILE_CONT(c.a2b,.95),MAX(c.a2b),AVG(c.a2b),STDDEV_POP(c.a2b),COUNT(DISTINCT c.a2b) FROM levels l LEFT JOIN c ON c.a2=l.a2_level GROUP BY l.a2_level ORDER BY l.a2_level
    """).fetchall()


def _independent_variance(connection: Any) -> tuple[Any, ...]:
    return connection.execute(f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM "{RAW_TABLE}" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), g AS (SELECT a2,AVG(a2b) gm,COUNT(*) n FROM c GROUP BY a2), s AS (SELECT AVG(a2b) global_mean FROM c), total AS (SELECT s.global_mean,SUM(POW(c.a2b-s.global_mean,2)) total_ss FROM c CROSS JOIN s GROUP BY s.global_mean), between_part AS (SELECT total.global_mean,total.total_ss,SUM(g.n*POW(g.gm-total.global_mean,2)) between_group_ss FROM g CROSS JOIN total GROUP BY total.global_mean,total.total_ss), within_part AS (SELECT SUM(POW(c.a2b-g.gm,2)) within_group_ss FROM c JOIN g USING(a2)) SELECT between_part.global_mean,between_part.total_ss,between_part.between_group_ss,within_part.within_group_ss,between_part.between_group_ss/NULLIF(between_part.total_ss,0),within_part.within_group_ss/NULLIF(between_part.total_ss,0),between_part.total_ss-between_part.between_group_ss-within_part.within_group_ss FROM between_part CROSS JOIN within_part
    """).fetchone()


def _independent_stability(
    connection: Any,
    overall: Mapping[str, Mapping[str, Any]],
    years: Mapping[tuple[str, int], tuple[int, float | None, float | None]],
    securities: Mapping[tuple[str, str], tuple[int, float | None, float | None]],
    security_ids: list[str],
    security_min_common_rows: int,
) -> dict[str, dict[str, Any]]:
    fields = CSV_FIELDS["exp_a03_stability_summary.csv"]
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_validator_stability_pairs (pair_id VARCHAR, overall_pearson DOUBLE, overall_spearman DOUBLE, security_total_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO a03_validator_stability_pairs VALUES (?,?,?,?)",
        [
            (
                pair_id,
                values["pearson_raw"],
                values["spearman_midrank"],
                len(security_ids),
            )
            for pair_id, values in overall.items()
        ],
    )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_validator_year_stability (pair_id VARCHAR, spearman_midrank DOUBLE)"
    )
    year_values = [
        (pair_id, values[2])
        for (pair_id, _), values in years.items()
        if values[0] > 0 and values[2] is not None
    ]
    if year_values:
        connection.executemany(
            "INSERT INTO a03_validator_year_stability VALUES (?,?)", year_values
        )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_validator_security_stability (pair_id VARCHAR, spearman_midrank DOUBLE)"
    )
    security_values = [
        (pair_id, values[2])
        for (pair_id, _), values in securities.items()
        if values[0] >= security_min_common_rows and values[2] is not None
    ]
    if security_values:
        connection.executemany(
            "INSERT INTO a03_validator_security_stability VALUES (?,?)", security_values
        )
    rows = connection.execute("""
      WITH y AS (
        SELECT pair_id,COUNT(*) year_count,MIN(spearman_midrank) year_spearman_min,
          QUANTILE_CONT(spearman_midrank,.25) year_spearman_q25,
          QUANTILE_CONT(spearman_midrank,.5) year_spearman_median,
          QUANTILE_CONT(spearman_midrank,.75) year_spearman_q75,
          MAX(spearman_midrank) year_spearman_max,
          SUM(CASE WHEN spearman_midrank<0 THEN 1 ELSE 0 END) year_negative_count
        FROM a03_validator_year_stability GROUP BY pair_id
      ), s AS (
        SELECT pair_id,COUNT(*) security_eligible_count,
          QUANTILE_CONT(spearman_midrank,.1) security_spearman_q10,
          QUANTILE_CONT(spearman_midrank,.25) security_spearman_q25,
          QUANTILE_CONT(spearman_midrank,.5) security_spearman_median,
          QUANTILE_CONT(spearman_midrank,.75) security_spearman_q75,
          QUANTILE_CONT(spearman_midrank,.9) security_spearman_q90,
          SUM(CASE WHEN spearman_midrank<0 THEN 1 ELSE 0 END) security_negative_count
        FROM a03_validator_security_stability GROUP BY pair_id
      )
      SELECT p.pair_id,p.overall_pearson,p.overall_spearman,
        COALESCE(y.year_count,0),y.year_spearman_min,y.year_spearman_q25,y.year_spearman_median,y.year_spearman_q75,y.year_spearman_max,COALESCE(y.year_negative_count,0),
        p.security_total_count,COALESCE(s.security_eligible_count,0),p.security_total_count-COALESCE(s.security_eligible_count,0),
        s.security_spearman_q10,s.security_spearman_q25,s.security_spearman_median,s.security_spearman_q75,s.security_spearman_q90,COALESCE(s.security_negative_count,0)
      FROM a03_validator_stability_pairs p LEFT JOIN y USING(pair_id) LEFT JOIN s USING(pair_id) ORDER BY p.pair_id
    """).fetchall()
    return {row[0]: dict(zip(fields, row, strict=True)) for row in rows}


def _independent_decision(
    connection: Any,
    config: Mapping[str, Any],
    overall: Mapping[str, Mapping[str, Any]],
    years: Mapping[tuple[str, int], tuple[int, float | None, float | None]],
    securities: Mapping[tuple[str, str], tuple[int, float | None, float | None]],
    tails: Mapping[tuple[str, float], tuple[Any, ...]],
    variance: tuple[Any, ...],
    security_ids: list[str],
) -> dict[str, Any]:
    gate_config = config["redundancy_gate"]
    adequacy_config = config["representation_adequacy"]
    stability = _independent_stability(
        connection,
        overall,
        years,
        securities,
        security_ids,
        int(config["correlation"]["security_min_common_rows"]),
    )
    a2a2b = stability["A2_A2b"]
    tail = tails
    variance_fields = CSV_FIELDS["exp_a03_a2_a2b_variance_decomposition.csv"]
    variance_map = dict(zip(variance_fields, variance, strict=True))
    gate = {
        "overall_spearman": {
            "actual": a2a2b["overall_spearman"],
            "threshold": gate_config["overall_spearman_min"],
            "passed": a2a2b["overall_spearman"] is not None
            and a2a2b["overall_spearman"] >= gate_config["overall_spearman_min"],
        },
        "minimum_year_spearman": {
            "actual": a2a2b["year_spearman_min"],
            "threshold": gate_config["minimum_year_spearman_min"],
            "passed": a2a2b["year_spearman_min"] is not None
            and a2a2b["year_spearman_min"] >= gate_config["minimum_year_spearman_min"],
        },
        "eligible_security_spearman_q10": {
            "actual": a2a2b["security_spearman_q10"],
            "threshold": gate_config["eligible_security_spearman_q10_min"],
            "passed": a2a2b["security_spearman_q10"] is not None
            and a2a2b["security_spearman_q10"]
            >= gate_config["eligible_security_spearman_q10_min"],
        },
        "tail_jaccard_005": {
            "actual": tail[("A2_A2b", 0.05)][8],
            "threshold": gate_config["tail_jaccard_005_min"],
            "passed": tail[("A2_A2b", 0.05)][8] >= gate_config["tail_jaccard_005_min"],
        },
        "tail_jaccard_010": {
            "actual": tail[("A2_A2b", 0.1)][8],
            "threshold": gate_config["tail_jaccard_010_min"],
            "passed": tail[("A2_A2b", 0.1)][8] >= gate_config["tail_jaccard_010_min"],
        },
        "eta_squared": {
            "actual": variance_map["eta_squared"],
            "threshold": gate_config["eta_squared_min"],
            "passed": variance_map["eta_squared"] is not None
            and variance_map["eta_squared"] >= gate_config["eta_squared_min"],
        },
    }
    gate["all_passed"] = all(item["passed"] for item in gate.values())
    grid_violation_count, unique_level_count, maximum_level_share = (
        connection.execute(f"""
      WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM \"{RAW_TABLE}\" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3), levels AS (SELECT a2,COUNT(*) n FROM c GROUP BY a2)
      SELECT (SELECT COUNT(*) FROM c WHERE ABS(a2*20-ROUND(a2*20))>{A2_GRID_TOLERANCE}),(SELECT COUNT(*) FROM levels),(SELECT MAX(n)::DOUBLE/(SELECT COUNT(*) FROM c) FROM levels)
    """).fetchone()
    )
    adequacy = {
        "grid_violation_count": {
            "actual": int(grid_violation_count),
            "threshold": adequacy_config["a2_grid_violation_max"],
            "passed": int(grid_violation_count)
            <= adequacy_config["a2_grid_violation_max"],
        },
        "unique_grid_level_count": {
            "actual": int(unique_level_count),
            "threshold": adequacy_config["a2_unique_level_count"],
            "passed": int(unique_level_count)
            == adequacy_config["a2_unique_level_count"],
        },
        "maximum_level_share": {
            "actual": maximum_level_share,
            "threshold": adequacy_config["a2_max_level_share"],
            "passed": maximum_level_share <= adequacy_config["a2_max_level_share"],
        },
        "tail_realized_rate_005": {
            "actual": tail[("A2_A2b", 0.05)][3],
            "threshold": adequacy_config["a2_tail_realized_rate_005_max"],
            "passed": tail[("A2_A2b", 0.05)][3]
            <= adequacy_config["a2_tail_realized_rate_005_max"],
        },
        "tail_realized_rate_010": {
            "actual": tail[("A2_A2b", 0.1)][3],
            "threshold": adequacy_config["a2_tail_realized_rate_010_max"],
            "passed": tail[("A2_A2b", 0.1)][3]
            <= adequacy_config["a2_tail_realized_rate_010_max"],
        },
    }
    adequacy["all_passed"] = all(item["passed"] for item in adequacy.values())
    collisions = {}
    for pair_id in ("A1_A2", "A1_A2b"):
        pair = stability[pair_id]
        collisions[pair_id] = bool(
            pair["overall_spearman"] is not None
            and pair["overall_spearman"] >= gate_config["overall_spearman_min"]
            and pair["year_spearman_min"] is not None
            and pair["year_spearman_min"] >= gate_config["minimum_year_spearman_min"]
            and tail[(pair_id, 0.05)][8] >= gate_config["tail_jaccard_005_min"]
            and tail[(pair_id, 0.1)][8] >= gate_config["tail_jaccard_010_min"]
        )
    if gate["all_passed"] and adequacy["all_passed"]:
        candidates, reason = (
            ["A1", "A2"],
            "redundant_and_A2_preferred_for_topological_interpretability",
        )
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "selected_persistence_representative",
            "A2b": "retain_as_redundant_backup_not_carried_to_A04",
        }
    elif gate["all_passed"]:
        candidates, reason = ["A1", "A2b"], "redundant_but_A2_representation_inadequate"
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "retain_as_coarse_backup_not_carried_to_A04",
            "A2b": "selected_persistence_representative",
        }
    else:
        candidates, reason = ["A1", "A2", "A2b"], "material_internal_difference"
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "retain_for_A04",
            "A2b": "retain_for_A04",
        }
    return {
        "candidate_ids": ["A1", "A2", "A2b"],
        "common_valid_count": int(overall["A1_A2"]["common_count"]),
        "A2_A2b_redundancy_gate": gate,
        "A2_representation_adequacy": adequacy,
        "A1_collision_flags": collisions,
        "recommended_candidate_set_for_A04": candidates,
        "candidate_dispositions": dispositions,
        "decision_reason": reason,
        "decision_status": "provisional_A03_recommendation",
        "A_layer_registered": False,
        "PCATV_created": False,
        "EXP_A04_started": False,
    }


def _independent_aggregate_check(
    connection: Any,
    package_root: Path,
    config: Mapping[str, Any],
    *,
    synthetic_fixture: bool = False,
) -> list[str]:
    errors: list[str] = []
    overall = _read_csv(
        package_root / "exp_a03_pairwise_overall.csv", "exp_a03_pairwise_overall.csv"
    )
    if len(overall) != 3:
        errors.append("pairwise_overall_row_count_mismatch")
    overall_map = {row["pair_id"]: row for row in overall}
    overall_expected: dict[str, dict[str, Any]] = {}
    for pair_id, (_, _, left, right) in PAIR_DEFS.items():
        count, pearson, spearman = _ranked_pair(connection, left, right)
        # Recompute distinct/tied metadata with an independent aggregate rather
        # than trusting the producer's compact metadata.
        left_unique, right_unique = connection.execute(
            f"WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM \"{RAW_TABLE}\" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) SELECT COUNT(DISTINCT {left}),COUNT(DISTINCT {right}) FROM c"
        ).fetchone()
        left_ties, right_ties = connection.execute(
            f"WITH c AS (SELECT security_id,trading_date,observation_sequence,MAX(raw_value) FILTER(WHERE indicator_id='{A1_ID}') a1,MAX(raw_value) FILTER(WHERE indicator_id='{A2_ID}') a2,MAX(raw_value) FILTER(WHERE indicator_id='{A2B_ID}') a2b FROM \"{RAW_TABLE}\" WHERE validity_status='valid' GROUP BY ALL HAVING COUNT(DISTINCT indicator_id)=3) SELECT (SELECT COALESCE(SUM(n) FILTER(WHERE n>1),0) FROM (SELECT {left},COUNT(*) n FROM c GROUP BY {left})),(SELECT COALESCE(SUM(n) FILTER(WHERE n>1),0) FROM (SELECT {right},COUNT(*) n FROM c GROUP BY {right}))"
        ).fetchone()
        overall_expected[pair_id] = {
            "common_count": count,
            "pearson_raw": pearson,
            "spearman_midrank": spearman,
            "left_unique_value_count": int(left_unique),
            "right_unique_value_count": int(right_unique),
            "left_tied_row_count": int(left_ties),
            "right_tied_row_count": int(right_ties),
        }
        row = overall_map.get(pair_id)
        if (
            row is None
            or row["left_indicator_id"] != PAIR_DEFS[pair_id][0]
            or row["right_indicator_id"] != PAIR_DEFS[pair_id][1]
            or int(row["common_count"]) != count
            or not _float_equal(row["pearson_raw"], pearson)
            or not _float_equal(row["spearman_midrank"], spearman)
            or any(
                int(row[field]) != overall_expected[pair_id][field]
                for field in (
                    "left_unique_value_count",
                    "right_unique_value_count",
                    "left_tied_row_count",
                    "right_tied_row_count",
                )
            )
        ):
            errors.append(f"aggregate_csv_mismatch:{pair_id}")
        if spearman is None or not math.isfinite(float(spearman)):
            errors.append(f"nonfinite_overall_spearman:{pair_id}")
        elif spearman < 0:
            errors.append(f"negative_overall_spearman:{pair_id}")
    years = [int(value) for value in config["candidate_universe"]["years"]]
    year_rows = _read_csv(
        package_root / "exp_a03_pairwise_year.csv", "exp_a03_pairwise_year.csv"
    )
    if len(year_rows) != 3 * len(years):
        errors.append("pairwise_year_row_count_mismatch")
    year_map = {(row["pair_id"], int(row["calendar_year"])): row for row in year_rows}
    year_expected: dict[tuple[str, int], tuple[int, float | None, float | None]] = {}
    for pair_id, (_, _, left, right) in PAIR_DEFS.items():
        grouped = _grouped_pair_rows(connection, left, right, "YEAR(trading_date)")
        for year in years:
            row = year_map.get((pair_id, year))
            expected = grouped.get(year, (0, None, None))
            year_expected[(pair_id, year)] = expected
            if (
                row is None
                or int(row["common_count"]) != expected[0]
                or not _float_equal(row["pearson_raw"], expected[1])
                or not _float_equal(row["spearman_midrank"], expected[2])
            ):
                errors.append(f"year_aggregate_mismatch:{pair_id}:{year}")
            if not synthetic_fixture and expected[0] == 0:
                errors.append(f"accepted_year_missing:{pair_id}:{year}")
    security_rows = _read_csv(
        package_root / "exp_a03_pairwise_security.csv", "exp_a03_pairwise_security.csv"
    )
    security_ids = [
        row[0]
        for row in connection.execute(
            f'SELECT DISTINCT security_id FROM "{RAW_TABLE}" ORDER BY security_id'
        ).fetchall()
    ]
    expected_security_rows = 3 * len(security_ids)
    if len(security_rows) != expected_security_rows:
        errors.append("pairwise_security_row_count_mismatch")
    security_map = {(row["pair_id"], row["security_id"]): row for row in security_rows}
    if len(security_map) != len(security_rows):
        errors.append("pairwise_security_duplicate_key")
    security_expected: dict[
        tuple[str, str], tuple[int, float | None, float | None]
    ] = {}
    security_min = int(config["correlation"]["security_min_common_rows"])
    for pair_id, (_, _, left, right) in PAIR_DEFS.items():
        grouped = _grouped_pair_rows(connection, left, right, "security_id")
        for security_id in security_ids:
            row = security_map.get((pair_id, security_id))
            expected = grouped.get(security_id, (0, None, None))
            security_expected[(pair_id, security_id)] = expected
            eligible = expected[0] >= security_min
            if (
                row is None
                or int(row["common_count"]) != expected[0]
                or row["eligible"].lower() != str(eligible).lower()
            ):
                errors.append(f"security_aggregate_mismatch:{pair_id}:{security_id}")
            if eligible and (
                not _float_equal(row["pearson_raw"], expected[1])
                or not _float_equal(row["spearman_midrank"], expected[2])
            ):
                errors.append(f"security_correlation_mismatch:{pair_id}:{security_id}")
            if not eligible and (
                row["pearson_raw"] not in ("",)
                or row["spearman_midrank"] not in ("",)
                or row["reason"] != "insufficient_common_rows"
            ):
                errors.append(f"security_insufficient_contract:{pair_id}:{security_id}")
            if not synthetic_fixture and expected[0] == 0:
                errors.append(f"accepted_security_missing:{pair_id}:{security_id}")
    tails = _read_csv(
        package_root / "exp_a03_tail_overlap.csv", "exp_a03_tail_overlap.csv"
    )
    if len(tails) != 9:
        errors.append("tail_row_count_mismatch")
    tail_map: dict[tuple[str, float], tuple[Any, ...]] = {}
    for row in tails:
        left, right = PAIR_DEFS[row["pair_id"]][2:]
        fraction = float(row["tail_fraction"])
        expected = _independent_tail(connection, left, right, fraction)
        tail_map[(row["pair_id"], fraction)] = expected
        actual = (
            float(row["left_threshold"]),
            float(row["right_threshold"]),
            int(row["left_selected_count"]),
            float(row["left_realized_rate"]),
            int(row["right_selected_count"]),
            float(row["right_realized_rate"]),
            int(row["intersection_count"]),
            int(row["union_count"]),
            float(row["jaccard"]),
            float(row["left_containment"]),
            float(row["right_containment"]),
        )
        tail_fields = (
            "left_threshold",
            "right_threshold",
            "left_selected_count",
            "left_realized_rate",
            "right_selected_count",
            "right_realized_rate",
            "intersection_count",
            "union_count",
            "jaccard",
            "left_containment",
            "right_containment",
        )
        tail_mismatch = False
        for field, actual_value, expected_value in zip(
            tail_fields, actual, expected, strict=True
        ):
            if field in {
                "left_selected_count",
                "right_selected_count",
                "intersection_count",
                "union_count",
            }:
                tail_mismatch |= actual_value != int(expected_value)
            elif expected_value is None:
                tail_mismatch |= actual_value is not None
            else:
                tail_mismatch |= not _float_equal(
                    str(actual_value), float(expected_value)
                )
        if tail_mismatch:
            errors.append(
                f"tail_aggregate_mismatch:{row['pair_id']}:{row['tail_fraction']}"
            )
    conditional = _read_csv(
        package_root / "exp_a03_a2_a2b_conditional_profile.csv",
        "exp_a03_a2_a2b_conditional_profile.csv",
    )
    expected_conditional = _independent_conditional(connection, config)
    if len(conditional) != 21:
        errors.append("conditional_row_count_mismatch")
    for persisted, expected in zip(conditional, expected_conditional, strict=False):
        for index, field in enumerate(
            CSV_FIELDS["exp_a03_a2_a2b_conditional_profile.csv"]
        ):
            expected_value = expected[index]
            if field in {"row_count", "a2b_unique_value_count"}:
                mismatch = int(persisted[field]) != int(expected_value or 0)
            elif expected_value is None:
                mismatch = persisted[field] != ""
            else:
                mismatch = not _float_equal(persisted[field], float(expected_value))
            if mismatch:
                errors.append(f"conditional_aggregate_mismatch:{field}")
                break
    variance = _read_csv(
        package_root / "exp_a03_a2_a2b_variance_decomposition.csv",
        "exp_a03_a2_a2b_variance_decomposition.csv",
    )
    expected_variance = _independent_variance(connection)
    if len(variance) != 1 or any(
        not _float_equal(variance[0][field], expected_variance[index])
        for index, field in enumerate(
            CSV_FIELDS["exp_a03_a2_a2b_variance_decomposition.csv"]
        )
    ):
        errors.append("variance_decomposition_mismatch")
    if variance:
        try:
            residual = float(variance[0]["reconciliation_residual"])
            total_ss = float(variance[0]["total_ss"])
            if abs(residual) > 1e-9 * max(1.0, abs(total_ss)):
                errors.append("variance_residual_failure")
        except (TypeError, ValueError):
            errors.append("variance_residual_failure")
    stability = _read_csv(
        package_root / "exp_a03_stability_summary.csv", "exp_a03_stability_summary.csv"
    )
    if len(stability) != 3:
        errors.append("stability_summary_row_count_mismatch")
    stability_map = {row["pair_id"]: row for row in stability}
    expected_stability = _independent_stability(
        connection,
        overall_expected,
        year_expected,
        security_expected,
        security_ids,
        security_min,
    )
    integer_fields = {
        "year_count",
        "year_negative_count",
        "security_total_count",
        "security_eligible_count",
        "security_insufficient_count",
        "security_negative_count",
    }
    for pair_id, expected in expected_stability.items():
        row = stability_map.get(pair_id)
        if row is None:
            errors.append(f"stability_summary_mismatch:{pair_id}")
            continue
        for field in CSV_FIELDS["exp_a03_stability_summary.csv"]:
            if field == "pair_id":
                continue
            expected_value = expected[field]
            if field in integer_fields:
                mismatch = int(row[field]) != int(expected_value or 0)
            elif expected_value is None:
                mismatch = row[field] != ""
            else:
                mismatch = not _float_equal(row[field], float(expected_value))
            if mismatch:
                errors.append(f"stability_summary_mismatch:{pair_id}:{field}")
                break
    disposition_path = package_root / "exp_a03_candidate_disposition.json"
    if disposition_path.is_file():
        persisted_decision = load_json(disposition_path)
        expected_decision = _independent_decision(
            connection,
            config,
            overall_expected,
            year_expected,
            security_expected,
            tail_map,
            expected_variance,
            security_ids,
        )
        for field in (
            "candidate_ids",
            "common_valid_count",
            "recommended_candidate_set_for_A04",
            "candidate_dispositions",
            "decision_reason",
            "decision_status",
            "A1_collision_flags",
            "A_layer_registered",
            "PCATV_created",
            "EXP_A04_started",
        ):
            if not _json_value_equal(
                persisted_decision.get(field), expected_decision[field]
            ):
                errors.append(f"decision_rule_failure:{field}")
        for group in ("A2_A2b_redundancy_gate", "A2_representation_adequacy"):
            if not _json_value_equal(
                persisted_decision.get(group), expected_decision[group]
            ) or not _json_value_equal(
                persisted_decision.get("thresholds", {}).get(group),
                expected_decision[group],
            ):
                errors.append(f"decision_rule_failure:{group}")
    return errors


def validate_package(
    package_root: Path,
    *,
    config: Mapping[str, Any],
    input_manifest_path: Path,
    run_id: str,
    input_root: Path | None = None,
    allow_synthetic_fixture: bool = False,
    allow_formal_run: bool = False,
    reviewed_implementation_sha: str | None = None,
    require_final_manifest: bool = True,
) -> dict[str, Any]:
    config_errors = validate_static_config(config)
    if config_errors:
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "valid": False,
            "errors": [f"config:{error}" for error in config_errors],
            "mismatch_counts": {"config_mismatch": len(config_errors)},
        }
    try:
        input_info = prepare_input_manifest(
            input_manifest_path,
            input_root=input_root,
            allow_synthetic_fixture=allow_synthetic_fixture,
            allow_formal_run=allow_formal_run,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "valid": False,
            "errors": [f"lineage:{exc}"],
            "mismatch_counts": {"lineage_mismatch": 1},
        }
    errors: list[str] = []
    package_root = package_root.resolve()
    manifest_path = package_root / "exp_a03_manifest.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else None
    if manifest is None and require_final_manifest:
        errors.append("manifest_missing")
    if manifest is not None:
        if manifest.get("task_id") != TASK_ID or manifest.get("run_id") != run_id:
            errors.append("manifest_identity_mismatch")
        if (
            manifest.get("synthetic_fixture") is not input_info["synthetic_fixture"]
            or manifest.get("formal_data_version") is not False
        ):
            errors.append("manifest_execution_mode_mismatch")
        expected_formal = not input_info["synthetic_fixture"]
        for field in (
            "formal_run_allowed",
            "formal_run_executed",
            "formal_artifacts_generated",
        ):
            if manifest.get(field) is not expected_formal:
                errors.append(f"manifest_{field}_mismatch")
        if manifest.get("reviewed_implementation_sha") != (
            None if input_info["synthetic_fixture"] else reviewed_implementation_sha
        ):
            errors.append("manifest_reviewed_sha_mismatch")
        expected_upstream = {
            "task_id": "EXP-A02",
            "accepted_run_id": input_info["handoff"]["accepted_run_id"],
            "reviewed_implementation_sha": input_info["handoff"][
                "reviewed_implementation_sha"
            ],
            "result_commit": input_info["handoff"]["result_commit"],
        }
        if manifest.get("accepted_upstream") != expected_upstream:
            errors.append("accepted_upstream_binding_mismatch")
        input_artifacts = manifest.get("input_artifacts")
        if not isinstance(input_artifacts, Mapping) or set(input_artifacts) != set(
            EXPECTED_INPUTS
        ):
            errors.append("manifest_input_artifact_set_mismatch")
        else:
            for artifact_id in EXPECTED_INPUTS:
                declaration = input_info["declarations"][artifact_id]
                persisted = input_artifacts[artifact_id]
                if (
                    not isinstance(persisted, Mapping)
                    or persisted.get("path") != declaration.get("path")
                    or persisted.get("path_policy") != declaration.get("path_policy")
                    or persisted.get("sha256")
                    != input_info["artifact_hashes"][artifact_id]
                ):
                    errors.append(
                        f"manifest_input_artifact_binding_mismatch:{artifact_id}"
                    )
        binding = input_info["manifest"]["cross_artifact_bindings"]
        for field, expected in (
            ("raw_row_count", binding["a01_raw_row_count"]),
            ("expected_key_count", binding["expected_key_count"]),
            ("triple_common_valid_count", binding["triple_common_valid_count"]),
            ("security_count", binding["security_count"]),
            ("date_min", binding["date_min"]),
            ("date_max", binding["date_max"]),
        ):
            if manifest.get(field) != expected:
                errors.append(f"manifest_{field}_mismatch")
        for field in (
            "A_layer_registered",
            "PCATV_created",
            "EXP_A04_started",
            "prohibited_outputs_generated",
        ):
            if manifest.get(field) is not False:
                errors.append(f"manifest_{field}_mismatch")
        if manifest.get("input_manifest_sha256") != sha256_file(input_manifest_path):
            errors.append("input_manifest_hash_mismatch")
        if (
            manifest.get("input_hashes_before") != input_info["artifact_hashes"]
            or manifest.get("input_hashes_after") != input_info["artifact_hashes"]
            or manifest.get("input_hash_changed_count") != 0
        ):
            errors.append("input_hash_changed")
        if manifest.get("preliminary_mismatch_count", 0):
            errors.append("preliminary_validator_mismatch")
    raw_path = input_info["paths"]["exp_a01_raw_metrics"]
    connection = duckdb.connect(str(raw_path), read_only=True)
    try:
        _inspect_raw(
            connection,
            input_info["declarations"]["exp_a01_raw_metrics"],
            input_info["manifest"]["cross_artifact_bindings"],
        )
        for name, value in _invariants(
            connection, input_info["common_valid_count"]
        ).items():
            if value:
                errors.append(f"{name}:{value}")
        if (package_root / "exp_a03_pairwise_overall.csv").is_file():
            errors.extend(
                _independent_aggregate_check(
                    connection,
                    package_root,
                    config,
                    synthetic_fixture=input_info["synthetic_fixture"],
                )
            )
        else:
            errors.append("pairwise_overall_missing")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"raw_or_aggregate_validation:{exc}")
    finally:
        connection.close()
    disposition_path = package_root / "exp_a03_candidate_disposition.json"
    if disposition_path.is_file():
        disposition = load_json(disposition_path)
        if (
            disposition.get("task_id") != TASK_ID
            or disposition.get("run_id") != run_id
            or disposition.get("decision_version") != "EXP-A03-v1"
            or disposition.get("decision_status") != "provisional_A03_recommendation"
            or disposition.get("A_layer_registered") is not False
            or disposition.get("PCATV_created") is not False
            or disposition.get("EXP_A04_started") is not False
        ):
            errors.append("decision_governance_mismatch")
    else:
        errors.append("candidate_disposition_missing")
    if require_final_manifest:
        actual = {path.name for path in package_root.iterdir() if path.is_file()}
        if actual != set(OUTPUT_FILES):
            errors.append("exact_output_file_set_mismatch")
        if any(
            path.suffix.lower() in {".duckdb", ".parquet"}
            for path in package_root.iterdir()
        ):
            errors.append("forbidden_output_file")
        if manifest is None or manifest.get("final_manifest") is not True:
            errors.append("final_manifest_required")
        if manifest is not None:
            declared = manifest.get("output_artifacts", {})
            for filename in set(OUTPUT_FILES) - {"exp_a03_manifest.json"}:
                path = package_root / filename
                if (
                    not path.is_file()
                    or not isinstance(declared.get(filename), Mapping)
                    or declared[filename].get("sha256") != sha256_file(path)
                ):
                    errors.append(f"output_hash_mismatch:{filename}")
    for filename in CSV_FIELDS:
        path = package_root / filename
        if path.is_file():
            try:
                _read_csv(path, filename)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"csv_contract:{filename}:{exc}")
    analysis = package_root / "exp_a03_result_analysis.md"
    if analysis.is_file():
        text = analysis.read_text(encoding="utf-8")
        expected_headings = config["analysis_headings"]
        positions = [text.find(heading) for heading in expected_headings]
        if any(position < 0 for position in positions) or positions != sorted(
            positions
        ):
            errors.append("analysis_heading_contract")
        if not text.rstrip().endswith(
            "needs_investigation_before_user_review"
            if input_info["synthetic_fixture"]
            else "ready_for_user_formal_result_review"
        ):
            errors.append("analysis_readiness_contract")
    else:
        errors.append("analysis_missing")
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "errors": errors,
        "warnings": [],
        "lineage_replayed_from_disk": True,
        "full_set_based_invariant_scan_performed": True,
        "full_output_aggregate_recompute_performed": True,
        "core_validator_execution_count": 1,
        "mismatch_counts": {"total": len(errors)},
        "input_artifact_hashes": input_info["artifact_hashes"],
        "input_hash_changed_count": 0,
    }


def cheap_validate_final_package(
    package_root: Path,
    *,
    run_id: str,
    input_manifest_sha256: str,
    input_hashes: Mapping[str, str],
    reviewed_implementation_sha: str | None,
    synthetic_fixture: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    actual = {path.name for path in package_root.iterdir() if path.is_file()}
    if actual != set(OUTPUT_FILES):
        errors.append("exact_output_file_set_mismatch")
    if any(
        path.suffix.lower() in {".duckdb", ".parquet"}
        for path in package_root.iterdir()
    ):
        errors.append("forbidden_output_file")
    manifest = (
        load_json(package_root / "exp_a03_manifest.json")
        if (package_root / "exp_a03_manifest.json").is_file()
        else {}
    )
    if (
        manifest.get("task_id") != TASK_ID
        or manifest.get("run_id") != run_id
        or manifest.get("input_manifest_sha256") != input_manifest_sha256
    ):
        errors.append("manifest_identity_mismatch")
    expected_formal = not synthetic_fixture
    if (
        manifest.get("synthetic_fixture") is not synthetic_fixture
        or manifest.get("formal_data_version") is not False
    ):
        errors.append("manifest_execution_mode_mismatch")
    for field in (
        "formal_run_allowed",
        "formal_run_executed",
        "formal_artifacts_generated",
    ):
        if manifest.get(field) is not expected_formal:
            errors.append(f"manifest_{field}_mismatch")
    if (
        manifest.get("input_hashes_before") != dict(input_hashes)
        or manifest.get("input_hashes_after") != dict(input_hashes)
        or manifest.get("input_hash_changed_count") != 0
    ):
        errors.append("input_hash_changed")
    if manifest.get("reviewed_implementation_sha") != (
        None if synthetic_fixture else reviewed_implementation_sha
    ):
        errors.append("reviewed_sha_mismatch")
    expected_upstream = {
        "task_id": "EXP-A02",
        "accepted_run_id": "EXP-A02-20260717T100527443Z",
        "reviewed_implementation_sha": "bfd7ad71de8638d0a9d0adde824078d7ddc595b5",
        "result_commit": "45765edcf6c8a76bc47b167822e9d7a07ec5ab10",
    }
    if manifest.get("accepted_upstream") != expected_upstream:
        errors.append("accepted_upstream_binding_mismatch")
    input_artifacts = manifest.get("input_artifacts")
    if not isinstance(input_artifacts, Mapping) or set(input_artifacts) != set(
        EXPECTED_INPUTS
    ):
        errors.append("manifest_input_artifact_set_mismatch")
    else:
        for artifact_id in EXPECTED_INPUTS:
            declaration = input_artifacts[artifact_id]
            if not isinstance(declaration, Mapping) or declaration.get(
                "sha256"
            ) != input_hashes.get(artifact_id):
                errors.append(f"manifest_input_artifact_hash_mismatch:{artifact_id}")
    for field in (
        "A_layer_registered",
        "PCATV_created",
        "EXP_A04_started",
        "prohibited_outputs_generated",
    ):
        if manifest.get(field) is not False:
            errors.append(f"manifest_{field}_mismatch")
    if (
        manifest.get("final_manifest") is not True
        or manifest.get("validator_status") != "passed"
        or manifest.get("anomaly_status")
        not in {"passed", "passed_with_investigation_items"}
    ):
        errors.append("final_status_mismatch")
    declared = manifest.get("output_artifacts", {})
    for filename in set(OUTPUT_FILES) - {"exp_a03_manifest.json"}:
        if not isinstance(declared.get(filename), Mapping) or declared[filename].get(
            "sha256"
        ) != sha256_file(package_root / filename):
            errors.append(f"output_hash_mismatch:{filename}")
    analysis_path = package_root / "exp_a03_result_analysis.md"
    if not analysis_path.is_file():
        errors.append("analysis_missing")
    else:
        text = analysis_path.read_text(encoding="utf-8")
        positions = [
            text.find(heading)
            for heading in load_json(CONFIG_PATH)["analysis_headings"]
        ]
        if any(position < 0 for position in positions) or positions != sorted(
            positions
        ):
            errors.append("analysis_heading_contract")
        expected_final = (
            "needs_investigation_before_user_review"
            if synthetic_fixture
            else "ready_for_user_formal_result_review"
        )
        if not text.rstrip().endswith(expected_final):
            errors.append("analysis_readiness_contract")
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
