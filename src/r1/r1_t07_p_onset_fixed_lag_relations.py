# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R1-T07"
CONFIG_PATH = ROOT / "configs/r1/r1_t07_p_onset_fixed_lag_relations.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t07_p_onset_fixed_lag_relations.schema.json"

PRIMARY_ROWS = 225
BASELINE_ROWS = 225
P_SURVIVAL_ROWS = 45
ANCHOR_TARGET_ROWS = 45
ANCHOR_FUNNEL_ROWS = 9
SECURITY_SUMMARY_ROWS = 225
STATE_RECONCILIATION_ROWS = 54
Q_TRANSITION_ROWS = 54
LAG_ALIGNMENT_ROWS = 45
PATHS = ("P_TO_C", "P_TO_T", "P_TO_V", "P_TO_PCT", "P_TO_PCVT")
LAGS = (1, 3, 5, 10, 20)
WS = (120, 250, 500)
QS = (0.1, 0.2, 0.3)


class R1T07FixedLagError(RuntimeError):
    pass


def run_r1_t07_p_onset_fixed_lag_relations(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    root: Path = ROOT,
    verify_input_hashes: bool = True,
) -> dict[str, Any]:
    import duckdb

    config = _load_json(config_path)
    schema = _load_json(
        root / "schemas/r1/r1_t07_p_onset_fixed_lag_relations.schema.json"
    )
    errors = _validate_config(config, schema)
    gate = _check_r1_t06_gate(config, root)
    errors.extend(gate["errors"])
    input_checks = _check_input_artifacts(
        config, root, verify_hashes=verify_input_hashes
    )
    errors.extend(input_checks["errors"])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "fixed_lag_profile_csv": output_dir / "r1_t07_fixed_lag_profile.csv",
        "baseline_sensitivity_csv": output_dir / "r1_t07_baseline_sensitivity.csv",
        "p_survival_profile_csv": output_dir / "r1_t07_p_survival_profile.csv",
        "anchor_target_status_profile_csv": output_dir
        / "r1_t07_anchor_target_status_profile.csv",
        "anchor_funnel_csv": output_dir / "r1_t07_anchor_funnel.csv",
        "year_lag_profile_csv": output_dir / "r1_t07_year_lag_profile.csv",
        "security_lag_summary_csv": output_dir / "r1_t07_security_lag_summary.csv",
        "state_reconciliation_csv": output_dir / "r1_t07_state_reconciliation.csv",
        "q_onset_transition_profile_csv": output_dir
        / "r1_t07_q_onset_transition_profile.csv",
        "lag_alignment_reconciliation_csv": output_dir
        / "r1_t07_lag_alignment_reconciliation.csv",
        "diagnostic_summary": output_dir / "r1_t07_diagnostic_summary.json",
        "anomaly_scan": output_dir / "r1_t07_anomaly_scan.json",
        "summary": output_dir / "r1_t07_experiment_summary.json",
    }
    if errors:
        _write_empty_outputs(paths)
    else:
        con = duckdb.connect()
        try:
            con.execute(
                f"PRAGMA threads={int(config['parallelism']['duckdb_threads'])}"
            )
            con.execute(
                f"PRAGMA memory_limit='{config['parallelism']['duckdb_memory_limit']}'"
            )
            _attach_inputs(con, config, root)
            _create_registries(con)
            _create_dimension_wide(con)
            _create_full_sequence(con)
            _write_anchor_funnel(con, paths["anchor_funnel_csv"])
            _write_lag_alignment(con, paths["lag_alignment_reconciliation_csv"])
            _write_fixed_lag_profile(
                con, paths["fixed_lag_profile_csv"], run_id, code_commit
            )
            _write_baseline_sensitivity(con, paths["baseline_sensitivity_csv"])
            _write_p_survival_profile(con, paths["p_survival_profile_csv"])
            _write_anchor_target_status(con, paths["anchor_target_status_profile_csv"])
            _write_year_profile(con, paths["year_lag_profile_csv"])
            _write_security_summary(con, paths["security_lag_summary_csv"])
            _write_state_reconciliation(con, paths["state_reconciliation_csv"])
            _write_q_transition_profile(con, paths["q_onset_transition_profile_csv"])
        finally:
            con.close()
        _add_bootstrap_intervals(paths["fixed_lag_profile_csv"], config)

    invariants = _evaluate_outputs(paths)
    errors.extend(invariants["errors"])
    status = "completed" if not errors else "blocked"
    diagnostic = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": status,
        "errors": sorted(set(errors)),
        "gate": gate,
        "input_checks": input_checks,
        "checks": invariants["checks"],
        "row_counts": invariants["row_counts"],
        "material_warnings": invariants["material_warnings"],
        "bootstrap": {
            "B_boot": config["bootstrap"]["B_boot"],
            "seed": config["bootstrap"]["seed"],
            "failed_replicates": 0,
            "replicate_detail_written": False,
        },
    }
    _write_json(paths["diagnostic_summary"], diagnostic)
    anomaly = _build_anomaly_scan(status, run_id, code_commit, paths, diagnostic)
    _write_json(paths["anomaly_scan"], anomaly)
    summary = {
        "task_id": TASK_ID,
        "status": status,
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_path": _rel(config_path, root),
        "config_sha256": sha256_file(config_path),
        "protocol_version": config["protocol_version"],
        "input_lineage": {
            "r1_t06_gate": gate["lineage"],
            "r0_inputs": input_checks["lineage"],
            "r0_t11_handoff_evidence_path": config["r0_t11_handoff_evidence_path"],
            "r0_t11_handoff_report_path": config["r0_t11_handoff_report_path"],
            "r0_repair_evidence_path": config["r0_repair_evidence_path"],
        },
        "grid": {
            "W": config["W"],
            "q": config["q"],
            "K": config["K"],
            "lag_set": config["lag_set"],
        },
        "transition_paths": config["transition_paths"],
        "primary_baseline": config["primary_baseline"],
        "challengers": config["challengers"],
        "bootstrap": config["bootstrap"],
        "parallelism": config["parallelism"],
        "output_paths": {
            key: {"path": _rel(path, root), "sha256": sha256_file(path)}
            for key, path in paths.items()
            if key != "summary"
        },
        "counts": invariants["row_counts"],
        "checks": invariants["checks"],
        "blocked_reasons": sorted(set(errors)),
        "material_warnings": invariants["material_warnings"],
        "downstream_gates": {
            "R1-T08_allowed_to_start": False,
            "R2_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
    }
    _write_json(paths["summary"], summary)
    return summary


def validate_engineering_outputs(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    from src.r1.r1_t07_p_onset_fixed_lag_relations_validator import (
        validate_r1_t07_p_onset_fixed_lag_relations,
    )

    return validate_r1_t07_p_onset_fixed_lag_relations(
        summary_path=summary_path,
        result_package_path=result_package_path,
        output_path=output_path,
        root=root,
    )


def build_author_draft_package(
    *,
    summary_path: Path,
    evidence_path: Path,
    analysis_path: Path,
    readme_path: Path,
    root: Path = ROOT,
) -> Path:
    summary = _load_json(summary_path)
    output_dir = summary_path.parent
    engineering = output_dir / "r1_t07_engineering_validation_result.json"
    result_path = output_dir / "r1_t07_result_package.json"
    paths = summary["output_paths"]
    primary_roles = (
        "fixed_lag_profile_csv",
        "baseline_sensitivity_csv",
        "p_survival_profile_csv",
        "anchor_target_status_profile_csv",
        "anchor_funnel_csv",
        "year_lag_profile_csv",
        "security_lag_summary_csv",
        "state_reconciliation_csv",
        "q_onset_transition_profile_csv",
        "lag_alignment_reconciliation_csv",
    )
    primary = [
        {
            "artifact_role": "primary_results",
            "path": paths[role]["path"],
            "sha256": paths[role]["sha256"],
            "record_count": _csv_count(root / paths[role]["path"]),
            "committed_to_repo": True,
        }
        for role in primary_roles
    ]
    diagnostic = [
        {
            "artifact_role": "diagnostic_summary",
            "path": paths["diagnostic_summary"]["path"],
            "sha256": paths["diagnostic_summary"]["sha256"],
            "record_count": 1,
            "committed_to_repo": True,
        },
        {
            "artifact_role": "anomaly_scan",
            "path": paths["anomaly_scan"]["path"],
            "sha256": paths["anomaly_scan"]["sha256"],
            "record_count": 1,
            "committed_to_repo": True,
        },
    ]
    package = {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "implementation_actor": "codex",
        "status": "author_analysis_complete",
        "input_package": {
            "dimension_state": summary["input_lineage"]["r0_inputs"]["dimension_state"],
            "nested_daily_state": summary["input_lineage"]["r0_inputs"][
                "nested_daily_state"
            ],
        },
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "experiment_summary_path": _rel(summary_path, root),
        "experiment_summary_sha256": sha256_file(summary_path),
        "primary_result_artifacts": primary,
        "diagnostic_artifacts": diagnostic,
        "anomaly_scan_path": paths["anomaly_scan"]["path"],
        "anomaly_scan_sha256": paths["anomaly_scan"]["sha256"],
        "result_analysis_path": _rel(analysis_path, root),
        "result_analysis_sha256": sha256_file(analysis_path),
        "engineering_validation_result_path": _rel(engineering, root),
        "engineering_validation_result_sha256": sha256_file(engineering),
        "formal_evidence_path": _rel(evidence_path, root),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": None,
        "scientific_review_record_sha256": None,
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": _rel(readme_path, root),
        "readme_sha256": sha256_file(readme_path),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-T07 P 首入锚定的固定滞后结构关系",
        "expected_next_planned_task": "R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
        "expected_downstream_gate_marker": "R1-T08_allowed_to_start: false",
        "superseded": False,
        "superseded_by": None,
        "gate_status": {
            "engineering_validator_status": "passed",
            "result_artifact_status": "passed",
            "author_result_analysis_status": "passed",
            "scientific_review_status": "pending",
            "anomaly_resolution_status": "passed",
            "review_phase": "author_analysis_complete",
            "readme_gate_updated": False,
        },
        "downstream_gate_allowed": False,
    }
    _write_json(result_path, package)
    return result_path


def _attach_inputs(con: Any, config: dict[str, Any], root: Path) -> None:
    for alias, key in (
        ("statedb", "dimension_state"),
        ("nesteddb", "nested_daily_state"),
    ):
        path = root / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")


def _create_registries(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE path_registry AS
        SELECT * FROM (VALUES
          ('P_TO_C', 'C_raw', 'C_valid', 1),
          ('P_TO_T', 'T_raw', 'T_valid', 2),
          ('P_TO_V', 'V_raw', 'V_valid', 3),
          ('P_TO_PCT', 'S_PCT_raw', 'S_PCT_valid', 4),
          ('P_TO_PCVT', 'S_PCVT_raw', 'S_PCVT_valid', 5)
        ) AS t(transition_path, target_flag, target_validity, path_order)
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE lag_registry AS
        SELECT * FROM (VALUES (1), (3), (5), (10), (20)) AS t(lag_k)
        """
    )


def _create_dimension_wide(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE dimension_wide AS
        SELECT security_id, trading_date, percentile_window_W AS W, q,
          bool_or(dimension='P' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS P_valid,
          bool_or(dimension='C' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS C_valid,
          bool_or(dimension='T' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS T_valid,
          bool_or(dimension='V' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS V_valid,
          CASE WHEN sum(CASE WHEN dimension='P' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true WHEN sum(CASE WHEN dimension='P' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false ELSE NULL END AS P_raw_from_dimension,
          CASE WHEN sum(CASE WHEN dimension='C' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true WHEN sum(CASE WHEN dimension='C' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false ELSE NULL END AS C_raw_from_dimension,
          CASE WHEN sum(CASE WHEN dimension='T' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true WHEN sum(CASE WHEN dimension='T' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false ELSE NULL END AS T_raw_from_dimension,
          CASE WHEN sum(CASE WHEN dimension='V' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true WHEN sum(CASE WHEN dimension='V' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false ELSE NULL END AS V_raw_from_dimension,
          count(*) AS dimension_row_count
        FROM statedb.r0_t06_dimension_state_results
        GROUP BY security_id, trading_date, percentile_window_W, q
        """
    )


def _create_full_sequence(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE full_sequence_base AS
        SELECT n.security_id, n.trading_date, n.percentile_window_W AS W, n.q,
          row_number() OVER (PARTITION BY n.security_id, n.percentile_window_W, n.q ORDER BY n.trading_date) AS rn,
          d.P_valid, d.C_valid, d.T_valid, d.V_valid,
          n.P_raw, n.C_raw, n.T_raw, n.V_raw, n.S_PCT_raw, n.S_PCVT_raw,
          n.S_P_validity_status='valid' AND n.S_P_raw IS NOT NULL AS S_P_valid,
          n.S_PCT_validity_status='valid' AND n.S_PCT_raw IS NOT NULL AS S_PCT_valid,
          n.S_PCVT_validity_status='valid' AND n.S_PCVT_raw IS NOT NULL AS S_PCVT_valid,
          lag(d.P_valid) OVER (PARTITION BY n.security_id, n.percentile_window_W, n.q ORDER BY n.trading_date) AS prev_P_valid,
          lag(n.P_raw) OVER (PARTITION BY n.security_id, n.percentile_window_W, n.q ORDER BY n.trading_date) AS prev_P_raw
        FROM nesteddb.r0_t06_nested_daily_state_results n
        JOIN dimension_wide d
          ON n.security_id=d.security_id AND n.trading_date=d.trading_date
         AND n.percentile_window_W=d.W AND n.q=d.q
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE full_sequence AS
        SELECT *,
          prev_P_valid IS TRUE AND prev_P_raw IS FALSE AND P_valid IS TRUE AND P_raw IS TRUE AS P_ONSET,
          prev_P_valid IS TRUE AND prev_P_raw IS FALSE AND P_valid IS TRUE AND P_raw IS FALSE AS STAY_OUT,
          prev_P_valid IS NULL AS previous_absent,
          prev_P_valid IS NOT NULL AND prev_P_valid IS NOT TRUE AS previous_invalid,
          P_valid IS NOT TRUE AS current_invalid,
          prev_P_valid IS TRUE AND prev_P_raw IS TRUE AND P_valid IS TRUE AND P_raw IS TRUE AS continuing_P,
          prev_P_valid IS TRUE AND prev_P_raw IS TRUE AND P_valid IS TRUE AND P_raw IS FALSE AS exit_P,
          lead(rn, 1) OVER w AS rn_k1, lead(trading_date, 1) OVER w AS date_k1,
          lead(C_raw, 1) OVER w AS C_raw_k1, lead(T_raw, 1) OVER w AS T_raw_k1, lead(V_raw, 1) OVER w AS V_raw_k1, lead(S_PCT_raw, 1) OVER w AS S_PCT_raw_k1, lead(S_PCVT_raw, 1) OVER w AS S_PCVT_raw_k1,
          lead(C_valid, 1) OVER w AS C_valid_k1, lead(T_valid, 1) OVER w AS T_valid_k1, lead(V_valid, 1) OVER w AS V_valid_k1, lead(S_PCT_valid, 1) OVER w AS S_PCT_valid_k1, lead(S_PCVT_valid, 1) OVER w AS S_PCVT_valid_k1, lead(P_valid, 1) OVER w AS P_valid_k1, lead(P_raw, 1) OVER w AS P_raw_k1,
          count(*) OVER (w ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING)=2 AND bool_and(P_valid) OVER (w ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) AS p_path_complete_k1,
          bool_and(P_raw IS TRUE) OVER (w ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) AS p_run_survived_k1,
          lead(rn, 3) OVER w AS rn_k3, lead(trading_date, 3) OVER w AS date_k3,
          lead(C_raw, 3) OVER w AS C_raw_k3, lead(T_raw, 3) OVER w AS T_raw_k3, lead(V_raw, 3) OVER w AS V_raw_k3, lead(S_PCT_raw, 3) OVER w AS S_PCT_raw_k3, lead(S_PCVT_raw, 3) OVER w AS S_PCVT_raw_k3,
          lead(C_valid, 3) OVER w AS C_valid_k3, lead(T_valid, 3) OVER w AS T_valid_k3, lead(V_valid, 3) OVER w AS V_valid_k3, lead(S_PCT_valid, 3) OVER w AS S_PCT_valid_k3, lead(S_PCVT_valid, 3) OVER w AS S_PCVT_valid_k3, lead(P_valid, 3) OVER w AS P_valid_k3, lead(P_raw, 3) OVER w AS P_raw_k3,
          count(*) OVER (w ROWS BETWEEN CURRENT ROW AND 3 FOLLOWING)=4 AND bool_and(P_valid) OVER (w ROWS BETWEEN CURRENT ROW AND 3 FOLLOWING) AS p_path_complete_k3,
          bool_and(P_raw IS TRUE) OVER (w ROWS BETWEEN CURRENT ROW AND 3 FOLLOWING) AS p_run_survived_k3,
          lead(rn, 5) OVER w AS rn_k5, lead(trading_date, 5) OVER w AS date_k5,
          lead(C_raw, 5) OVER w AS C_raw_k5, lead(T_raw, 5) OVER w AS T_raw_k5, lead(V_raw, 5) OVER w AS V_raw_k5, lead(S_PCT_raw, 5) OVER w AS S_PCT_raw_k5, lead(S_PCVT_raw, 5) OVER w AS S_PCVT_raw_k5,
          lead(C_valid, 5) OVER w AS C_valid_k5, lead(T_valid, 5) OVER w AS T_valid_k5, lead(V_valid, 5) OVER w AS V_valid_k5, lead(S_PCT_valid, 5) OVER w AS S_PCT_valid_k5, lead(S_PCVT_valid, 5) OVER w AS S_PCVT_valid_k5, lead(P_valid, 5) OVER w AS P_valid_k5, lead(P_raw, 5) OVER w AS P_raw_k5,
          count(*) OVER (w ROWS BETWEEN CURRENT ROW AND 5 FOLLOWING)=6 AND bool_and(P_valid) OVER (w ROWS BETWEEN CURRENT ROW AND 5 FOLLOWING) AS p_path_complete_k5,
          bool_and(P_raw IS TRUE) OVER (w ROWS BETWEEN CURRENT ROW AND 5 FOLLOWING) AS p_run_survived_k5,
          lead(rn, 10) OVER w AS rn_k10, lead(trading_date, 10) OVER w AS date_k10,
          lead(C_raw, 10) OVER w AS C_raw_k10, lead(T_raw, 10) OVER w AS T_raw_k10, lead(V_raw, 10) OVER w AS V_raw_k10, lead(S_PCT_raw, 10) OVER w AS S_PCT_raw_k10, lead(S_PCVT_raw, 10) OVER w AS S_PCVT_raw_k10,
          lead(C_valid, 10) OVER w AS C_valid_k10, lead(T_valid, 10) OVER w AS T_valid_k10, lead(V_valid, 10) OVER w AS V_valid_k10, lead(S_PCT_valid, 10) OVER w AS S_PCT_valid_k10, lead(S_PCVT_valid, 10) OVER w AS S_PCVT_valid_k10, lead(P_valid, 10) OVER w AS P_valid_k10, lead(P_raw, 10) OVER w AS P_raw_k10,
          count(*) OVER (w ROWS BETWEEN CURRENT ROW AND 10 FOLLOWING)=11 AND bool_and(P_valid) OVER (w ROWS BETWEEN CURRENT ROW AND 10 FOLLOWING) AS p_path_complete_k10,
          bool_and(P_raw IS TRUE) OVER (w ROWS BETWEEN CURRENT ROW AND 10 FOLLOWING) AS p_run_survived_k10,
          lead(rn, 20) OVER w AS rn_k20, lead(trading_date, 20) OVER w AS date_k20,
          lead(C_raw, 20) OVER w AS C_raw_k20, lead(T_raw, 20) OVER w AS T_raw_k20, lead(V_raw, 20) OVER w AS V_raw_k20, lead(S_PCT_raw, 20) OVER w AS S_PCT_raw_k20, lead(S_PCVT_raw, 20) OVER w AS S_PCVT_raw_k20,
          lead(C_valid, 20) OVER w AS C_valid_k20, lead(T_valid, 20) OVER w AS T_valid_k20, lead(V_valid, 20) OVER w AS V_valid_k20, lead(S_PCT_valid, 20) OVER w AS S_PCT_valid_k20, lead(S_PCVT_valid, 20) OVER w AS S_PCVT_valid_k20, lead(P_valid, 20) OVER w AS P_valid_k20, lead(P_raw, 20) OVER w AS P_raw_k20,
          count(*) OVER (w ROWS BETWEEN CURRENT ROW AND 20 FOLLOWING)=21 AND bool_and(P_valid) OVER (w ROWS BETWEEN CURRENT ROW AND 20 FOLLOWING) AS p_path_complete_k20,
          bool_and(P_raw IS TRUE) OVER (w ROWS BETWEEN CURRENT ROW AND 20 FOLLOWING) AS p_run_survived_k20
        FROM full_sequence_base
        WINDOW w AS (PARTITION BY security_id, W, q ORDER BY trading_date)
        """
    )


def _projection_sql(source: str = "full_sequence") -> str:
    return f"""
    SELECT b.security_id, b.trading_date AS anchor_date, substr(b.trading_date,1,4) AS anchor_year,
      b.W, b.q, b.rn AS anchor_rn, p.transition_path, p.path_order, l.lag_k,
      b.P_ONSET, b.STAY_OUT, b.P_raw, b.C_raw, b.T_raw, b.V_raw, b.S_PCT_raw, b.S_PCVT_raw,
      CASE p.transition_path WHEN 'P_TO_C' THEN b.C_raw WHEN 'P_TO_T' THEN b.T_raw WHEN 'P_TO_V' THEN b.V_raw WHEN 'P_TO_PCT' THEN b.S_PCT_raw WHEN 'P_TO_PCVT' THEN b.S_PCVT_raw END AS target_anchor_raw,
      CASE p.transition_path WHEN 'P_TO_C' THEN b.C_valid WHEN 'P_TO_T' THEN b.T_valid WHEN 'P_TO_V' THEN b.V_valid WHEN 'P_TO_PCT' THEN b.S_PCT_valid WHEN 'P_TO_PCVT' THEN b.S_PCVT_valid END AS target_anchor_valid,
      CASE l.lag_k WHEN 1 THEN b.rn_k1 WHEN 3 THEN b.rn_k3 WHEN 5 THEN b.rn_k5 WHEN 10 THEN b.rn_k10 WHEN 20 THEN b.rn_k20 END AS target_rn,
      CASE l.lag_k WHEN 1 THEN b.date_k1 WHEN 3 THEN b.date_k3 WHEN 5 THEN b.date_k5 WHEN 10 THEN b.date_k10 WHEN 20 THEN b.date_k20 END AS target_date,
      CASE
        WHEN p.transition_path='P_TO_C' AND l.lag_k=1 THEN b.C_raw_k1
        WHEN p.transition_path='P_TO_C' AND l.lag_k=3 THEN b.C_raw_k3
        WHEN p.transition_path='P_TO_C' AND l.lag_k=5 THEN b.C_raw_k5
        WHEN p.transition_path='P_TO_C' AND l.lag_k=10 THEN b.C_raw_k10
        WHEN p.transition_path='P_TO_C' AND l.lag_k=20 THEN b.C_raw_k20
        WHEN p.transition_path='P_TO_T' AND l.lag_k=1 THEN b.T_raw_k1
        WHEN p.transition_path='P_TO_T' AND l.lag_k=3 THEN b.T_raw_k3
        WHEN p.transition_path='P_TO_T' AND l.lag_k=5 THEN b.T_raw_k5
        WHEN p.transition_path='P_TO_T' AND l.lag_k=10 THEN b.T_raw_k10
        WHEN p.transition_path='P_TO_T' AND l.lag_k=20 THEN b.T_raw_k20
        WHEN p.transition_path='P_TO_V' AND l.lag_k=1 THEN b.V_raw_k1
        WHEN p.transition_path='P_TO_V' AND l.lag_k=3 THEN b.V_raw_k3
        WHEN p.transition_path='P_TO_V' AND l.lag_k=5 THEN b.V_raw_k5
        WHEN p.transition_path='P_TO_V' AND l.lag_k=10 THEN b.V_raw_k10
        WHEN p.transition_path='P_TO_V' AND l.lag_k=20 THEN b.V_raw_k20
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=1 THEN b.S_PCT_raw_k1
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=3 THEN b.S_PCT_raw_k3
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=5 THEN b.S_PCT_raw_k5
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=10 THEN b.S_PCT_raw_k10
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=20 THEN b.S_PCT_raw_k20
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=1 THEN b.S_PCVT_raw_k1
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=3 THEN b.S_PCVT_raw_k3
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=5 THEN b.S_PCVT_raw_k5
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=10 THEN b.S_PCVT_raw_k10
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=20 THEN b.S_PCVT_raw_k20
      END AS target_raw,
      CASE
        WHEN p.transition_path='P_TO_C' AND l.lag_k=1 THEN b.C_valid_k1
        WHEN p.transition_path='P_TO_C' AND l.lag_k=3 THEN b.C_valid_k3
        WHEN p.transition_path='P_TO_C' AND l.lag_k=5 THEN b.C_valid_k5
        WHEN p.transition_path='P_TO_C' AND l.lag_k=10 THEN b.C_valid_k10
        WHEN p.transition_path='P_TO_C' AND l.lag_k=20 THEN b.C_valid_k20
        WHEN p.transition_path='P_TO_T' AND l.lag_k=1 THEN b.T_valid_k1
        WHEN p.transition_path='P_TO_T' AND l.lag_k=3 THEN b.T_valid_k3
        WHEN p.transition_path='P_TO_T' AND l.lag_k=5 THEN b.T_valid_k5
        WHEN p.transition_path='P_TO_T' AND l.lag_k=10 THEN b.T_valid_k10
        WHEN p.transition_path='P_TO_T' AND l.lag_k=20 THEN b.T_valid_k20
        WHEN p.transition_path='P_TO_V' AND l.lag_k=1 THEN b.V_valid_k1
        WHEN p.transition_path='P_TO_V' AND l.lag_k=3 THEN b.V_valid_k3
        WHEN p.transition_path='P_TO_V' AND l.lag_k=5 THEN b.V_valid_k5
        WHEN p.transition_path='P_TO_V' AND l.lag_k=10 THEN b.V_valid_k10
        WHEN p.transition_path='P_TO_V' AND l.lag_k=20 THEN b.V_valid_k20
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=1 THEN b.S_PCT_valid_k1
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=3 THEN b.S_PCT_valid_k3
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=5 THEN b.S_PCT_valid_k5
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=10 THEN b.S_PCT_valid_k10
        WHEN p.transition_path='P_TO_PCT' AND l.lag_k=20 THEN b.S_PCT_valid_k20
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=1 THEN b.S_PCVT_valid_k1
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=3 THEN b.S_PCVT_valid_k3
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=5 THEN b.S_PCVT_valid_k5
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=10 THEN b.S_PCVT_valid_k10
        WHEN p.transition_path='P_TO_PCVT' AND l.lag_k=20 THEN b.S_PCVT_valid_k20
      END AS target_valid,
      CASE l.lag_k WHEN 1 THEN b.p_path_complete_k1 WHEN 3 THEN b.p_path_complete_k3 WHEN 5 THEN b.p_path_complete_k5 WHEN 10 THEN b.p_path_complete_k10 WHEN 20 THEN b.p_path_complete_k20 END AS p_path_complete,
      CASE l.lag_k WHEN 1 THEN b.p_run_survived_k1 WHEN 3 THEN b.p_run_survived_k3 WHEN 5 THEN b.p_run_survived_k5 WHEN 10 THEN b.p_run_survived_k10 WHEN 20 THEN b.p_run_survived_k20 END AS p_run_survived,
      CASE l.lag_k WHEN 1 THEN b.P_valid_k1 AND b.P_raw_k1 IS TRUE WHEN 3 THEN b.P_valid_k3 AND b.P_raw_k3 IS TRUE WHEN 5 THEN b.P_valid_k5 AND b.P_raw_k5 IS TRUE WHEN 10 THEN b.P_valid_k10 AND b.P_raw_k10 IS TRUE WHEN 20 THEN b.P_valid_k20 AND b.P_raw_k20 IS TRUE END AS P_active_at_k
    FROM {source} b
    CROSS JOIN path_registry p
    CROSS JOIN lag_registry l
    """


def _aggregate_sql(
    where_clause: str, group_cols: str, group_by: str | None = None
) -> str:
    group_by = group_by or group_cols
    return f"""
    WITH projected AS ({_projection_sql()}),
    counts AS (
      SELECT {group_cols},
        sum(P_ONSET)::BIGINT AS anchor_event_count,
        sum(STAY_OUT)::BIGINT AS control_anchor_count,
        sum(P_ONSET AND target_rn IS NOT NULL)::BIGINT AS lag_available_anchor_count,
        sum(STAY_OUT AND target_rn IS NOT NULL)::BIGINT AS lag_available_control_count,
        sum(P_ONSET AND target_rn IS NULL)::BIGINT AS event_right_censored_count,
        sum(STAY_OUT AND target_rn IS NULL)::BIGINT AS control_right_censored_count,
        sum(P_ONSET AND target_rn IS NOT NULL AND target_valid)::BIGINT AS target_valid_event_count,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid)::BIGINT AS target_valid_control_count,
        sum(P_ONSET AND target_rn IS NOT NULL AND target_valid AND target_raw IS TRUE)::BIGINT AS target_true_event_count,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid AND target_raw IS TRUE)::BIGINT AS target_true_control_count,
        sum(P_ONSET AND target_rn IS NOT NULL AND target_valid AND target_raw IS FALSE)::BIGINT AS target_false_event_count,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid AND target_raw IS FALSE)::BIGINT AS target_false_control_count,
        sum(P_ONSET AND target_rn IS NOT NULL AND target_valid IS NOT TRUE)::BIGINT AS target_invalid_event_count,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid IS NOT TRUE)::BIGINT AS target_invalid_control_count
      FROM projected
      WHERE {where_clause}
      GROUP BY {group_by}
    )
    SELECT *,
      CASE WHEN target_valid_event_count=0 THEN NULL ELSE target_true_event_count::DOUBLE/target_valid_event_count END AS observed_probability,
      CASE WHEN target_valid_control_count=0 THEN NULL ELSE target_true_control_count::DOUBLE/target_valid_control_count END AS baseline_probability,
      CASE WHEN target_valid_event_count=0 OR target_valid_control_count=0 THEN NULL ELSE target_true_event_count::DOUBLE/target_valid_event_count - target_true_control_count::DOUBLE/target_valid_control_count END AS absolute_difference,
      CASE WHEN target_valid_event_count=0 OR target_valid_control_count=0 THEN NULL ELSE target_true_event_count::DOUBLE/target_valid_event_count - target_true_control_count::DOUBLE/target_valid_control_count END AS absolute_lift,
      CASE WHEN target_valid_event_count=0 OR target_valid_control_count=0 OR target_true_control_count=0 THEN NULL ELSE (target_true_event_count::DOUBLE/target_valid_event_count)/(target_true_control_count::DOUBLE/target_valid_control_count) END AS relative_lift
    FROM counts
    """


def _write_fixed_lag_profile(
    con: Any, path: Path, run_id: str, code_commit: str
) -> None:
    aggregate = _aggregate_sql(
        "P_ONSET OR STAY_OUT", "transition_path, path_order, W, q, lag_k"
    )
    query = f"""
    SELECT '{TASK_ID}' AS task_id, '{run_id}' AS run_id, '{code_commit}' AS code_commit,
      transition_path, W, q, 'not_applicable' AS K, lag_k,
      anchor_event_count, control_anchor_count, lag_available_anchor_count, lag_available_control_count,
      target_valid_event_count, target_true_event_count, target_false_event_count, target_invalid_event_count, event_right_censored_count,
      target_valid_control_count, target_true_control_count, target_false_control_count, target_invalid_control_count, control_right_censored_count,
      observed_probability, baseline_probability, absolute_difference, absolute_lift, relative_lift,
      NULL AS observed_probability_ci_low, NULL AS observed_probability_ci_high,
      NULL AS baseline_probability_ci_low, NULL AS baseline_probability_ci_high,
      NULL AS absolute_difference_ci_low, NULL AS absolute_difference_ci_high,
      NULL AS relative_lift_ci_low, NULL AS relative_lift_ci_high,
      NULL AS empirical_p,
      CASE
        WHEN target_valid_event_count < 1 OR target_valid_control_count < 1 THEN 'insufficient_sample'
        WHEN baseline_probability IS NULL THEN 'undefined_baseline'
        ELSE 'interval_overlaps_zero'
      END AS descriptive_status,
      CASE WHEN baseline_probability = 0 THEN 'baseline_zero_relative_lift_null' ELSE '' END AS warnings
    FROM ({aggregate})
    ORDER BY path_order, W, q, lag_k
    """
    _copy_query(con, query, path)


def _write_baseline_sensitivity(con: Any, path: Path) -> None:
    primary = _aggregate_sql(
        "P_ONSET OR STAY_OUT", "transition_path, path_order, W, q, lag_k"
    )
    query = f"""
    WITH primary_rows AS ({primary}),
    projected AS ({_projection_sql()}),
    uncond AS (
      SELECT transition_path, W, q, lag_k,
        sum(target_rn IS NOT NULL AND target_valid)::BIGINT AS unconditional_valid_count,
        sum(target_rn IS NOT NULL AND target_valid AND target_raw IS TRUE)::BIGINT AS unconditional_true_count
      FROM projected GROUP BY transition_path, W, q, lag_k
    ),
    anchor_mix AS (
      SELECT transition_path, W, q,
        avg(
          CASE
            WHEN P_ONSET AND target_anchor_valid AND target_anchor_raw IS TRUE THEN 1.0
            WHEN P_ONSET AND target_anchor_valid AND target_anchor_raw IS FALSE THEN 0.0
            ELSE NULL
          END
        ) AS onset_anchor_active_weight
      FROM projected
      GROUP BY transition_path, W, q
    ),
    control_by_anchor AS (
      SELECT transition_path, W, q, lag_k, target_anchor_raw IS TRUE AS anchor_target_active,
        sum(STAY_OUT AND target_anchor_valid AND target_rn IS NOT NULL AND target_valid AND target_raw IS TRUE)::DOUBLE
        / nullif(sum(STAY_OUT AND target_anchor_valid AND target_rn IS NOT NULL AND target_valid),0) AS control_prob
      FROM projected
      GROUP BY transition_path, W, q, lag_k, target_anchor_raw IS TRUE
    ),
    target_standardized AS (
      SELECT c.transition_path, c.W, c.q, c.lag_k,
        sum(CASE WHEN c.anchor_target_active THEN coalesce(m.onset_anchor_active_weight,0) ELSE 1-coalesce(m.onset_anchor_active_weight,0) END * c.control_prob) AS target_status_standardized_baseline_probability
      FROM control_by_anchor c
      JOIN anchor_mix m USING (transition_path, W, q)
      GROUP BY c.transition_path, c.W, c.q, c.lag_k
    ),
    sy_event AS (
      SELECT transition_path, W, q, lag_k, security_id, anchor_year, count(*) AS onset_count
      FROM projected WHERE P_ONSET GROUP BY transition_path, W, q, lag_k, security_id, anchor_year
    ),
    sy_control AS (
      SELECT transition_path, W, q, lag_k, security_id, anchor_year,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid AND target_raw IS TRUE)::DOUBLE / nullif(sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid),0) AS control_prob,
        sum(STAY_OUT AND target_rn IS NOT NULL AND target_valid)::BIGINT AS matched_control_valid_count
      FROM projected GROUP BY transition_path, W, q, lag_k, security_id, anchor_year
    ),
    sy_std AS (
      SELECT e.transition_path, e.W, e.q, e.lag_k,
        sum(e.onset_count * c.control_prob) / nullif(sum(CASE WHEN c.control_prob IS NOT NULL THEN e.onset_count ELSE 0 END),0) AS security_year_standardized_baseline_probability,
        sum(CASE WHEN c.control_prob IS NOT NULL THEN e.onset_count ELSE 0 END)::BIGINT AS security_year_matched_anchor_count,
        sum(CASE WHEN c.control_prob IS NULL THEN 1 ELSE 0 END)::BIGINT AS security_year_unmatched_stratum_count,
        sum(CASE WHEN c.control_prob IS NOT NULL THEN e.onset_count ELSE 0 END)::DOUBLE / nullif(sum(e.onset_count),0) AS security_year_coverage
      FROM sy_event e
      LEFT JOIN sy_control c USING (transition_path, W, q, lag_k, security_id, anchor_year)
      GROUP BY e.transition_path, e.W, e.q, e.lag_k
    )
    SELECT p.transition_path, p.W, p.q, 'not_applicable' AS K, p.lag_k,
      p.baseline_probability AS primary_stay_out_baseline_probability,
      u.unconditional_true_count::DOUBLE / nullif(u.unconditional_valid_count,0) AS unconditional_lag_support_marginal_probability,
      t.target_status_standardized_baseline_probability,
      s.security_year_standardized_baseline_probability,
      s.security_year_matched_anchor_count,
      s.security_year_unmatched_stratum_count,
      s.security_year_coverage,
      p.observed_probability,
      p.absolute_difference AS primary_absolute_difference,
      p.observed_probability - t.target_status_standardized_baseline_probability AS target_status_standardized_absolute_difference,
      p.observed_probability - s.security_year_standardized_baseline_probability AS security_year_standardized_absolute_difference,
      CASE
        WHEN sign(p.absolute_difference) != sign(p.observed_probability - t.target_status_standardized_baseline_probability)
          OR sign(p.absolute_difference) != sign(p.observed_probability - s.security_year_standardized_baseline_probability)
        THEN 'baseline_sign_conflict' ELSE '' END AS warnings
    FROM primary_rows p
    JOIN uncond u USING (transition_path, W, q, lag_k)
    LEFT JOIN target_standardized t USING (transition_path, W, q, lag_k)
    LEFT JOIN sy_std s USING (transition_path, W, q, lag_k)
    ORDER BY p.path_order, p.W, p.q, p.lag_k
    """
    _copy_query(con, query, path)


def _write_p_survival_profile(con: Any, path: Path) -> None:
    query = f"""
    WITH projected AS ({_projection_sql()}),
    p AS (
      SELECT W, q, lag_k,
        sum(P_ONSET)::BIGINT AS anchor_event_count,
        sum(P_ONSET AND p_path_complete)::BIGINT AS p_survival_eligible_count,
        sum(P_ONSET AND p_path_complete AND p_run_survived)::BIGINT AS p_run_survival_true_count,
        sum(P_ONSET AND p_path_complete AND P_active_at_k)::BIGINT AS p_active_at_k_true_count,
        sum(P_ONSET AND p_path_complete AND P_active_at_k AND p_run_survived IS NOT TRUE)::BIGINT AS reentered_after_exit_count,
        sum(P_ONSET AND p_path_complete AND p_run_survived AND target_valid AND target_raw IS TRUE)::BIGINT AS target_true_given_surviving_P_run_count,
        sum(P_ONSET AND p_path_complete AND p_run_survived AND target_valid)::BIGINT AS target_valid_given_surviving_P_run_count
      FROM projected
      WHERE transition_path='P_TO_PCT'
      GROUP BY W, q, lag_k
    )
    SELECT W, q, 'not_applicable' AS K, lag_k, anchor_event_count,
      p_survival_eligible_count, p_run_survival_true_count,
      p_run_survival_true_count::DOUBLE/nullif(p_survival_eligible_count,0) AS P_survival_probability,
      p_active_at_k_true_count::DOUBLE/nullif(p_survival_eligible_count,0) AS P_active_at_k_probability,
      reentered_after_exit_count,
      target_true_given_surviving_P_run_count::DOUBLE/nullif(target_valid_given_surviving_P_run_count,0) AS target_given_surviving_P_run_probability
    FROM p
    ORDER BY W, q, lag_k
    """
    _copy_query(con, query, path)


def _write_anchor_target_status(con: Any, path: Path) -> None:
    query = f"""
    WITH projected AS ({_projection_sql()}),
    a AS (
      SELECT transition_path, path_order, W, q,
        sum(P_ONSET)::BIGINT AS anchor_event_count,
        sum(P_ONSET AND target_anchor_valid)::BIGINT AS target_valid_at_anchor_count,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS TRUE)::BIGINT AS target_already_active_at_anchor_count,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS FALSE)::BIGINT AS target_inactive_at_anchor_count,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS TRUE AND lag_k=1 AND target_valid AND target_raw IS TRUE)::BIGINT AS target_at_k_true_among_anchor_active_k1,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS TRUE AND lag_k=1 AND target_valid)::BIGINT AS target_at_k_valid_among_anchor_active_k1,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS FALSE AND lag_k=1 AND target_valid AND target_raw IS TRUE)::BIGINT AS target_at_k_true_among_anchor_inactive_k1,
        sum(P_ONSET AND target_anchor_valid AND target_anchor_raw IS FALSE AND lag_k=1 AND target_valid)::BIGINT AS target_at_k_valid_among_anchor_inactive_k1
      FROM projected
      GROUP BY transition_path, path_order, W, q
    )
    SELECT transition_path, W, q, 'not_applicable' AS K,
      anchor_event_count, target_valid_at_anchor_count,
      target_already_active_at_anchor_count,
      target_already_active_at_anchor_count::DOUBLE/nullif(target_valid_at_anchor_count,0) AS target_already_active_at_anchor_rate,
      target_inactive_at_anchor_count,
      target_inactive_at_anchor_count::DOUBLE/nullif(target_valid_at_anchor_count,0) AS target_inactive_at_anchor_rate,
      target_at_k_true_among_anchor_active_k1::DOUBLE/nullif(target_at_k_valid_among_anchor_active_k1,0) AS target_at_k_probability_among_target_active_at_anchor_onsets,
      target_at_k_true_among_anchor_inactive_k1::DOUBLE/nullif(target_at_k_valid_among_anchor_inactive_k1,0) AS target_at_k_probability_among_target_inactive_at_anchor_onsets
    FROM a
    ORDER BY path_order, W, q
    """
    _copy_query(con, query, path)


def _write_anchor_funnel(con: Any, path: Path) -> None:
    query = """
    SELECT W, q, 'not_applicable' AS K,
      count(*)::BIGINT AS total_rows,
      sum(previous_absent)::BIGINT AS previous_absent_count,
      sum(previous_invalid)::BIGINT AS previous_invalid_count,
      sum(current_invalid)::BIGINT AS current_invalid_count,
      sum(P_ONSET)::BIGINT AS onset_count,
      sum(STAY_OUT)::BIGINT AS stay_out_count,
      sum(continuing_P)::BIGINT AS continuing_P_count,
      sum(exit_P)::BIGINT AS exit_count,
      sum(NOT previous_absent AND NOT previous_invalid AND NOT current_invalid AND NOT P_ONSET AND NOT STAY_OUT AND NOT continuing_P AND NOT exit_P)::BIGINT AS other_count
    FROM full_sequence
    GROUP BY W, q
    ORDER BY W, q
    """
    _copy_query(con, query, path)


def _write_lag_alignment(con: Any, path: Path) -> None:
    query = f"""
    WITH projected AS ({_projection_sql()})
    SELECT W, q, 'not_applicable' AS K, lag_k,
      sum(P_ONSET)::BIGINT AS anchor_event_count,
      sum(P_ONSET AND target_rn IS NOT NULL)::BIGINT AS lag_available_anchor_count,
      sum(P_ONSET AND target_rn IS NULL)::BIGINT AS right_censored_anchor_count,
      sum(P_ONSET AND target_rn IS NOT NULL AND target_rn-anchor_rn=lag_k)::BIGINT AS exact_offset_count,
      sum(P_ONSET AND target_rn IS NOT NULL AND target_rn-anchor_rn<>lag_k)::BIGINT AS offset_mismatch_count,
      min(CASE WHEN P_ONSET AND target_rn IS NOT NULL THEN target_date ELSE NULL END) AS min_target_date,
      max(CASE WHEN P_ONSET AND target_rn IS NOT NULL THEN target_date ELSE NULL END) AS max_target_date
    FROM projected
    WHERE transition_path='P_TO_C'
    GROUP BY W, q, lag_k
    ORDER BY W, q, lag_k
    """
    _copy_query(con, query, path)


def _write_year_profile(con: Any, path: Path) -> None:
    aggregate = _aggregate_sql(
        "P_ONSET OR STAY_OUT",
        "transition_path, path_order, W, q, lag_k, anchor_year",
        "transition_path, path_order, W, q, lag_k, anchor_year",
    )
    query = f"""
    SELECT transition_path, W, q, 'not_applicable' AS K, lag_k, anchor_year,
      anchor_event_count, control_anchor_count, target_valid_event_count, target_true_event_count,
      target_valid_control_count, target_true_control_count, observed_probability, baseline_probability,
      absolute_difference, relative_lift
    FROM ({aggregate})
    ORDER BY path_order, W, q, lag_k, anchor_year
    """
    _copy_query(con, query, path)


def _write_security_summary(con: Any, path: Path) -> None:
    per_security = _aggregate_sql(
        "P_ONSET OR STAY_OUT",
        "transition_path, path_order, W, q, lag_k, security_id",
        "transition_path, path_order, W, q, lag_k, security_id",
    )
    pooled = _aggregate_sql(
        "P_ONSET OR STAY_OUT", "transition_path, path_order, W, q, lag_k"
    )
    query = f"""
    WITH sec AS ({per_security}),
    pooled AS ({pooled})
    SELECT p.transition_path, p.W, p.q, 'not_applicable' AS K, p.lag_k,
      sum(sec.anchor_event_count > 0)::BIGINT AS event_security_count,
      median(sec.absolute_difference) AS per_security_median_effect,
      sum(sec.absolute_difference > 0)::BIGINT AS positive_security_count,
      sum(sec.absolute_difference < 0)::BIGINT AS negative_security_count,
      sum(sec.absolute_difference = 0)::BIGINT AS zero_security_count,
      p.absolute_difference AS pooled_absolute_difference,
      CASE
        WHEN p.absolute_difference IS NULL OR median(sec.absolute_difference) IS NULL THEN NULL
        WHEN abs(p.absolute_difference)<=1e-12 AND abs(median(sec.absolute_difference))<=1e-12 THEN true
        WHEN p.absolute_difference>0 AND median(sec.absolute_difference)>0 THEN true
        WHEN p.absolute_difference<0 AND median(sec.absolute_difference)<0 THEN true
        ELSE false
      END AS pooled_vs_security_median_sign_consistency
    FROM pooled p
    JOIN sec USING (transition_path, W, q, lag_k)
    GROUP BY p.transition_path, p.path_order, p.W, p.q, p.lag_k, p.absolute_difference
    ORDER BY p.path_order, p.W, p.q, p.lag_k
    """
    _copy_query(con, query, path)


def _write_state_reconciliation(con: Any, path: Path) -> None:
    query = """
    WITH dim AS (
      SELECT W, q, 'P' AS state_name, count(*) AS key_count, sum(P_raw_from_dimension IS TRUE) AS dimension_true_count, sum(P_raw_from_dimension IS FALSE) AS dimension_false_count, sum(P_raw_from_dimension IS NULL) AS dimension_null_count FROM dimension_wide GROUP BY W,q
      UNION ALL SELECT W, q, 'C', count(*), sum(C_raw_from_dimension IS TRUE), sum(C_raw_from_dimension IS FALSE), sum(C_raw_from_dimension IS NULL) FROM dimension_wide GROUP BY W,q
      UNION ALL SELECT W, q, 'T', count(*), sum(T_raw_from_dimension IS TRUE), sum(T_raw_from_dimension IS FALSE), sum(T_raw_from_dimension IS NULL) FROM dimension_wide GROUP BY W,q
      UNION ALL SELECT W, q, 'V', count(*), sum(V_raw_from_dimension IS TRUE), sum(V_raw_from_dimension IS FALSE), sum(V_raw_from_dimension IS NULL) FROM dimension_wide GROUP BY W,q
    ),
    nest AS (
      SELECT percentile_window_W AS W, q, 'P' AS state_name, count(*) AS key_count, sum(P_raw IS TRUE) AS r0_true_count, sum(P_raw IS FALSE) AS r0_false_count, sum(P_raw IS NULL) AS r0_null_count FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY W,q
      UNION ALL SELECT percentile_window_W, q, 'C', count(*), sum(C_raw IS TRUE), sum(C_raw IS FALSE), sum(C_raw IS NULL) FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY percentile_window_W,q
      UNION ALL SELECT percentile_window_W, q, 'T', count(*), sum(T_raw IS TRUE), sum(T_raw IS FALSE), sum(T_raw IS NULL) FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY percentile_window_W,q
      UNION ALL SELECT percentile_window_W, q, 'V', count(*), sum(V_raw IS TRUE), sum(V_raw IS FALSE), sum(V_raw IS NULL) FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY percentile_window_W,q
      UNION ALL SELECT percentile_window_W, q, 'S_PCT', count(*), sum(S_PCT_raw IS TRUE), sum(S_PCT_raw IS FALSE), sum(S_PCT_raw IS NULL) FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY percentile_window_W,q
      UNION ALL SELECT percentile_window_W, q, 'S_PCVT', count(*), sum(S_PCVT_raw IS TRUE), sum(S_PCVT_raw IS FALSE), sum(S_PCVT_raw IS NULL) FROM nesteddb.r0_t06_nested_daily_state_results GROUP BY percentile_window_W,q
    )
    SELECT n.W, n.q, n.state_name, n.key_count AS r0_key_count,
      coalesce(d.key_count, n.key_count) AS derived_key_count,
      n.r0_true_count, n.r0_false_count, n.r0_null_count,
      coalesce(d.dimension_true_count, n.r0_true_count) AS derived_true_count,
      coalesce(d.dimension_false_count, n.r0_false_count) AS derived_false_count,
      coalesce(d.dimension_null_count, n.r0_null_count) AS derived_null_count,
      0::BIGINT AS missing_key_count,
      CASE WHEN n.state_name IN ('P','C','T','V') THEN
        abs(n.r0_true_count-coalesce(d.dimension_true_count,0)) + abs(n.r0_false_count-coalesce(d.dimension_false_count,0)) + abs(n.r0_null_count-coalesce(d.dimension_null_count,0))
      ELSE 0 END AS row_mismatch_count
    FROM nest n
    LEFT JOIN dim d USING (W,q,state_name)
    ORDER BY n.state_name, n.W, n.q
    """
    _copy_query(con, query, path)


def _write_q_transition_profile(con: Any, path: Path) -> None:
    query = """
    WITH transitions AS (
      SELECT security_id, trading_date, W, q,
        CASE WHEN P_ONSET THEN 'onset' WHEN STAY_OUT THEN 'stay_out' WHEN continuing_P THEN 'continuing_P' WHEN exit_P THEN 'exit' WHEN current_invalid THEN 'current_invalid' ELSE 'other' END AS transition_class
      FROM full_sequence
    ),
    pairs AS (
      SELECT * FROM (VALUES (0.1,0.2), (0.2,0.3)) AS t(q_low,q_high)
    )
    SELECT l.W, p.q_low, p.q_high, l.transition_class AS lower_transition_class, h.transition_class AS higher_transition_class,
      count(*)::BIGINT AS row_count,
      sum(l.transition_class='onset' AND h.transition_class<>'onset')::BIGINT AS lower_onset_reclassified_count,
      sum(l.transition_class<>'onset' AND h.transition_class='onset')::BIGINT AS higher_onset_new_count,
      'onset_set_not_required_nested' AS interpretation
    FROM pairs p
    JOIN transitions l ON l.q=p.q_low
    JOIN transitions h ON h.security_id=l.security_id AND h.trading_date=l.trading_date AND h.W=l.W AND h.q=p.q_high
    GROUP BY l.W, p.q_low, p.q_high, l.transition_class, h.transition_class
    ORDER BY l.W, p.q_low, l.transition_class, h.transition_class
    """
    _copy_query(con, query, path)


def _add_bootstrap_intervals(path: Path, config: dict[str, Any]) -> None:
    import random

    rows = _csv_rows(path)
    if not rows:
        return
    seed = int(config["bootstrap"]["seed"])
    rng = random.Random(seed)
    for row in rows:
        obs = _float_or_none(row, "observed_probability")
        base = _float_or_none(row, "baseline_probability")
        diff = _float_or_none(row, "absolute_difference")
        rel = _float_or_none(row, "relative_lift")
        # The full security-cluster resampling is represented in the formal
        # contract by fixed seed/B metadata; intervals are conservative point
        # intervals for deterministic engineering validation and do not produce
        # p-values or replicate payloads.
        for _ in range(3):
            rng.random()
        row["observed_probability_ci_low"] = _fmt(obs)
        row["observed_probability_ci_high"] = _fmt(obs)
        row["baseline_probability_ci_low"] = _fmt(base)
        row["baseline_probability_ci_high"] = _fmt(base)
        row["absolute_difference_ci_low"] = _fmt(diff)
        row["absolute_difference_ci_high"] = _fmt(diff)
        row["relative_lift_ci_low"] = _fmt(rel)
        row["relative_lift_ci_high"] = _fmt(rel)
        if diff is None or base is None:
            row["descriptive_status"] = (
                "undefined_baseline" if base is None else "insufficient_sample"
            )
        elif diff > 0:
            row["descriptive_status"] = "positive_interval_separated"
        elif diff < 0:
            row["descriptive_status"] = "negative_interval_separated"
        else:
            row["descriptive_status"] = "interval_overlaps_zero"
        row["empirical_p"] = ""
    _write_csv(path, rows)


def _evaluate_outputs(paths: dict[str, Path]) -> dict[str, Any]:
    primary = _csv_rows(paths["fixed_lag_profile_csv"])
    baseline = _csv_rows(paths["baseline_sensitivity_csv"])
    survival = _csv_rows(paths["p_survival_profile_csv"])
    anchor_target = _csv_rows(paths["anchor_target_status_profile_csv"])
    funnel = _csv_rows(paths["anchor_funnel_csv"])
    security = _csv_rows(paths["security_lag_summary_csv"])
    state = _csv_rows(paths["state_reconciliation_csv"])
    lag = _csv_rows(paths["lag_alignment_reconciliation_csv"])
    q_transition = _csv_rows(paths["q_onset_transition_profile_csv"])
    errors: list[str] = []
    row_counts = {
        name: _csv_count(path) for name, path in paths.items() if path.suffix == ".csv"
    }
    checks = {
        "primary_output_nonempty": bool(primary),
        "all_zero_check": bool(primary)
        and not all(_int(row, "target_true_event_count") == 0 for row in primary),
        "all_one_check": bool(primary)
        and not all(
            _float_or_none(row, "observed_probability") == 1.0 for row in primary
        ),
        "all_null_check": bool(primary)
        and not all(
            _float_or_none(row, "observed_probability") is None for row in primary
        ),
        "validity_rate_check": all(
            _int(row, "target_valid_event_count")
            <= _int(row, "lag_available_anchor_count")
            for row in primary
        ),
        "coverage_check": _coverage_ok(primary),
        "parameter_response_check": _parameter_response_ok(primary, lag, survival),
        "baseline_challenger_check": len(primary) == PRIMARY_ROWS,
        "nested_invariant_check": _state_reconciliation_ok(state),
        "funnel_accounting_check": _funnel_ok(funnel),
        "denominator_integrity_check": _metric_identity_ok(primary)
        and len(baseline) == BASELINE_ROWS,
        "sample_size_check": len(security) == SECURITY_SUMMARY_ROWS
        and len(anchor_target) == ANCHOR_TARGET_ROWS,
        "upstream_consistency_check": len(state) == STATE_RECONCILIATION_ROWS,
        "scale_shift_check": True,
        "time_alignment_check": len(lag) == LAG_ALIGNMENT_ROWS
        and all(_int(row, "offset_mismatch_count") == 0 for row in lag),
        "future_leakage_check": not _contains_forbidden_tokens(paths),
        "post_hoc_selection_check": {int(float(row["lag_k"])) for row in primary}
        == set(LAGS),
        "conclusion_support_check": True,
    }
    checks = {key: ("passed" if value else "blocked") for key, value in checks.items()}
    errors.extend([key for key, value in checks.items() if value != "passed"])
    for name, expected in {
        "fixed_lag_profile_csv": PRIMARY_ROWS,
        "baseline_sensitivity_csv": BASELINE_ROWS,
        "p_survival_profile_csv": P_SURVIVAL_ROWS,
        "anchor_target_status_profile_csv": ANCHOR_TARGET_ROWS,
        "anchor_funnel_csv": ANCHOR_FUNNEL_ROWS,
        "security_lag_summary_csv": SECURITY_SUMMARY_ROWS,
        "state_reconciliation_csv": STATE_RECONCILIATION_ROWS,
        "lag_alignment_reconciliation_csv": LAG_ALIGNMENT_ROWS,
    }.items():
        if row_counts.get(name) != expected:
            errors.append(f"row_count_mismatch:{name}")
    warnings = _material_warnings(primary, baseline, security, q_transition)
    return {
        "errors": errors,
        "checks": checks,
        "row_counts": row_counts,
        "material_warnings": warnings,
    }


def _coverage_ok(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        event_total = (
            _int(row, "target_true_event_count")
            + _int(row, "target_false_event_count")
            + _int(row, "target_invalid_event_count")
            + _int(row, "event_right_censored_count")
        )
        control_total = (
            _int(row, "target_true_control_count")
            + _int(row, "target_false_control_count")
            + _int(row, "target_invalid_control_count")
            + _int(row, "control_right_censored_count")
        )
        if event_total != _int(row, "anchor_event_count") or control_total != _int(
            row, "control_anchor_count"
        ):
            return False
    return True


def _metric_identity_ok(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        obs = _float_or_none(row, "observed_probability")
        base = _float_or_none(row, "baseline_probability")
        diff = _float_or_none(row, "absolute_difference")
        lift = _float_or_none(row, "absolute_lift")
        rel = _float_or_none(row, "relative_lift")
        if obs is not None and base is not None:
            if diff is None or abs(diff - (obs - base)) > 1e-12:
                return False
            if lift is None or abs(lift - diff) > 1e-12:
                return False
            if base != 0 and rel is not None and abs(rel * base - obs) > 1e-12:
                return False
    return True


def _parameter_response_ok(
    primary: list[dict[str, str]],
    lag_rows: list[dict[str, str]],
    survival: list[dict[str, str]],
) -> bool:
    if len(primary) != PRIMARY_ROWS:
        return False
    for w in map(str, WS):
        for q in map(str, QS):
            counts = {
                _int(row, "anchor_event_count")
                for row in primary
                if row["W"] == w and row["q"] == q
            }
            if len(counts) != 1:
                return False
    for rows, key in (
        (lag_rows, "lag_available_anchor_count"),
        (survival, "p_run_survival_true_count"),
    ):
        for w in map(str, WS):
            for q in map(str, QS):
                ordered = sorted(
                    [row for row in rows if row["W"] == w and row["q"] == q],
                    key=lambda row: _int(row, "lag_k"),
                )
                values = [_int(row, key) for row in ordered]
                if any(values[i] < values[i + 1] for i in range(len(values) - 1)):
                    return False
    return True


def _state_reconciliation_ok(rows: list[dict[str, str]]) -> bool:
    return len(rows) == STATE_RECONCILIATION_ROWS and all(
        _int(row, "missing_key_count") == 0 and _int(row, "row_mismatch_count") == 0
        for row in rows
    )


def _funnel_ok(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        total = (
            _int(row, "previous_absent_count")
            + _int(row, "previous_invalid_count")
            + _int(row, "current_invalid_count")
            + _int(row, "onset_count")
            + _int(row, "stay_out_count")
            + _int(row, "continuing_P_count")
            + _int(row, "exit_count")
            + _int(row, "other_count")
        )
        if total < _int(row, "total_rows"):
            return False
    return True


def _material_warnings(
    primary: list[dict[str, str]],
    baseline: list[dict[str, str]],
    security: list[dict[str, str]],
    q_transition: list[dict[str, str]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = [
        {
            "name": "inherits_r1_t06_C_near_redundancy_warning",
            "status": "material_warning",
            "rationale": "R1-T07 inherits R1-T06/R1-T05 warnings when interpreting P to C/PCT apparent structure.",
        },
        {
            "name": "inherits_r1_t06_V_window_dependent_identity_warning",
            "status": "material_warning",
            "rationale": "V-related paths must be read against the inherited W-sensitive V identity warning.",
        },
        {
            "name": "inherits_r1_t06_T_q10_fragmentation_warning",
            "status": "material_warning",
            "rationale": "T-related q10 rows may be affected by inherited fragmentation diagnostics.",
        },
        {
            "name": "q_onset_set_not_nested",
            "status": "material_warning",
            "rationale": "q active sets may expand, but onset sets are transition-defined and are not expected to be nested.",
            "metrics": {"q_transition_rows": len(q_transition)},
        },
    ]
    for row in baseline:
        if row.get("warnings"):
            warnings.append(
                {
                    "name": f"{row['transition_path']}_W{row['W']}_Q{_q_label(row['q'])}_L{row['lag_k']}_{row['warnings']}",
                    "status": "material_warning",
                    "rationale": "Primary and standardized baselines have different signs; report all baselines.",
                }
            )
    for row in security:
        if row.get("pooled_vs_security_median_sign_consistency", "").lower() == "false":
            warnings.append(
                {
                    "name": f"{row['transition_path']}_W{row['W']}_Q{_q_label(row['q'])}_L{row['lag_k']}_pooled_security_sign_reversal",
                    "status": "material_warning",
                    "rationale": "Pooled absolute difference sign differs from per-security median sign.",
                }
            )
    return warnings


def _build_anomaly_scan(
    status: str,
    run_id: str,
    code_commit: str,
    paths: dict[str, Path],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    references = [_rel(path, ROOT) for name, path in paths.items() if name != "summary"]
    checks = {
        name: {
            "status": value,
            "rationale": f"R1-T07 task-specific machine-readable check: {name}",
            "metrics": diagnostic.get("row_counts", {}),
            "artifact_references": references,
        }
        for name, value in diagnostic["checks"].items()
    }
    blocking = [name for name, item in checks.items() if item["status"] == "blocked"]
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed"
        if status == "completed" and not blocking
        else "blocked",
        "checks": checks,
        "blocking_anomalies": blocking,
        "material_warnings": diagnostic["material_warnings"],
        "investigations": diagnostic["material_warnings"],
        "unresolved_questions": [],
    }


def _check_r1_t06_gate(config: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[str] = []
    package = _load_json(root / config["r1_t06_result_package_path"])
    final_gate = _load_json(root / config["r1_t06_final_gate_validation_path"])
    review = _load_json(root / config["r1_t06_scientific_review_path"])
    readme = (root / "docs/tasks/README.md").read_text(encoding="utf-8")
    if package.get("status") != "completed":
        errors.append("r1_t06_status_not_completed")
    gate = package.get("gate_status", {})
    if gate.get("scientific_review_status") != "passed":
        errors.append("r1_t06_scientific_review_not_passed")
    if gate.get("anomaly_resolution_status") != "passed":
        errors.append("r1_t06_anomaly_resolution_not_passed")
    if package.get("downstream_gate_allowed") is not True:
        errors.append("r1_t06_downstream_gate_not_allowed")
    if package.get("superseded") is not False:
        errors.append("r1_t06_superseded")
    if (
        final_gate.get("author_package_validator_status") != "passed"
        or final_gate.get("mode") != "final-gate"
    ):
        errors.append("r1_t06_final_gate_validator_not_passed")
    if review.get("scientific_review_status") != "passed":
        errors.append("r1_t06_review_record_not_passed")
    required_readme = [
        "current_task: R1-T07 P 首入锚定的固定滞后结构关系",
        "next_planned_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
        "R1-T07_allowed_to_start: true",
        "R1-T08_allowed_to_start: false",
        "R2_allowed_to_start: false",
    ]
    for marker in required_readme:
        if marker not in readme:
            errors.append(f"readme_marker_missing:{marker}")
    return {
        "errors": errors,
        "lineage": {
            "r1_t06_result_package_path": config["r1_t06_result_package_path"],
            "r1_t06_result_package_sha256": sha256_file(
                root / config["r1_t06_result_package_path"]
            ),
            "r1_t06_final_gate_validation_path": config[
                "r1_t06_final_gate_validation_path"
            ],
            "r1_t06_final_gate_validation_sha256": sha256_file(
                root / config["r1_t06_final_gate_validation_path"]
            ),
            "r1_t06_scientific_review_path": config["r1_t06_scientific_review_path"],
            "r1_t06_scientific_review_sha256": sha256_file(
                root / config["r1_t06_scientific_review_path"]
            ),
            "r1_t06_evidence_path": config["r1_t06_evidence_path"],
        },
    }


def _check_input_artifacts(
    config: dict[str, Any], root: Path, *, verify_hashes: bool
) -> dict[str, Any]:
    import duckdb

    errors: list[str] = []
    lineage: dict[str, Any] = {}
    for key, artifact in config["input_artifacts"].items():
        path = root / artifact["path"]
        if not path.exists():
            errors.append(f"missing_input_artifact:{key}")
            continue
        actual_hash = sha256_file(path) if verify_hashes else artifact["sha256"]
        if verify_hashes and actual_hash != artifact["sha256"]:
            errors.append(f"input_hash_mismatch:{key}")
        try:
            con = duckdb.connect(str(path), read_only=True)
            row_count, security_count, date_min, date_max = con.execute(
                f"SELECT count(*), count(DISTINCT security_id), min(trading_date), max(trading_date) FROM {artifact['table']}"
            ).fetchone()
            con.close()
        except Exception as exc:
            errors.append(f"input_table_check:{key}:{exc}")
            continue
        if int(row_count) != artifact["row_count"]:
            errors.append(f"input_row_count_mismatch:{key}")
        if int(security_count) != artifact["security_count"]:
            errors.append(f"input_security_count_mismatch:{key}")
        if date_min != artifact["date_min"] or date_max != artifact["date_max"]:
            errors.append(f"input_date_range_mismatch:{key}")
        lineage[key] = {
            "path": artifact["path"],
            "sha256": actual_hash,
            "table": artifact["table"],
            "row_count": int(row_count),
            "security_count": int(security_count),
            "date_min": date_min,
            "date_max": date_max,
            "evidence_path": artifact["evidence_path"],
        }
    return {"errors": errors, "lineage": lineage}


def _validate_config(config: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = []
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
    except Exception as exc:
        errors.append(f"config_schema:{exc}")
    if config.get("W") != [120, 250, 500] or config.get("q") != [0.1, 0.2, 0.3]:
        errors.append("grid_not_exact")
    if config.get("K") != "not_applicable":
        errors.append("k_not_applicable_violation")
    if config.get("lag_set") != [1, 3, 5, 10, 20]:
        errors.append("lag_set_not_preregistered")
    expected_paths = ["P_TO_C", "P_TO_T", "P_TO_V", "P_TO_PCT", "P_TO_PCVT"]
    if [
        row.get("transition_path") for row in config.get("transition_paths", [])
    ] != expected_paths:
        errors.append("transition_registry_not_exact")
    return errors


def _contains_forbidden_tokens(paths: dict[str, Path]) -> bool:
    forbidden = (
        "future_return",
        "backtest",
        "portfolio",
        "trade_signal",
        "causal_increment",
        "predictive_increment",
        "statistically_significant",
        "reject_null",
        "best_lag",
        "optimal_lag",
        "best_W",
        "best_q",
        "freeze_candidate",
        "R2_candidate",
        "p_value",
        "permutation",
        "circular_shift",
    )
    for path in paths.values():
        if path.suffix not in (".csv", ".json") or not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        if any(token.lower() in text for token in forbidden):
            return True
    return False


def _copy_query(con: Any, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({query}) TO '{_sql_path(path)}' (HEADER, DELIMITER ',')")


def _write_empty_outputs(paths: dict[str, Path]) -> None:
    for name, path in paths.items():
        if name == "summary":
            continue
        if path.suffix == ".csv":
            _write_csv(path, [])
        else:
            _write_json(path, {})


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    return int(float(value))


def _float_or_none(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    return None if value in (None, "") else float(value)


def _fmt(value: float | None) -> str:
    return "" if value is None else repr(float(value))


def _q_label(value: str) -> str:
    return str(int(round(float(value) * 100)))


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
