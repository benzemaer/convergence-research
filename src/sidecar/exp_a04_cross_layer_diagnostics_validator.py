# ruff: noqa: E501

"""Independent EXP-A04 lineage, output, and aggregate validator.

This module intentionally does not call the producer's SQL or calculation
helpers.  It reconstructs the pair universes and compact aggregates from the
two persisted inputs, then compares them with the published package.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

TASK_ID = "EXP-A04"
A_IDS = (
    "A1_LogBodyCenterToMACloudCenter_5_60",
    "A2_BodyCenterOutsideMACloudRate20_5_60",
    "A2b_BodyToMACloudGapMean20_5_60",
)
A_SHORT = {A_IDS[0]: "A1", A_IDS[1]: "A2", A_IDS[2]: "A2b"}
A_RAW_NAMES = {
    A_IDS[0]: "LogBodyCenterToMACloudCenter_5_60",
    A_IDS[1]: "BodyCenterOutsideMACloudRate20_5_60",
    A_IDS[2]: "BodyToMACloudGapMean20_5_60",
}
PCVT_IDS = (
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base",
)
PCVT_LAYER = {
    PCVT_IDS[0]: "P",
    PCVT_IDS[1]: "P",
    PCVT_IDS[2]: "C",
    PCVT_IDS[3]: "C",
    PCVT_IDS[4]: "T",
    PCVT_IDS[5]: "T",
    PCVT_IDS[6]: "V",
    PCVT_IDS[7]: "V",
}
YEARS = tuple(range(2016, 2027))
TAILS = (0.01, 0.05, 0.1)
OUTPUT_FILES = {
    "exp_a04_indicator_registry.csv",
    "exp_a04_pairwise_coverage.csv",
    "exp_a04_pairwise_overall.csv",
    "exp_a04_pairwise_year.csv",
    "exp_a04_pairwise_security.csv",
    "exp_a04_tail_overlap.csv",
    "exp_a04_layer_summary.csv",
    "exp_a04_candidate_summary.csv",
    "exp_a04_cross_layer_disposition.json",
    "exp_a04_manifest.json",
    "exp_a04_validator_result.json",
    "exp_a04_anomaly_scan.json",
    "exp_a04_result_analysis.md",
}
CSV_FIELDS = {
    "exp_a04_indicator_registry.csv": (
        "registry_role",
        "indicator_id",
        "layer",
        "raw_metric_name",
        "raw_source_indicator_id",
        "raw_value_direction",
    ),
    "exp_a04_pairwise_coverage.csv": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "a_valid_count",
        "pcvt_valid_count",
        "common_count",
        "common_rate_of_a",
        "common_rate_of_pcvt",
        "common_rate_of_smaller_side",
        "join_key_policy",
        "one_to_one_key_proven",
    ),
    "exp_a04_pairwise_overall.csv": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "a_tied_row_count",
        "pcvt_tied_row_count",
    ),
    "exp_a04_pairwise_year.csv": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "calendar_year",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "undefined_reason",
    ),
    "exp_a04_pairwise_security.csv": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "security_id",
        "common_count",
        "eligible",
        "pearson_raw",
        "spearman_midrank",
        "reason",
    ),
    "exp_a04_tail_overlap.csv": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "tail_fraction",
        "a_threshold",
        "pcvt_threshold",
        "a_selected_count",
        "a_realized_rate",
        "pcvt_selected_count",
        "pcvt_realized_rate",
        "intersection_count",
        "union_count",
        "jaccard",
        "a_containment",
        "pcvt_containment",
    ),
    "exp_a04_layer_summary.csv": (
        "a_candidate_id",
        "pcvt_layer",
        "indicator_pair_count",
        "valid_pair_count",
        "nearest_indicator_by_spearman",
        "max_overall_spearman",
        "nearest_indicator_by_tail_jaccard_005",
        "max_tail_jaccard_005",
        "nearest_indicator_by_tail_jaccard_010",
        "max_tail_jaccard_010",
        "hard_collision_count",
        "hard_collision_indicator_ids_json",
    ),
    "exp_a04_candidate_summary.csv": (
        "a_candidate_id",
        "nearest_layer",
        "nearest_indicator",
        "max_overall_spearman",
        "max_tail_jaccard_005",
        "max_tail_jaccard_010",
        "hard_collision_count",
        "hard_collision_pairs_json",
        "eligible_pair_count",
        "low_coverage_pair_count",
        "provisional_status_for_A05",
    ),
}


class ValidationError(RuntimeError):
    """Raised only for internal validator setup failures."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _date_expr(column: str) -> str:
    value = f"CAST({column} AS VARCHAR)"
    return f"COALESCE(try_strptime({value}, '%Y-%m-%d')::DATE,try_strptime({value}, '%Y%m%d')::DATE)"


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quantile_cont(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def _schema_validate(
    root: Path, schema_name: str, payload: Mapping[str, Any]
) -> list[str]:
    schema = _load(root / "schemas" / "sidecar" / schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=lambda item: list(item.path),
    )
    return [
        "schema:" + ".".join(str(part) for part in error.path) + ":" + error.message
        for error in errors
    ]


def _committed_bytes(root: Path, relative_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{relative_path}"]
    )


def _verify_repo_artifact(root: Path, declaration: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    relative = str(declaration["path"])
    try:
        data = _committed_bytes(root, relative)
    except subprocess.CalledProcessError:
        return [f"missing_committed_artifact:{relative}"]
    if hashlib.sha256(data).hexdigest() != declaration["committed_byte_sha256"]:
        errors.append(f"committed_byte_sha256_mismatch:{relative}")
    blob_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", f"HEAD:{relative}"], text=True
    ).strip()
    if blob_sha != declaration["git_blob_sha"]:
        errors.append(f"git_blob_sha_mismatch:{relative}")
    return errors


def validate_handoffs(
    root: Path,
    config: Mapping[str, Any],
    *,
    a03_path: Path | None = None,
    pcvt_path: Path | None = None,
) -> list[str]:
    """Validate immutable handoffs and their committed evidence before raw open."""
    a03_path = (
        a03_path
        or root / "data/generated/sidecar/exp_a03/exp_a03_accepted_result_handoff.json"
    )
    pcvt_path = (
        pcvt_path
        or root
        / "data/generated/sidecar/exp_a04/exp_a04_pcvt_raw_accepted_handoff.json"
    )
    errors: list[str] = []
    if not a03_path.is_file() or not pcvt_path.is_file():
        return ["accepted_handoff_missing"]
    a03 = _load(a03_path)
    pcvt = _load(pcvt_path)
    errors.extend(
        _schema_validate(root, "exp_a03_accepted_result_handoff.schema.json", a03)
    )
    errors.extend(
        _schema_validate(root, "exp_a04_pcvt_raw_accepted_handoff.schema.json", pcvt)
    )
    if a03.get("accepted_candidate_set_for_A04") != ["A1", "A2", "A2b"]:
        errors.append("a03_candidate_set_mismatch")
    if (
        a03.get("EXP_A04_input_eligible") is not True
        or a03.get("formal_result_review_status") != "accepted"
    ):
        errors.append("a03_acceptance_status_mismatch")
    registry = config.get("pcvt_indicator_registry", [])
    pcvt_registry = pcvt.get("indicator_registry", [])
    expected_registry = [
        (
            row.get("indicator_id"),
            row.get("layer"),
            row.get("raw_metric_name"),
            row.get("raw_value_direction"),
        )
        for row in registry
    ]
    actual_registry = [
        (
            row.get("indicator_id"),
            row.get("layer"),
            row.get("raw_metric_name"),
            row.get("direction"),
        )
        for row in pcvt_registry
    ]
    if expected_registry != actual_registry:
        errors.append("pcvt_handoff_registry_mismatch")
    if pcvt.get("artifact", {}).get("sha256") != config.get("upstream", {}).get(
        "pcvt_raw_binding", {}
    ).get("sha256"):
        errors.append("pcvt_raw_binding_mismatch")
    for declaration in a03.get("artifact_bindings", {}).values():
        errors.extend(_verify_repo_artifact(root, declaration))
    for declaration in pcvt.get("accepted_evidence", []):
        try:
            data = _committed_bytes(root, declaration["path"])
        except subprocess.CalledProcessError:
            errors.append(f"missing_pcvt_evidence:{declaration.get('path')}")
            continue
        if hashlib.sha256(data).hexdigest() != declaration.get("sha256"):
            errors.append(f"pcvt_evidence_sha256_mismatch:{declaration.get('path')}")
    return errors


def validate_authoritative_pcvt_registry(
    root: Path, config: Mapping[str, Any]
) -> list[str]:
    """Rebuild the eight raw PCVT bindings from the accepted R0 contracts."""
    t01_path = root / "configs/r0/r0_t01_pcvt_candidate_spec.v1.json"
    t04_path = root / "configs/r0/r0_t04_raw_metric_engine_contract.v1.json"
    try:
        t01 = _load(t01_path)
        t04 = _load(t04_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"authoritative_pcvt_registry_load_failed:{exc}"]

    candidate_by_id = {
        str(row.get("indicator_id")): row
        for row in t01.get("candidate_indicators", [])
        if isinstance(row, Mapping)
    }
    # R0-T04 keeps the raw V2 base metric under its own id while T01 names the
    # downstream percentile candidate V2_AmountLevel20Pct.  This mapping is
    # part of the frozen R0 contract, not a new A04 indicator.
    t01_id_by_raw_id = {
        "V2_LogAmount20_base": "V2_AmountLevel20Pct",
    }
    expected: list[tuple[str, str, str, str]] = []
    errors: list[str] = []
    for raw in t04.get("active_raw_metrics", []):
        if not isinstance(raw, Mapping):
            errors.append("authoritative_pcvt_registry_row_not_object")
            continue
        raw_id = str(raw.get("indicator_id"))
        t01_id = t01_id_by_raw_id.get(raw_id, raw_id)
        candidate = candidate_by_id.get(t01_id)
        if candidate is None:
            errors.append(f"authoritative_pcvt_indicator_missing:{raw_id}")
            continue
        expected.append(
            (
                raw_id,
                str(candidate.get("pcvt_layer")),
                str(raw.get("raw_metric_name")),
                str(candidate.get("raw_value_direction")),
            )
        )

    actual = [
        (
            str(row.get("indicator_id")),
            str(row.get("layer")),
            str(row.get("raw_metric_name")),
            str(row.get("raw_value_direction")),
        )
        for row in config.get("pcvt_indicator_registry", [])
        if isinstance(row, Mapping)
    ]
    if expected != actual:
        errors.append("authoritative_pcvt_registry_mismatch")
    if len(expected) != 8 or len(actual) != 8:
        errors.append("authoritative_pcvt_registry_count_mismatch")
    return errors


def _resolve_manifest_artifact(
    manifest_path: Path, artifact: Mapping[str, Any]
) -> Path | None:
    policy = artifact.get("path_policy")
    path = Path(str(artifact.get("path", "")))
    if policy == "absolute_declared_path":
        return path
    if policy == "relative_to_manifest":
        return (manifest_path.parent / path).resolve()
    if policy == "basename_local_only":
        return manifest_path.parent / path.name
    return None


def validate_authorized_manifest(
    root: Path, manifest_path: Path, *, reviewed_sha: str | None = None
) -> list[str]:
    """Validate the exact ten-artifact manifest without connecting to raw data."""
    if not manifest_path.is_file():
        return ["authorized_manifest_missing"]
    manifest = _load(manifest_path)
    errors = _schema_validate(
        root, "exp_a04_authorized_input_manifest.schema.json", manifest
    )
    expected_ids = {
        "exp_a03_accepted_result_handoff",
        "exp_a03_manifest",
        "exp_a03_validator_result",
        "exp_a03_anomaly_scan",
        "exp_a03_candidate_disposition",
        "exp_a01_raw_metrics",
        "exp_a04_pcvt_raw_accepted_handoff",
        "pcvt_raw_metrics",
        "pcvt_raw_acceptance_evidence",
        "pcvt_raw_validator_or_manifest_evidence",
    }
    actual_ids = set(manifest.get("input_artifacts", {}))
    if actual_ids != expected_ids:
        errors.append("authorized_manifest_exact_ten_artifacts_mismatch")
    bindings = manifest.get("cross_artifact_bindings", {})
    if (
        reviewed_sha is not None
        and bindings.get("a04_reviewed_implementation_sha") != reviewed_sha
    ):
        errors.append("authorized_manifest_reviewed_sha_mismatch")
    for artifact_id, artifact in manifest.get("input_artifacts", {}).items():
        if not isinstance(artifact, Mapping):
            errors.append(f"artifact_not_object:{artifact_id}")
            continue
        path = _resolve_manifest_artifact(manifest_path, artifact)
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"artifact_missing:{artifact_id}")
            continue
        if sha256_file(path) != artifact.get("sha256"):
            errors.append(f"artifact_sha256_mismatch:{artifact_id}")
    return errors


def validate_lineage_inputs(
    root: Path,
    config: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
    reviewed_sha: str | None = None,
) -> list[str]:
    errors = validate_handoffs(root, config)
    errors.extend(validate_authoritative_pcvt_registry(root, config))
    if manifest_path is not None:
        errors.extend(
            validate_authorized_manifest(root, manifest_path, reviewed_sha=reviewed_sha)
        )
    return list(dict.fromkeys(errors))


def _columns(connection: Any, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
    if not rows:
        raise ValidationError(f"missing_table:{table}")
    return {str(row[1]) for row in rows}


def _independent_views(
    connection: Any, pcvt_path: Path, a_table: str, pcvt_table: str
) -> None:
    connection.execute(
        f"ATTACH '{str(pcvt_path).replace(chr(39), chr(39) + chr(39))}' AS v_pcvt (READ_ONLY)"
    )
    a_cols = _columns(connection, a_table)
    p_cols = _columns(connection, f"v_pcvt.{pcvt_table}")
    required_a = {
        "security_id",
        "trading_date",
        "observation_sequence",
        "indicator_id",
        "raw_value",
        "validity_status",
    }
    required_p = {
        "security_id",
        "trading_date",
        "indicator_id",
        "raw_value",
        "validity_status",
    }
    if not required_a <= a_cols or not required_p <= p_cols:
        raise ValidationError("raw_schema_mismatch")
    a_ids = ",".join("'" + value + "'" for value in A_IDS)
    p_ids = ",".join("'" + value + "'" for value in PCVT_IDS)
    a_date = _date_expr("trading_date")
    connection.execute(
        f"""CREATE OR REPLACE TEMP TABLE v_a AS SELECT CAST(security_id AS VARCHAR) security_id,{a_date} trading_date,CAST(indicator_id AS VARCHAR) indicator_id,TRY_CAST(raw_value AS DOUBLE) raw_value FROM "{a_table}" WHERE indicator_id IN ({a_ids}) AND validity_status='valid' AND {a_date} IS NOT NULL AND TRY_CAST(raw_value AS DOUBLE) IS NOT NULL AND isfinite(TRY_CAST(raw_value AS DOUBLE))"""
    )
    connection.execute(
        f"""CREATE OR REPLACE TEMP TABLE v_p AS SELECT CAST(security_id AS VARCHAR) security_id,{_date_expr("trading_date")} trading_date,CAST(indicator_id AS VARCHAR) indicator_id,TRY_CAST(raw_value AS DOUBLE) raw_value FROM v_pcvt."{pcvt_table}" WHERE indicator_id IN ({p_ids}) AND validity_status='valid' AND {_date_expr("trading_date")} IS NOT NULL AND TRY_CAST(raw_value AS DOUBLE) IS NOT NULL AND isfinite(TRY_CAST(raw_value AS DOUBLE))"""
    )
    if connection.execute(
        "SELECT COUNT(*) FROM (SELECT indicator_id,security_id,trading_date FROM v_a GROUP BY ALL HAVING COUNT(*)>1)"
    ).fetchone()[0]:
        raise ValidationError("duplicate_a_security_date_key")
    if connection.execute(
        "SELECT COUNT(*) FROM (SELECT indicator_id,security_id,trading_date FROM v_p GROUP BY ALL HAVING COUNT(*)>1)"
    ).fetchone()[0]:
        raise ValidationError("duplicate_pcvt_security_date_key")
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_pairs AS SELECT a.indicator_id a_id,p.indicator_id p_id,a.security_id,a.trading_date,YEAR(a.trading_date) calendar_year,a.raw_value a_raw,p.raw_value p_raw FROM v_a a JOIN v_p p USING(security_id,trading_date)"""
    )


def _independent_recompute(
    connection: Any, pcvt_path: Path, a_table: str, pcvt_table: str, security_count: int
) -> dict[str, list[dict[str, Any]]]:
    _independent_views(connection, pcvt_path, a_table, pcvt_table)
    pairs = sorted(
        [(f"{A_SHORT[a]}__{p}", a, p, PCVT_LAYER[p]) for a in A_IDS for p in PCVT_IDS]
    )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE v_registry(pair_id VARCHAR,a_id VARCHAR,p_id VARCHAR,layer VARCHAR)"
    )
    connection.executemany("INSERT INTO v_registry VALUES (?,?,?,?)", pairs)
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_join AS SELECT r.pair_id,r.a_id,r.p_id,r.layer,p.security_id,p.trading_date,p.calendar_year,p.a_raw,p.p_raw FROM v_registry r JOIN v_pairs p ON p.a_id=r.a_id AND p.p_id=r.p_id"""
    )
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_rank AS SELECT *,RANK() OVER(PARTITION BY pair_id ORDER BY a_raw)+(COUNT(*) OVER(PARTITION BY pair_id,a_raw)-1)/2.0 a_rank,RANK() OVER(PARTITION BY pair_id ORDER BY p_raw)+(COUNT(*) OVER(PARTITION BY pair_id,p_raw)-1)/2.0 p_rank FROM v_join"""
    )
    overall = [
        dict(zip(CSV_FIELDS["exp_a04_pairwise_overall.csv"], row, strict=True))
        for row in connection.execute(
            """WITH agg AS (SELECT pair_id,COUNT(*) n,CORR(a_raw,p_raw) pearson_raw,CORR(a_rank,p_rank) spearman_midrank FROM v_rank GROUP BY pair_id), a_ties AS (SELECT pair_id,COALESCE(SUM(CASE WHEN n>1 THEN n ELSE 0 END),0) tied FROM (SELECT pair_id,a_raw,COUNT(*) n FROM v_join GROUP BY pair_id,a_raw) GROUP BY pair_id), p_ties AS (SELECT pair_id,COALESCE(SUM(CASE WHEN n>1 THEN n ELSE 0 END),0) tied FROM (SELECT pair_id,p_raw,COUNT(*) n FROM v_join GROUP BY pair_id,p_raw) GROUP BY pair_id) SELECT r.pair_id,r.a_id,r.p_id,r.layer,COALESCE(a.n,0),a.pearson_raw,a.spearman_midrank,COALESCE(a_ties.tied,0),COALESCE(p_ties.tied,0) FROM v_registry r LEFT JOIN agg a USING(pair_id) LEFT JOIN a_ties USING(pair_id) LEFT JOIN p_ties USING(pair_id) ORDER BY r.pair_id"""
        ).fetchall()
    ]
    coverage = [
        dict(zip(CSV_FIELDS["exp_a04_pairwise_coverage.csv"], row, strict=True))
        for row in connection.execute(
            """WITH a AS (SELECT indicator_id,COUNT(*) n FROM v_a GROUP BY indicator_id),p AS (SELECT indicator_id,COUNT(*) n FROM v_p GROUP BY indicator_id),c AS (SELECT a_id,p_id,COUNT(*) n FROM v_pairs GROUP BY a_id,p_id) SELECT r.pair_id,r.a_id,r.p_id,r.layer,COALESCE(a.n,0),COALESCE(p.n,0),COALESCE(c.n,0),COALESCE(c.n,0)::DOUBLE/NULLIF(a.n,0),COALESCE(c.n,0)::DOUBLE/NULLIF(p.n,0),COALESCE(c.n,0)::DOUBLE/NULLIF(LEAST(a.n,p.n),0),'security_id+trading_date_after_strict_uniqueness_proof',TRUE FROM v_registry r LEFT JOIN a ON a.indicator_id=r.a_id LEFT JOIN p ON p.indicator_id=r.p_id LEFT JOIN c ON c.a_id=r.a_id AND c.p_id=r.p_id ORDER BY r.pair_id"""
        ).fetchall()
    ]
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_rank_year AS SELECT *,RANK() OVER(PARTITION BY pair_id,calendar_year ORDER BY a_raw)+(COUNT(*) OVER(PARTITION BY pair_id,calendar_year,a_raw)-1)/2.0 a_rank,RANK() OVER(PARTITION BY pair_id,calendar_year ORDER BY p_raw)+(COUNT(*) OVER(PARTITION BY pair_id,calendar_year,p_raw)-1)/2.0 p_rank FROM v_join"""
    )
    year_sql = """WITH y AS (SELECT * FROM range(2016,2027)),a AS (SELECT pair_id,calendar_year,COUNT(*) n,CORR(a_raw,p_raw) pearson_raw,CORR(a_rank,p_rank) spearman_midrank FROM v_rank_year GROUP BY pair_id,calendar_year) SELECT r.pair_id,r.a_id,r.p_id,r.layer,y.range::INTEGER,COALESCE(a.n,0),a.pearson_raw,a.spearman_midrank,CASE WHEN COALESCE(a.n,0)>0 AND a.spearman_midrank IS NULL THEN 'undefined_correlation' ELSE NULL END FROM v_registry r CROSS JOIN y LEFT JOIN a ON a.pair_id=r.pair_id AND a.calendar_year=y.range ORDER BY r.pair_id,y.range"""
    years = [
        dict(zip(CSV_FIELDS["exp_a04_pairwise_year.csv"], row, strict=True))
        for row in connection.execute(year_sql).fetchall()
    ]
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_rank_sec AS SELECT *,RANK() OVER(PARTITION BY pair_id,security_id ORDER BY a_raw)+(COUNT(*) OVER(PARTITION BY pair_id,security_id,a_raw)-1)/2.0 a_rank,RANK() OVER(PARTITION BY pair_id,security_id ORDER BY p_raw)+(COUNT(*) OVER(PARTITION BY pair_id,security_id,p_raw)-1)/2.0 p_rank FROM v_join"""
    )
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE v_security AS SELECT security_id FROM v_a GROUP BY security_id UNION SELECT security_id FROM v_p GROUP BY security_id"""
    )
    sec_sql = """WITH a AS (SELECT pair_id,security_id,COUNT(*) n,CORR(a_raw,p_raw) pearson_raw,CORR(a_rank,p_rank) spearman_midrank FROM v_rank_sec GROUP BY pair_id,security_id) SELECT r.pair_id,r.a_id,r.p_id,r.layer,s.security_id,COALESCE(a.n,0),CASE WHEN COALESCE(a.n,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN TRUE ELSE FALSE END,CASE WHEN COALESCE(a.n,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN a.pearson_raw ELSE NULL END,CASE WHEN COALESCE(a.n,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN a.spearman_midrank ELSE NULL END,CASE WHEN COALESCE(a.n,0)<100 THEN 'insufficient_common_rows' WHEN a.pearson_raw IS NULL OR a.spearman_midrank IS NULL OR NOT isfinite(a.pearson_raw) OR NOT isfinite(a.spearman_midrank) THEN 'undefined_correlation_constant_input' ELSE NULL END FROM v_registry r CROSS JOIN v_security s LEFT JOIN a ON a.pair_id=r.pair_id AND a.security_id=s.security_id ORDER BY r.pair_id,s.security_id"""
    securities = [
        dict(zip(CSV_FIELDS["exp_a04_pairwise_security.csv"], row, strict=True))
        for row in connection.execute(sec_sql).fetchall()
    ]
    tails: list[dict[str, Any]] = []
    for pair_id, a_id, p_id, layer in pairs:
        for fraction in TAILS:
            row = connection.execute(
                f"""WITH q AS (SELECT QUANTILE_DISC(a_raw,{fraction}) a_threshold,QUANTILE_DISC(p_raw,{fraction}) p_threshold FROM v_join WHERE pair_id='{pair_id}'),f AS (SELECT a_raw<=(SELECT a_threshold FROM q) aa,p_raw<=(SELECT p_threshold FROM q) pp FROM v_join WHERE pair_id='{pair_id}') SELECT (SELECT a_threshold FROM q),(SELECT p_threshold FROM q),COUNT(*) FILTER(WHERE aa),COUNT(*) FILTER(WHERE pp),COUNT(*) FILTER(WHERE aa AND pp),COUNT(*) FILTER(WHERE aa OR pp),COUNT(*) FROM f"""
            ).fetchone()
            at, pt, ac, pc, inter, union, total = row
            ac, pc, inter, union, total = [
                int(value or 0) for value in (ac, pc, inter, union, total)
            ]
            tails.append(
                {
                    "pair_id": pair_id,
                    "a_candidate_id": a_id,
                    "pcvt_indicator_id": p_id,
                    "pcvt_layer": layer,
                    "tail_fraction": fraction,
                    "a_threshold": at,
                    "pcvt_threshold": pt,
                    "a_selected_count": ac,
                    "a_realized_rate": ac / total if total else None,
                    "pcvt_selected_count": pc,
                    "pcvt_realized_rate": pc / total if total else None,
                    "intersection_count": inter,
                    "union_count": union,
                    "jaccard": inter / union if union else None,
                    "a_containment": inter / ac if ac else None,
                    "pcvt_containment": inter / pc if pc else None,
                }
            )
    return {
        "pairwise_coverage": coverage,
        "pairwise_overall": overall,
        "pairwise_year": years,
        "pairwise_security": securities,
        "tail_overlap": tails,
    }


def _parse_cell(value: str) -> Any:
    if value == "":
        return None
    if value in {"True", "true"}:
        return True
    if value in {"False", "false"}:
        return False
    try:
        return int(value) if re.fullmatch(r"-?\d+", value) else float(value)
    except ValueError:
        return value


def _read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != fields:
            raise ValidationError(f"csv_fields_mismatch:{path.name}")
        return [
            {key: _parse_cell(value) for key, value in row.items()} for row in reader
        ]


def _same(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, int | float) and isinstance(right, int | float):
        if not math.isfinite(float(left)) or not math.isfinite(float(right)):
            return False
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return str(left) == str(right)


def _compare_rows(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]], name: str
) -> list[str]:
    errors: list[str] = []
    if len(expected) != len(actual):
        return [f"row_count_mismatch:{name}:{len(actual)}!={len(expected)}"]
    for index, (exp, got) in enumerate(zip(expected, actual, strict=True)):
        for field in exp:
            if not _same(exp.get(field), got.get(field)):
                errors.append(f"aggregate_mismatch:{name}:{index}:{field}")
                break
    return errors


def _independent_collisions(
    metrics: Mapping[str, list[dict[str, Any]]],
) -> dict[str, bool]:
    overall = {row["pair_id"]: row for row in metrics["pairwise_overall"]}
    years: dict[str, list[float]] = {}
    securities: dict[str, list[float]] = {}
    tails = {
        (row["pair_id"], float(row["tail_fraction"])): row
        for row in metrics["tail_overlap"]
    }
    for row in metrics["pairwise_year"]:
        if row["common_count"] > 0 and row["spearman_midrank"] is not None:
            years.setdefault(row["pair_id"], []).append(float(row["spearman_midrank"]))
    for row in metrics["pairwise_security"]:
        if row["eligible"] and row["spearman_midrank"] is not None:
            securities.setdefault(row["pair_id"], []).append(
                float(row["spearman_midrank"])
            )
    out: dict[str, bool] = {}
    for pair_id, row in overall.items():
        y = years.get(pair_id, [])
        s = sorted(securities.get(pair_id, []))
        q10 = _quantile_cont(s, 0.1)
        out[pair_id] = bool(
            row["spearman_midrank"] is not None
            and row["spearman_midrank"] >= 0.95
            and y
            and min(y) >= 0.9
            and q10 is not None
            and q10 >= 0.8
            and tails[(pair_id, 0.05)]["jaccard"] is not None
            and tails[(pair_id, 0.05)]["jaccard"] >= 0.8
            and tails[(pair_id, 0.1)]["jaccard"] is not None
            and tails[(pair_id, 0.1)]["jaccard"] >= 0.8
        )
    return out


def _collision_payloads(
    metrics: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    overall = {row["pair_id"]: row for row in metrics["pairwise_overall"]}
    years: dict[str, list[float]] = {}
    securities: dict[str, list[float]] = {}
    tails = {
        (row["pair_id"], float(row["tail_fraction"])): row
        for row in metrics["tail_overlap"]
    }
    for row in metrics["pairwise_year"]:
        if row["common_count"] > 0 and row["spearman_midrank"] is not None:
            years.setdefault(row["pair_id"], []).append(float(row["spearman_midrank"]))
    for row in metrics["pairwise_security"]:
        if row["eligible"] and row["spearman_midrank"] is not None:
            securities.setdefault(row["pair_id"], []).append(
                float(row["spearman_midrank"])
            )
    payloads: list[dict[str, Any]] = []
    for pair_id in sorted(overall):
        row = overall[pair_id]
        y = years.get(pair_id, [])
        s = securities.get(pair_id, [])
        q10 = _quantile_cont(s, 0.1)
        values = {
            "overall_spearman": (row["spearman_midrank"], 0.95),
            "minimum_year_spearman": (min(y) if y else None, 0.90),
            "eligible_security_spearman_q10": (q10, 0.80),
            "tail_jaccard_005": (tails[(pair_id, 0.05)]["jaccard"], 0.80),
            "tail_jaccard_010": (tails[(pair_id, 0.1)]["jaccard"], 0.80),
        }
        criteria = {
            name: {
                "actual": actual,
                "threshold": threshold,
                "passed": actual is not None and actual >= threshold,
            }
            for name, (actual, threshold) in values.items()
        }
        payloads.append(
            {
                "pair_id": pair_id,
                "a_candidate_id": row["a_candidate_id"],
                "pcvt_indicator_id": row["pcvt_indicator_id"],
                "pcvt_layer": row["pcvt_layer"],
                "criteria": criteria,
                "hard_cross_layer_collision": all(
                    item["passed"] for item in criteria.values()
                ),
            }
        )
    return payloads


def _best(
    rows: list[dict[str, Any]], field: str, layer_order: Mapping[str, int]
) -> dict[str, Any] | None:
    eligible = [row for row in rows if row.get(field) is not None]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda row: (
            -round(float(row[field]), 12),
            layer_order[row["pcvt_layer"]],
            row["pcvt_indicator_id"],
        ),
    )[0]


def _independent_summaries(
    metrics: Mapping[str, list[dict[str, Any]]],
    collision_payloads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layer_order = {"P": 0, "C": 1, "T": 2, "V": 3}
    overall = metrics["pairwise_overall"]
    coverage = {row["pair_id"]: row for row in metrics["pairwise_coverage"]}
    tails = {
        (row["pair_id"], float(row["tail_fraction"])): row
        for row in metrics["tail_overlap"]
    }
    collisions = {row["pair_id"]: row for row in collision_payloads}
    securities: dict[str, list[dict[str, Any]]] = {}
    for row in metrics["pairwise_security"]:
        securities.setdefault(row["pair_id"], []).append(row)
    layers: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for candidate in A_IDS:
        pair_rows = [row for row in overall if row["a_candidate_id"] == candidate]
        for layer in ("P", "C", "T", "V"):
            rows = [row for row in pair_rows if row["pcvt_layer"] == layer]
            by_spearman = _best(rows, "spearman_midrank", layer_order)
            tail5 = [
                {**row, "metric": tails[(row["pair_id"], 0.05)]["jaccard"]}
                for row in rows
            ]
            tail10 = [
                {**row, "metric": tails[(row["pair_id"], 0.1)]["jaccard"]}
                for row in rows
            ]
            best5 = _best(tail5, "metric", layer_order)
            best10 = _best(tail10, "metric", layer_order)
            hard_ids = sorted(
                row["pcvt_indicator_id"]
                for row in rows
                if collisions[row["pair_id"]]["hard_cross_layer_collision"]
            )
            layers.append(
                {
                    "a_candidate_id": candidate,
                    "pcvt_layer": layer,
                    "indicator_pair_count": len(rows),
                    "valid_pair_count": sum(row["common_count"] > 0 for row in rows),
                    "nearest_indicator_by_spearman": by_spearman["pcvt_indicator_id"]
                    if by_spearman
                    else None,
                    "max_overall_spearman": by_spearman["spearman_midrank"]
                    if by_spearman
                    else None,
                    "nearest_indicator_by_tail_jaccard_005": best5["pcvt_indicator_id"]
                    if best5
                    else None,
                    "max_tail_jaccard_005": best5["metric"] if best5 else None,
                    "nearest_indicator_by_tail_jaccard_010": best10["pcvt_indicator_id"]
                    if best10
                    else None,
                    "max_tail_jaccard_010": best10["metric"] if best10 else None,
                    "hard_collision_count": len(hard_ids),
                    "hard_collision_indicator_ids_json": json.dumps(
                        hard_ids, separators=(",", ":")
                    ),
                }
            )
        by_spearman = _best(pair_rows, "spearman_midrank", layer_order)
        tail5 = [
            {**row, "metric": tails[(row["pair_id"], 0.05)]["jaccard"]}
            for row in pair_rows
        ]
        tail10 = [
            {**row, "metric": tails[(row["pair_id"], 0.1)]["jaccard"]}
            for row in pair_rows
        ]
        best5 = _best(tail5, "metric", layer_order)
        best10 = _best(tail10, "metric", layer_order)
        hard_pairs = sorted(
            row["pair_id"]
            for row in pair_rows
            if collisions[row["pair_id"]]["hard_cross_layer_collision"]
        )
        low_coverage = sum(
            coverage[row["pair_id"]]["common_rate_of_smaller_side"] is not None
            and coverage[row["pair_id"]]["common_rate_of_smaller_side"] < 0.8
            for row in pair_rows
        )
        eligible = sum(
            sum(item["eligible"] for item in securities.get(row["pair_id"], [])) >= 720
            and coverage[row["pair_id"]]["common_rate_of_smaller_side"] is not None
            and coverage[row["pair_id"]]["common_rate_of_smaller_side"] >= 0.8
            for row in pair_rows
        )
        candidates.append(
            {
                "a_candidate_id": candidate,
                "nearest_layer": by_spearman["pcvt_layer"] if by_spearman else None,
                "nearest_indicator": by_spearman["pcvt_indicator_id"]
                if by_spearman
                else None,
                "max_overall_spearman": by_spearman["spearman_midrank"]
                if by_spearman
                else None,
                "max_tail_jaccard_005": best5["metric"] if best5 else None,
                "max_tail_jaccard_010": best10["metric"] if best10 else None,
                "hard_collision_count": len(hard_pairs),
                "hard_collision_pairs_json": json.dumps(
                    hard_pairs, separators=(",", ":")
                ),
                "eligible_pair_count": eligible,
                "low_coverage_pair_count": low_coverage,
                "provisional_status_for_A05": "carry_to_A05_with_collision_review"
                if hard_pairs
                else "carry_to_A05",
            }
        )
    return layers, candidates


def validate_formal_result(
    package_root: Path,
    *,
    config: Mapping[str, Any],
    a_raw_path: Path,
    pcvt_raw_path: Path,
    a_table: str = "exp_a01_raw_metrics",
    pcvt_table: str = "r0_t04_raw_metric_results",
    repo_root: Path | None = None,
    input_manifest_path: Path | None = None,
    reviewed_sha: str | None = None,
    run_id: str | None = None,
    synthetic_fixture: bool = False,
    require_final_manifest: bool = True,
) -> dict[str, Any]:
    """Replay lineage and all compact aggregates from disk."""
    errors: list[str] = []
    warnings: list[str] = []
    if repo_root is not None:
        errors.extend(
            validate_lineage_inputs(
                repo_root,
                config,
                manifest_path=input_manifest_path,
                reviewed_sha=reviewed_sha,
            )
        )
    actual_files = (
        {path.name for path in package_root.iterdir() if path.is_file()}
        if package_root.is_dir()
        else set()
    )
    if require_final_manifest and actual_files != OUTPUT_FILES:
        errors.append("exact_output_file_set_mismatch")
    if any(
        path.suffix.lower() in {".duckdb", ".parquet"}
        for path in package_root.iterdir()
        if path.is_file()
    ):
        errors.append("forbidden_output_file")
    metrics: dict[str, list[dict[str, Any]]] = {}
    try:
        for filename, fields in CSV_FIELDS.items():
            key = filename.removeprefix("exp_a04_").removesuffix(".csv")
            metrics[key] = _read_csv(package_root / filename, fields)
    except (OSError, ValidationError) as exc:
        errors.append(str(exc))
    try:
        connection = duckdb.connect(
            str(a_raw_path), read_only=True, config={"threads": "1"}
        )
        try:
            recomputed = _independent_recompute(
                connection,
                pcvt_raw_path,
                a_table,
                pcvt_table,
                len(
                    {row["security_id"] for row in metrics.get("pairwise_security", [])}
                ),
            )
        finally:
            connection.close()
        for key in (
            "pairwise_coverage",
            "pairwise_overall",
            "pairwise_year",
            "pairwise_security",
            "tail_overlap",
        ):
            filename = f"exp_a04_{key}.csv"
            errors.extend(
                _compare_rows(recomputed[key], metrics.get(key, []), filename)
            )
        expected_registry = [
            {
                "registry_role": "PCVT",
                "indicator_id": indicator["indicator_id"],
                "layer": indicator["layer"],
                "raw_metric_name": indicator["raw_metric_name"],
                "raw_source_indicator_id": indicator["raw_source_indicator_id"],
                "raw_value_direction": indicator["raw_value_direction"],
            }
            for indicator in config["pcvt_indicator_registry"]
        ] + [
            {
                "registry_role": "A",
                "indicator_id": candidate,
                "layer": "A",
                "raw_metric_name": A_RAW_NAMES[candidate],
                "raw_source_indicator_id": candidate,
                "raw_value_direction": "lower_raw_is_more_convergent",
            }
            for candidate in A_IDS
        ]
        errors.extend(
            _compare_rows(
                expected_registry,
                metrics.get("indicator_registry", []),
                "exp_a04_indicator_registry.csv",
            )
        )
        collision_payloads = _collision_payloads(recomputed)
        expected_layers, expected_candidates = _independent_summaries(
            recomputed, collision_payloads
        )
        errors.extend(
            _compare_rows(
                expected_layers,
                metrics.get("layer_summary", []),
                "exp_a04_layer_summary.csv",
            )
        )
        errors.extend(
            _compare_rows(
                expected_candidates,
                metrics.get("candidate_summary", []),
                "exp_a04_candidate_summary.csv",
            )
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"independent_raw_replay:{exc}")
    disposition_path = package_root / "exp_a04_cross_layer_disposition.json"
    disposition: Mapping[str, Any] = {}
    if disposition_path.is_file():
        disposition = _load(disposition_path)
        if disposition.get("candidate_set_for_A05") != ["A1", "A2", "A2b"]:
            errors.append("candidate_set_auto_reduced")
        if (
            disposition.get("pair_count") != 24
            or len(disposition.get("pair_collision_results", [])) != 24
        ):
            errors.append("disposition_pair_count_mismatch")
        actual_collisions = disposition.get("pair_collision_results", [])
        if len(actual_collisions) == len(collision_payloads):
            for expected, actual in zip(
                collision_payloads, actual_collisions, strict=True
            ):
                if expected.get("pair_id") != actual.get("pair_id") or expected.get(
                    "hard_cross_layer_collision"
                ) != actual.get("hard_cross_layer_collision"):
                    errors.append(
                        f"collision_result_mismatch:{expected.get('pair_id')}"
                    )
                    break
        for candidate in ("A1", "A2", "A2b"):
            expected = next(
                row
                for row in expected_candidates
                if A_SHORT[row["a_candidate_id"]] == candidate
            )
            actual = disposition.get("candidate_collision_summary", {}).get(
                candidate, {}
            )
            if (
                actual.get("hard_collision_count") != expected["hard_collision_count"]
                or actual.get("provisional_status_for_A05")
                != expected["provisional_status_for_A05"]
            ):
                errors.append(f"candidate_collision_summary_mismatch:{candidate}")
        forbidden = {
            "winner",
            "selected_final_indicator",
            "registered_layer",
            "formal_A_score",
            "formal_A_state",
        }
        if forbidden & set(disposition):
            errors.append("forbidden_disposition_field")
        if (
            disposition.get("EXP_A05_started") is not False
            or disposition.get("A_layer_registered") is not False
            or disposition.get("PCATV_created") is not False
        ):
            errors.append("governance_flag_mismatch")
    else:
        errors.append("disposition_missing")
    analysis_path = package_root / "exp_a04_result_analysis.md"
    if analysis_path.is_file():
        text = analysis_path.read_text(encoding="utf-8")
        positions = [text.find(heading) for heading in config["analysis_headings"]]
        if any(position < 0 for position in positions) or positions != sorted(
            positions
        ):
            errors.append("analysis_heading_contract")
        readiness = text.rstrip().splitlines()[-1] if text.rstrip() else ""
        expected_readiness = (
            "needs_investigation_before_user_review"
            if synthetic_fixture
            else {
                "passed": "ready_for_user_formal_result_review",
                "passed_with_investigation_items": "needs_investigation_before_user_review",
            }.get(_load(package_root / "exp_a04_anomaly_scan.json").get("status"), "")
            if (package_root / "exp_a04_anomaly_scan.json").is_file()
            else ""
        )
        if readiness != expected_readiness:
            errors.append("analysis_readiness_contract")
    elif require_final_manifest:
        errors.append("analysis_missing")
    validator_path = package_root / "exp_a04_validator_result.json"
    result = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": warnings,
        "lineage_replayed_from_disk": repo_root is not None,
        "full_set_based_invariant_scan_performed": True,
        "full_output_aggregate_recompute_performed": True,
        "core_validator_execution_count": 1,
        "mismatch_counts": {"total": len(errors)},
    }
    if require_final_manifest and validator_path.is_file():
        persisted = _load(validator_path)
        if persisted.get("status") != result["status"]:
            result["errors"].append("persisted_validator_status_mismatch")
            result["status"] = "failed"
            result["valid"] = False
    return result


def cheap_validate_final_package(
    package_root: Path, *, run_id: str, synthetic_fixture: bool
) -> dict[str, Any]:
    """Validate only compact package shape and hashes; never opens raw inputs."""
    errors: list[str] = []
    if not package_root.is_dir():
        errors.append("package_missing")
    else:
        actual = {path.name for path in package_root.iterdir() if path.is_file()}
        if actual != OUTPUT_FILES:
            errors.append("exact_output_file_set_mismatch")
        if any(
            path.suffix.lower() in {".duckdb", ".parquet"}
            for path in package_root.iterdir()
            if path.is_file()
        ):
            errors.append("forbidden_output_file")
        manifest_path = package_root / "exp_a04_manifest.json"
        if not manifest_path.is_file():
            errors.append("manifest_missing")
        else:
            manifest = _load(manifest_path)
            if (
                manifest.get("task_id") != TASK_ID
                or manifest.get("run_id") != run_id
                or manifest.get("final_manifest") is not True
            ):
                errors.append("manifest_identity_mismatch")
            if manifest.get("formal_data_version") is not False or manifest.get(
                "formal_run_executed"
            ) is not (not synthetic_fixture):
                errors.append("manifest_execution_mode_mismatch")
            for filename, sha in manifest.get("output_artifacts", {}).items():
                path = package_root / filename
                if not path.is_file() or sha.get("sha256") != sha256_file(path):
                    errors.append(f"output_hash_mismatch:{filename}")
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
