# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t15_layer_q_vector_materialization.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t15_layer_q_vector_materialization.schema.json"
TASK_ID = "R0-T15"
EPSILON = 1e-12

DIMENSION_DB = "r0_t15_dimension_state_results.duckdb"
NESTED_DB = "r0_t15_nested_daily_state_results.duckdb"
DAILY_DB = "r0_t15_daily_confirmation_results.duckdb"
INTERVAL_DB = "r0_t15_confirmed_interval_results.duckdb"
DIMENSION_TABLE = "r0_t15_dimension_state_results"
NESTED_TABLE = "r0_t15_nested_daily_state_results"
DAILY_TABLE = "r0_t15_daily_confirmation_results"
INTERVAL_TABLE = "r0_t15_confirmed_interval_results"


class R0T15Error(RuntimeError):
    pass


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def materialize_r0_t15_layer_q_vectors(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    verify_input_hashes: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _load_json(config_path)
    Draft202012Validator(_load_json(SCHEMA_PATH)).validate(config)
    binding, request, inputs = _verify_inputs(config, verify_input_hashes)
    registry = build_formal_registry(request, config)
    _write_csv(output_dir / "r0_t15_candidate_registry.csv", registry)
    write_json_atomic(output_dir / "r0_t15_request_binding.json", binding)
    print(
        f"heartbeat task={TASK_ID} run_id={run_id} phase=input_verified "
        f"registry={len(registry)} materialize={sum(row['materialize'] for row in registry)}",
        flush=True,
    )

    import duckdb  # noqa: PLC0415

    output_paths = {
        "dimension_state": output_dir / DIMENSION_DB,
        "nested_daily_state": output_dir / NESTED_DB,
        "daily_confirmation": output_dir / DAILY_DB,
        "confirmed_interval": output_dir / INTERVAL_DB,
    }
    for path in output_paths.values():
        if path.exists():
            raise R0T15Error(f"immutable_output_exists:{path}")
    con = duckdb.connect()
    try:
        con.execute(f"SET threads={int(config['parallelism']['duckdb_threads'])}")
        con.execute(
            "SET memory_limit=?", [config["parallelism"]["duckdb_memory_limit"]]
        )
        con.execute("SET preserve_insertion_order=true")
        _attach_inputs_and_outputs(con, inputs, output_paths)
        _create_output_tables(con)
        reconciliation: list[dict[str, Any]] = []
        vector_stats: list[dict[str, Any]] = []
        for index, vector in enumerate(registry, start=1):
            print(
                f"heartbeat task={TASK_ID} phase=vector_start "
                f"completed={index - 1}/{len(registry)} vector={vector['candidate_q_vector_id']}",
                flush=True,
            )
            _create_vector_tables(con, vector)
            if vector["materialize"]:
                _insert_vector_outputs(con, vector, request["request_id"])
                vector_stats.extend(_vector_stats(con, vector))
            else:
                reconciliation.extend(_baseline_reconciliation(con, vector))
            _drop_vector_tables(con)
            print(
                f"heartbeat task={TASK_ID} phase=vector_complete "
                f"completed={index}/{len(registry)} vector={vector['candidate_q_vector_id']}",
                flush=True,
            )
        table_summaries = _table_summaries(con)
        integrity = _integrity_checks(con, registry, table_summaries)
        for alias in ("dimout", "nestedout", "dailyout", "intervalout"):
            con.execute(f"CHECKPOINT {alias}")
    finally:
        con.close()

    _write_csv(output_dir / "r0_t15_upstream_reconciliation.csv", reconciliation)
    anomaly = build_anomaly_scan(registry, reconciliation, vector_stats, integrity)
    write_json_atomic(output_dir / "r0_t15_anomaly_scan.json", anomaly)
    output_records = _output_records(output_paths, table_summaries)
    manifest = build_artifact_manifest(
        run_id=run_id,
        code_commit=code_commit,
        config=config,
        binding=binding,
        registry=registry,
        outputs=output_records,
    )
    write_json_atomic(output_dir / "r0_t15_artifact_manifest.json", manifest)
    handoff = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "handoff_status": "author_draft_candidate",
        "artifact_manifest_path": _rel(output_dir / "r0_t15_artifact_manifest.json"),
        "artifact_manifest_sha256": sha256_file(
            output_dir / "r0_t15_artifact_manifest.json"
        ),
        "candidate_registry_path": _rel(output_dir / "r0_t15_candidate_registry.csv"),
        "candidate_registry_sha256": sha256_file(
            output_dir / "r0_t15_candidate_registry.csv"
        ),
        "upstream_binding": binding,
        "goal_internal_continuation_gate_status": "pending_author_analysis",
        "goal_internal_continuation_allowed": False,
        "goal_internal_t14_02_authorized": False,
        "repository_t14_02_gate_passed": False,
        "R1-T14-02_allowed_to_start": False,
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
    }
    write_json_atomic(output_dir / "r0_t15_authorized_handoff_manifest.json", handoff)
    schema_validation = {
        "task_id": TASK_ID,
        "status": "passed" if integrity["schema_status"] == "passed" else "failed",
        "tables": table_summaries,
        "schema_status": integrity["schema_status"],
        "primary_key_status": integrity["primary_key_status"],
    }
    write_json_atomic(output_dir / "r0_t15_schema_validation.json", schema_validation)
    final_gate = {
        "task_id": TASK_ID,
        "status": "pending_external_review",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "R1-T14-02_allowed_to_start": False,
    }
    write_json_atomic(
        output_dir / "r0_t15_final_gate_validation_result.json", final_gate
    )
    summary = {
        "task_id": TASK_ID,
        "stage": "R0",
        "task_class": "formal_materialization_bridge",
        "run_id": run_id,
        "code_commit": code_commit,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "runtime_seconds": time.monotonic() - started,
        "config_path": _rel(config_path),
        "config_sha256": sha256_file(config_path),
        "upstream_binding": binding,
        "registry_count": len(registry),
        "materialized_vector_count": sum(row["materialize"] for row in registry),
        "baseline_reference_count": sum(not row["materialize"] for row in registry),
        "outputs": output_records,
        "baseline_reconciliation_mismatch_count": sum(
            int(row["mismatch_count"]) for row in reconciliation
        ),
        "anomaly_scan_status": anomaly["status"],
        "anomaly_resolution_status": anomaly["anomaly_resolution_status"],
        "engineering_validator_status": "pending",
        "author_result_analysis_status": "pending",
        "R0_q_vector_materialization_status": "author_analysis_pending",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "goal_internal_continuation_gate_status": "pending_author_analysis",
        "goal_internal_continuation_allowed": False,
        "R1-T14-02_allowed_to_start": False,
        "formal_task_completed": False,
    }
    write_json_atomic(output_dir / "r0_t15_execution_summary.json", summary)
    return summary


def _verify_inputs(
    config: Mapping[str, Any], verify_hashes: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    upstream = dict(config["upstream_binding"])
    paths = {
        "upstream_result_package": upstream["upstream_result_package_path"],
        "upstream_author_analysis": upstream["upstream_author_analysis_path"],
        "materialization_request": upstream["materialization_request_path"],
    }
    expected = {
        "upstream_result_package": upstream["upstream_result_package_sha256"],
        "upstream_author_analysis": upstream["upstream_author_analysis_sha256"],
        "materialization_request": upstream["materialization_request_sha256"],
    }
    for name, relative in paths.items():
        path = ROOT / relative
        if not path.is_file():
            raise R0T15Error(f"upstream_missing:{name}")
        if verify_hashes and sha256_file(path) != expected[name]:
            raise R0T15Error(f"upstream_hash_mismatch:{name}")
    request = _load_json(ROOT / paths["materialization_request"])
    if request.get("decision") != "q_vector_materialization_request":
        raise R0T15Error("upstream_request_decision_invalid")
    if request.get("goal_internal_continuation_gate_status") != "passed":
        raise R0T15Error("upstream_internal_gate_not_passed")
    if request.get("scientific_review_status") != "pending":
        raise R0T15Error("upstream_review_boundary_changed")
    if upstream["repository_r0_materialization_gate_passed"] is not False:
        raise R0T15Error("repository_gate_must_remain_pending")
    _assert_upstream_commit_ancestor(upstream["upstream_head_commit"])
    inputs: dict[str, dict[str, Any]] = {}
    for name, item in config["input_artifacts"].items():
        path = ROOT / item["path"]
        if not path.is_file():
            raise R0T15Error(f"input_missing:{name}")
        actual = sha256_file(path) if verify_hashes else item["sha256"]
        if verify_hashes and actual != item["sha256"]:
            raise R0T15Error(f"input_hash_mismatch:{name}")
        inputs[name] = {
            **dict(item),
            "absolute_path": str(path),
            "actual_sha256": actual,
        }
    binding = {
        **upstream,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "upstream_result_package_actual_sha256": expected["upstream_result_package"],
        "upstream_author_analysis_actual_sha256": expected["upstream_author_analysis"],
        "materialization_request_actual_sha256": expected["materialization_request"],
    }
    return binding, request, inputs


def _assert_upstream_commit_ancestor(commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT
    )
    if result.returncode != 0:
        raise R0T15Error("upstream_head_commit_not_ancestor")


def build_formal_registry(
    request: Mapping[str, Any], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    frozen = request.get("frozen_registry", [])
    if len(frozen) != config["materialization"]["expected_total_registry_count"]:
        raise R0T15Error("request_registry_count_mismatch")
    output: list[dict[str, Any]] = []
    for row in frozen:
        fields = [
            row["W"],
            row["K"],
            row["qP"],
            row["qC"],
            row["qT"],
            row["qV"],
            row["state_line_role"],
            request["request_id"],
        ]
        digest = hashlib.sha256(
            "|".join(str(value) for value in fields).encode()
        ).hexdigest()[:20]
        output.append(
            {
                "formal_vector_id": f"R0T15_{digest}",
                "candidate_q_vector_id": row["candidate_q_vector_id"],
                "request_id": request["request_id"],
                "W": int(row["W"]),
                "K": int(row["K"]),
                "qP": float(row["qP"]),
                "qC": float(row["qC"]),
                "qT": float(row["qT"]),
                "qV": float(row["qV"]),
                "state_line_role": row["state_line_role"],
                "request_role": row["request_role"],
                "archetype": row["archetype"],
                "center_id": row["center_id"],
                "same_parameter_parent_id": row["same_parameter_parent_id"],
                "materialize": row["request_role"] != "baseline_reference",
                "baseline_reuse": row["request_role"] == "baseline_reference",
                "selection_reason": row["selection_reason"],
                "warnings": row["warnings"],
            }
        )
    if len({row["formal_vector_id"] for row in output}) != len(output):
        raise R0T15Error("formal_vector_id_collision")
    if (
        sum(row["materialize"] for row in output)
        != config["materialization"]["expected_nonbaseline_vector_count"]
    ):
        raise R0T15Error("nonbaseline_registry_count_mismatch")
    return output


def _attach_inputs_and_outputs(
    con: Any,
    inputs: Mapping[str, Mapping[str, Any]],
    output_paths: Mapping[str, Path],
) -> None:
    for alias, name in (
        ("scoredb", "dimension_score"),
        ("dailydb", "baseline_daily_confirmation"),
        ("intervaldb", "baseline_confirmed_interval"),
    ):
        con.execute(
            f"ATTACH '{_sql_literal(inputs[name]['absolute_path'])}' AS {alias} (READ_ONLY)"
        )
    for alias, key in (
        ("dimout", "dimension_state"),
        ("nestedout", "nested_daily_state"),
        ("dailyout", "daily_confirmation"),
        ("intervalout", "confirmed_interval"),
    ):
        con.execute(f"ATTACH '{_sql_literal(str(output_paths[key]))}' AS {alias}")


def _create_output_tables(con: Any) -> None:
    con.execute(
        f"""
        CREATE TABLE dimout.{DIMENSION_TABLE}(
          formal_vector_id VARCHAR,candidate_q_vector_id VARCHAR,request_id VARCHAR,
          security_id VARCHAR,trading_date VARCHAR,W INTEGER,K INTEGER,
          qP DOUBLE,qC DOUBLE,qT DOUBLE,qV DOUBLE,dimension VARCHAR,q_dimension DOUBLE,
          weak_delta DOUBLE,score_dimension DOUBLE,score_dimension_min DOUBLE,
          eligible_dimension BOOLEAN,dimension_active_weak BOOLEAN,validity_status VARCHAR,
          reason_codes VARCHAR[],component_indicator_ids VARCHAR[],state_engine_version VARCHAR
        );
        CREATE TABLE nestedout.{NESTED_TABLE}(
          formal_vector_id VARCHAR,candidate_q_vector_id VARCHAR,request_id VARCHAR,
          security_id VARCHAR,trading_date VARCHAR,W INTEGER,K INTEGER,
          qP DOUBLE,qC DOUBLE,qT DOUBLE,qV DOUBLE,weak_delta DOUBLE,
          P_raw BOOLEAN,C_raw BOOLEAN,T_raw BOOLEAN,V_raw BOOLEAN,
          S_P_raw BOOLEAN,S_PC_raw BOOLEAN,S_PCT_raw BOOLEAN,S_PCVT_raw BOOLEAN,
          S_P_validity_status VARCHAR,S_PC_validity_status VARCHAR,
          S_PCT_validity_status VARCHAR,S_PCVT_validity_status VARCHAR,
          S_P_reason_codes VARCHAR[],S_PC_reason_codes VARCHAR[],
          S_PCT_reason_codes VARCHAR[],S_PCVT_reason_codes VARCHAR[],
          state_engine_version VARCHAR
        );
        CREATE TABLE dailyout.{DAILY_TABLE}(
          formal_vector_id VARCHAR,candidate_q_vector_id VARCHAR,request_id VARCHAR,
          security_id VARCHAR,trading_date VARCHAR,W INTEGER,K INTEGER,
          qP DOUBLE,qC DOUBLE,qT DOUBLE,qV DOUBLE,weak_delta DOUBLE,state_name VARCHAR,
          raw_state BOOLEAN,raw_streak INTEGER,raw_streak_start_date VARCHAR,
          confirmed_state BOOLEAN,confirmation_start_date VARCHAR,confirmation_date VARCHAR,
          validity_status VARCHAR,reason_codes VARCHAR[],confirmation_engine_version VARCHAR
        );
        CREATE TABLE intervalout.{INTERVAL_TABLE}(
          formal_vector_id VARCHAR,candidate_q_vector_id VARCHAR,request_id VARCHAR,
          interval_id VARCHAR,security_id VARCHAR,W INTEGER,K INTEGER,
          qP DOUBLE,qC DOUBLE,qT DOUBLE,qV DOUBLE,weak_delta DOUBLE,state_name VARCHAR,
          raw_start_date VARCHAR,confirmation_date VARCHAR,confirmed_start_date VARCHAR,
          interval_end_date VARCHAR,last_observed_date VARCHAR,raw_duration_observations INTEGER,
          confirmed_duration_observations INTEGER,is_open_interval BOOLEAN,
          termination_reason VARCHAR,validity_status VARCHAR,reason_codes VARCHAR[],
          confirmation_engine_version VARCHAR
        )
        """
    )


def _create_vector_tables(con: Any, vector: Mapping[str, Any]) -> None:
    con.execute(
        """
        CREATE TEMP TABLE vector_dimension AS
        SELECT security_id,trading_date,CAST(percentile_window_W AS INTEGER) AS W,
          dimension,
          CASE dimension WHEN 'P' THEN ? WHEN 'C' THEN ? WHEN 'T' THEN ? ELSE ? END AS q_dimension,
          0.1::DOUBLE AS weak_delta,score_dimension,score_dimension_min,eligible_dimension,
          CASE WHEN eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL
            THEN score_dimension+1e-12 >= 1.0-(CASE dimension WHEN 'P' THEN ? WHEN 'C' THEN ? WHEN 'T' THEN ? ELSE ? END)
              AND score_dimension_min+1e-12 >= 1.0-(CASE dimension WHEN 'P' THEN ? WHEN 'C' THEN ? WHEN 'T' THEN ? ELSE ? END)-0.1
            ELSE NULL END AS dimension_active_weak,
          CASE WHEN eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL THEN 'valid' ELSE validity_status END AS validity_status,
          CASE WHEN eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL THEN ['valid_no_blocker'] ELSE reason_codes END AS reason_codes,
          component_indicator_ids,'r0_t15_layer_q_vector_materialization.v1' AS state_engine_version
        FROM scoredb.r0_t05_dimension_score_results
        WHERE percentile_window_W=?
        """,
        [
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
            vector["W"],
        ],
    )
    con.execute(
        """
        CREATE TEMP TABLE vector_nested AS
        WITH p AS (
          SELECT security_id,trading_date,W,
            max(dimension_active_weak) FILTER (WHERE dimension='P') AS P,
            max(dimension_active_weak) FILTER (WHERE dimension='C') AS C,
            max(dimension_active_weak) FILTER (WHERE dimension='T') AS T,
            max(dimension_active_weak) FILTER (WHERE dimension='V') AS V,
            max(validity_status) FILTER (WHERE dimension='P') AS status_P,
            max(validity_status) FILTER (WHERE dimension='C') AS status_C,
            max(validity_status) FILTER (WHERE dimension='T') AS status_T,
            max(validity_status) FILTER (WHERE dimension='V') AS status_V,
            any_value(reason_codes) FILTER (WHERE dimension='P') AS reasons_P,
            any_value(reason_codes) FILTER (WHERE dimension='C') AS reasons_C,
            any_value(reason_codes) FILTER (WHERE dimension='T') AS reasons_T,
            any_value(reason_codes) FILTER (WHERE dimension='V') AS reasons_V
          FROM vector_dimension GROUP BY security_id,trading_date,W
        ), n AS (
          SELECT *,P AS S_P,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL ELSE C END AS S_PC,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL WHEN C=false THEN false WHEN C IS NULL THEN NULL ELSE T END AS S_PCT,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL WHEN C=false THEN false WHEN C IS NULL THEN NULL WHEN T=false THEN false WHEN T IS NULL THEN NULL ELSE V END AS S_PCVT,
            CASE WHEN P IS NULL THEN status_P ELSE 'valid' END AS status_S_P,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C ELSE 'valid' END AS status_S_PC,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C WHEN C=false THEN 'valid' WHEN T IS NULL THEN status_T ELSE 'valid' END AS status_S_PCT,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C WHEN C=false THEN 'valid' WHEN T IS NULL THEN status_T WHEN T=false THEN 'valid' WHEN V IS NULL THEN status_V ELSE 'valid' END AS status_S_PCVT,
            CASE WHEN P IS NULL THEN reasons_P ELSE ['valid_no_blocker'] END AS reasons_S_P,
            CASE WHEN P IS NULL THEN reasons_P WHEN P=false THEN ['valid_no_blocker'] WHEN C IS NULL THEN reasons_C ELSE ['valid_no_blocker'] END AS reasons_S_PC,
            CASE WHEN P IS NULL THEN reasons_P WHEN P=false THEN ['valid_no_blocker'] WHEN C IS NULL THEN reasons_C WHEN C=false THEN ['valid_no_blocker'] WHEN T IS NULL THEN reasons_T ELSE ['valid_no_blocker'] END AS reasons_S_PCT,
            CASE WHEN P IS NULL THEN reasons_P WHEN P=false THEN ['valid_no_blocker'] WHEN C IS NULL THEN reasons_C WHEN C=false THEN ['valid_no_blocker'] WHEN T IS NULL THEN reasons_T WHEN T=false THEN ['valid_no_blocker'] WHEN V IS NULL THEN reasons_V ELSE ['valid_no_blocker'] END AS reasons_S_PCVT
          FROM p
        ) SELECT *,lead(trading_date) OVER (PARTITION BY security_id ORDER BY trading_date) AS next_date FROM n
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE vector_daily AS
        WITH segments AS (
          SELECT *,
            sum(CASE WHEN S_P IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_P,
            sum(CASE WHEN S_PC IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PC,
            sum(CASE WHEN S_PCT IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PCT,
            sum(CASE WHEN S_PCVT IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PCVT
          FROM vector_nested
        ), streaks AS (
          SELECT *,
            sum(CASE WHEN S_P IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_P ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_P,
            sum(CASE WHEN S_PC IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PC ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PC,
            sum(CASE WHEN S_PCT IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PCT ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PCT,
            sum(CASE WHEN S_PCVT IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PCVT ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PCVT
          FROM segments
        )
        SELECT *,
          CASE WHEN S_P IS NULL THEN NULL WHEN S_P=false THEN false ELSE streak_P>=3 END AS confirmed_P,
          CASE WHEN S_PC IS NULL THEN NULL WHEN S_PC=false THEN false ELSE streak_PC>=3 END AS confirmed_PC,
          CASE WHEN S_PCT IS NULL THEN NULL WHEN S_PCT=false THEN false ELSE streak_PCT>=3 END AS confirmed_PCT,
          CASE WHEN S_PCVT IS NULL THEN NULL WHEN S_PCVT=false THEN false ELSE streak_PCVT>=3 END AS confirmed_PCVT
        FROM streaks
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE vector_intervals AS
        WITH long AS ({_long_state_sql()}), grouped AS (
          SELECT state_name,security_id,state_group,
            min(trading_date) AS raw_start_date,
            min(trading_date) FILTER (WHERE raw_streak=3) AS confirmation_date,
            max(trading_date) AS last_true_date,arg_max(next_date,trading_date) AS next_observed_date,
            count(*)::INTEGER AS raw_duration,count(*) FILTER (WHERE raw_streak>=3)::INTEGER AS confirmed_duration
          FROM long WHERE raw_state IS TRUE GROUP BY state_name,security_id,state_group
        )
        SELECT *,next_observed_date IS NULL AS is_open_interval,
          CASE WHEN next_observed_date IS NULL THEN NULL ELSE last_true_date END AS interval_end_date
        FROM grouped WHERE confirmed_duration>0
        """
    )


def _long_state_sql() -> str:
    parts = []
    for short, state in (
        ("P", "S_P"),
        ("PC", "S_PC"),
        ("PCT", "S_PCT"),
        ("PCVT", "S_PCVT"),
    ):
        parts.append(
            f"SELECT security_id,trading_date,next_date,'{state}' AS state_name,"
            f"S_{short} AS raw_state,status_S_{short} AS validity_status,reasons_S_{short} AS reason_codes,"
            f"confirmed_{short} AS confirmed_state,grp_{short} AS state_group,streak_{short} AS raw_streak FROM vector_daily"
        )
    return " UNION ALL ".join(parts)


def _insert_vector_outputs(
    con: Any, vector: Mapping[str, Any], request_id: str
) -> None:
    params = _vector_params(vector, request_id)
    con.execute(
        f"""
        INSERT INTO dimout.{DIMENSION_TABLE}
        SELECT ?,?,?,security_id,trading_date,W,?, ?,?,?,?,dimension,q_dimension,weak_delta,
          score_dimension,score_dimension_min,eligible_dimension,dimension_active_weak,
          validity_status,reason_codes,component_indicator_ids,state_engine_version
        FROM vector_dimension ORDER BY security_id,trading_date,dimension
        """,
        [
            *params[:3],
            vector["K"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
        ],
    )
    con.execute(
        f"""
        INSERT INTO nestedout.{NESTED_TABLE}
        SELECT ?,?,?,security_id,trading_date,W,?, ?,?,?,?,0.1,
          P,C,T,V,S_P,S_PC,S_PCT,S_PCVT,status_S_P,status_S_PC,status_S_PCT,status_S_PCVT,
          reasons_S_P,reasons_S_PC,reasons_S_PCT,reasons_S_PCVT,'r0_t15_layer_q_vector_materialization.v1'
        FROM vector_nested ORDER BY security_id,trading_date
        """,
        [
            *params[:3],
            vector["K"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
        ],
    )
    con.execute(
        f"""
        INSERT INTO dailyout.{DAILY_TABLE}
        WITH long AS ({_long_state_sql()}), enriched AS (
          SELECT *,
            min(trading_date) FILTER (WHERE raw_state IS TRUE) OVER (PARTITION BY state_name,security_id,state_group) AS raw_start_date,
            min(trading_date) FILTER (WHERE raw_streak=3) OVER (PARTITION BY state_name,security_id,state_group) AS segment_confirmation_date
          FROM long
        )
        SELECT ?,?,?,security_id,trading_date,?, ?, ?,?,?,?,0.1,state_name,raw_state,
          CASE WHEN raw_state IS NULL THEN NULL WHEN raw_state=false THEN 0 ELSE raw_streak::INTEGER END,
          CASE WHEN raw_state IS TRUE THEN raw_start_date ELSE NULL END,
          confirmed_state,CASE WHEN confirmed_state IS TRUE THEN raw_start_date ELSE NULL END,
          CASE WHEN confirmed_state IS TRUE THEN segment_confirmation_date ELSE NULL END,
          validity_status,reason_codes,'r0_t15_layer_q_vector_materialization.v1'
        FROM enriched ORDER BY security_id,trading_date,state_name
        """,
        [
            *params[:3],
            vector["W"],
            vector["K"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
        ],
    )
    con.execute(
        f"""
        INSERT INTO intervalout.{INTERVAL_TABLE}
        SELECT ?,?,?,
          ?||'|'||security_id||'|'||state_name||'|'||confirmation_date,
          security_id,?, ?, ?,?,?,?,0.1,state_name,raw_start_date,confirmation_date,confirmation_date,
          interval_end_date,coalesce(next_observed_date,last_true_date),raw_duration,confirmed_duration,
          is_open_interval,CASE WHEN is_open_interval THEN 'end_of_input_open' ELSE 'raw_state_false_or_invalid' END,
          'valid',['valid_no_blocker'],'r0_t15_layer_q_vector_materialization.v1'
        FROM vector_intervals ORDER BY security_id,state_name,confirmation_date
        """,
        [
            *params[:3],
            vector["formal_vector_id"],
            vector["W"],
            vector["K"],
            vector["qP"],
            vector["qC"],
            vector["qT"],
            vector["qV"],
        ],
    )


def _vector_params(vector: Mapping[str, Any], request_id: str) -> list[Any]:
    return [vector["formal_vector_id"], vector["candidate_q_vector_id"], request_id]


def _baseline_reconciliation(
    con: Any, vector: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    long_sql = _long_state_sql()
    for state in ("S_PCT", "S_PCVT"):
        current = con.execute(
            f"""
            WITH long AS ({long_sql}) SELECT
              count(*) FILTER (WHERE raw_state IS TRUE),count(*) FILTER (WHERE confirmed_state IS TRUE),
              count(*) FILTER (WHERE validity_status='valid'),count(*) FILTER (WHERE validity_status='unknown'),
              count(*) FILTER (WHERE validity_status='blocked') FROM long WHERE state_name=?
            """,
            [state],
        ).fetchone()
        upstream = con.execute(
            """
            SELECT count(*) FILTER (WHERE raw_state IS TRUE),count(*) FILTER (WHERE confirmed_state IS TRUE),
              count(*) FILTER (WHERE validity_status='valid'),count(*) FILTER (WHERE validity_status='unknown'),
              count(*) FILTER (WHERE validity_status='blocked')
            FROM dailydb.r0_t07_daily_confirmation_results
            WHERE percentile_window_W=? AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name=?
            """,
            [vector["W"], state],
        ).fetchone()
        current_interval = con.execute(
            """SELECT count(*),coalesce(sum(confirmed_duration),0),count(*) FILTER (WHERE is_open_interval) FROM vector_intervals WHERE state_name=?""",
            [state],
        ).fetchone()
        upstream_interval = con.execute(
            """
            SELECT count(*),coalesce(sum(confirmed_duration_observations),0),count(*) FILTER (WHERE is_open_interval)
            FROM intervaldb.r0_t07_confirmed_interval_results
            WHERE percentile_window_W=? AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name=?
            """,
            [vector["W"], state],
        ).fetchone()
        pairs = [
            ("raw_state_days", current[0], upstream[0]),
            ("confirmed_state_days", current[1], upstream[1]),
            ("valid_rows", current[2], upstream[2]),
            ("unknown_rows", current[3], upstream[3]),
            ("blocked_rows", current[4], upstream[4]),
            ("confirmed_intervals", current_interval[0], upstream_interval[0]),
            ("confirmed_duration", current_interval[1], upstream_interval[1]),
            ("open_intervals", current_interval[2], upstream_interval[2]),
        ]
        output.extend(
            {
                "formal_vector_id": vector["formal_vector_id"],
                "candidate_q_vector_id": vector["candidate_q_vector_id"],
                "W": vector["W"],
                "state_name": state,
                "metric": metric,
                "materialized_value": actual,
                "upstream_value": expected,
                "mismatch_count": abs(int(actual) - int(expected)),
                "status": "passed" if int(actual) == int(expected) else "failed",
            }
            for metric, actual, expected in pairs
        )
    return output


def _vector_stats(con: Any, vector: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _query_dicts(
        con,
        f"""
        WITH long AS ({_long_state_sql()})
        SELECT state_name,count(*)::BIGINT AS total_rows,
          count(*) FILTER (WHERE validity_status='valid')::BIGINT AS valid_rows,
          count(*) FILTER (WHERE validity_status='unknown')::BIGINT AS unknown_rows,
          count(*) FILTER (WHERE validity_status='blocked')::BIGINT AS blocked_rows,
          count(*) FILTER (WHERE raw_state IS TRUE)::BIGINT AS raw_true,
          count(*) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS confirmed_true,
          count(*) FILTER (WHERE raw_state IS NULL AND validity_status='valid')::BIGINT AS null_marked_valid
        FROM long
        GROUP BY state_name
        """,
    )
    # The child invariant is checked directly below because the long form does not retain S_PCT.
    child = con.execute(
        """
        SELECT count(*) FILTER (WHERE S_PCVT IS TRUE AND S_PCT IS NOT TRUE),
          count(*) FILTER (WHERE confirmed_PCVT IS TRUE AND confirmed_PCT IS NOT TRUE)
        FROM vector_daily
        """
    ).fetchone()
    durations = {
        row[0]: (int(row[1]), int(row[2]))
        for row in con.execute(
            """SELECT state_name,count(*),sum(confirmed_duration) FROM vector_intervals GROUP BY state_name"""
        ).fetchall()
    }
    for row in rows:
        interval_count, duration = durations.get(row["state_name"], (0, 0))
        row.update(
            {
                "formal_vector_id": vector["formal_vector_id"],
                "candidate_q_vector_id": vector["candidate_q_vector_id"],
                "W": vector["W"],
                "qP": vector["qP"],
                "qC": vector["qC"],
                "qT": vector["qT"],
                "qV": vector["qV"],
                "interval_count": interval_count,
                "interval_confirmed_duration": duration,
                "child_raw_violation": int(child[0]),
                "child_confirmed_violation": int(child[1]),
            }
        )
    return rows


def _table_summaries(con: Any) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for key, qualified in (
        ("dimension_state", f"dimout.{DIMENSION_TABLE}"),
        ("nested_daily_state", f"nestedout.{NESTED_TABLE}"),
        ("daily_confirmation", f"dailyout.{DAILY_TABLE}"),
        ("confirmed_interval", f"intervalout.{INTERVAL_TABLE}"),
    ):
        row_count, vectors, securities, date_min, date_max = con.execute(
            f"""SELECT count(*),count(DISTINCT formal_vector_id),count(DISTINCT security_id),min(trading_date),max(trading_date) FROM {qualified}"""
            if key != "confirmed_interval"
            else f"""SELECT count(*),count(DISTINCT formal_vector_id),count(DISTINCT security_id),min(confirmation_date),max(coalesce(interval_end_date,last_observed_date)) FROM {qualified}"""
        ).fetchone()
        output[key] = {
            "table": qualified.split(".", 1)[1],
            "row_count": int(row_count),
            "vector_count": int(vectors),
            "security_count": int(securities),
            "date_min": date_min,
            "date_max": date_max,
        }
    return output


def _integrity_checks(
    con: Any,
    registry: Sequence[Mapping[str, Any]],
    summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    duplicates = {
        "dimension_state": con.execute(
            f"SELECT count(*)-count(DISTINCT (formal_vector_id,security_id,trading_date,dimension)) FROM dimout.{DIMENSION_TABLE}"
        ).fetchone()[0],
        "nested_daily_state": con.execute(
            f"SELECT count(*)-count(DISTINCT (formal_vector_id,security_id,trading_date)) FROM nestedout.{NESTED_TABLE}"
        ).fetchone()[0],
        "daily_confirmation": con.execute(
            f"SELECT count(*)-count(DISTINCT (formal_vector_id,security_id,trading_date,state_name)) FROM dailyout.{DAILY_TABLE}"
        ).fetchone()[0],
        "confirmed_interval": con.execute(
            f"SELECT count(*)-count(DISTINCT interval_id) FROM intervalout.{INTERVAL_TABLE}"
        ).fetchone()[0],
    }
    expected_vectors = sum(row["materialize"] for row in registry)
    schema_ok = all(
        summary["vector_count"] == expected_vectors for summary in summaries.values()
    )
    return {
        "schema_status": "passed" if schema_ok else "failed",
        "primary_key_status": "passed"
        if all(int(value) == 0 for value in duplicates.values())
        else "failed",
        "duplicate_counts": {key: int(value) for key, value in duplicates.items()},
    }


def build_anomaly_scan(
    registry: Sequence[Mapping[str, Any]],
    reconciliation: Sequence[Mapping[str, Any]],
    stats: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
) -> dict[str, Any]:
    nonbaseline = [row for row in registry if row["materialize"]]
    stats_index = {
        (row["candidate_q_vector_id"], row["state_name"]): row for row in stats
    }
    monotonic_pairs = []
    for window in (120, 250):
        for layer, state in (("T", "S_PCT"), ("V", "S_PCVT")):
            low = next(
                row
                for row in nonbaseline
                if row["W"] == window
                and abs(row[f"q{layer}"] - (0.25 if layer == "V" else 0.25)) < EPSILON
            )
            high_q = 0.3
            high = next(
                row
                for row in nonbaseline
                if row["W"] == window and abs(row[f"q{layer}"] - high_q) < EPSILON
            )
            monotonic_pairs.append(
                int(stats_index[(low["candidate_q_vector_id"], state)]["raw_true"])
                <= int(stats_index[(high["candidate_q_vector_id"], state)]["raw_true"])
            )
    checks = {
        "registry_exact_count": len(registry) == 10 and len(nonbaseline) == 8,
        "baseline_reconciliation_mismatch_zero": sum(
            int(row["mismatch_count"]) for row in reconciliation
        )
        == 0,
        "no_all_null": all(int(row["valid_rows"]) > 0 for row in stats),
        "no_all_zero": all(int(row["raw_true"]) > 0 for row in stats),
        "no_all_one": all(
            int(row["raw_true"]) < int(row["valid_rows"]) for row in stats
        ),
        "unknown_not_marked_valid": all(
            int(row["null_marked_valid"]) == 0 for row in stats
        ),
        "parent_child_invariant": all(
            int(row["child_raw_violation"]) == 0
            and int(row["child_confirmed_violation"]) == 0
            for row in stats
        ),
        "confirmation_interval_conservation": all(
            int(row["confirmed_true"]) == int(row["interval_confirmed_duration"])
            for row in stats
        ),
        "q_monotonic_response": all(monotonic_pairs),
        "schema_status": integrity["schema_status"] == "passed",
        "primary_key_status": integrity["primary_key_status"] == "passed",
    }
    findings = [name for name, passed in checks.items() if not passed]
    return {
        "task_id": TASK_ID,
        "checks": checks,
        "blocking_findings": findings,
        "unresolved_questions": [],
        "anomaly_resolution_status": "passed" if not findings else "failed",
        "status": "passed" if not findings else "failed",
        "vector_state_stats": list(stats),
        "integrity": dict(integrity),
    }


def _output_records(
    paths: Mapping[str, Path], summaries: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    return {
        key: {
            **dict(summaries[key]),
            "path": _rel(path),
            "sha256": sha256_file(path),
            "committed_to_repo": False,
        }
        for key, path in paths.items()
    }


def build_artifact_manifest(
    *,
    run_id: str,
    code_commit: str,
    config: Mapping[str, Any],
    binding: Mapping[str, Any],
    registry: Sequence[Mapping[str, Any]],
    outputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "r0_t15_artifact_manifest.v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "config_path": _rel(CONFIG_PATH),
        "config_sha256": sha256_file(CONFIG_PATH),
        "request_binding": dict(binding),
        "registry_sha256": hashlib.sha256(
            json.dumps(
                list(registry),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "baseline_reuse": True,
        "materialized_vector_count": sum(row["materialize"] for row in registry),
        "outputs": dict(outputs),
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def _drop_vector_tables(con: Any) -> None:
    for table in (
        "vector_intervals",
        "vector_daily",
        "vector_nested",
        "vector_dimension",
    ):
        con.execute(f"DROP TABLE {table}")


def _query_dicts(
    con: Any, sql: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    cursor = con.execute(sql, params or [])
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict | list | tuple):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise R0T15Error(f"json_object_required:{path}")
    return value


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _rel(path: str | Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
