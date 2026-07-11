from __future__ import annotations

# ruff: noqa: E501
import csv
import hashlib
import json
import math
import platform
import subprocess
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from src.r0.upstream_artifact_io import canonical_json, sha256_file, write_json_atomic
from src.r1.r1_t08_global_nested_null_models import CandidateData, LayerPayload
from src.r1.r1_t08_null_engine import (
    RAW_FALSE,
    RAW_NULL,
    RAW_TRUE,
    VALID,
    derive_continuous_blocks,
    derived_seed,
    deterministic_offsets,
    nested_retention_metrics,
    offset_plan_hash,
    ordered_and,
    shifted_source_indices,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v3.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json"
TASK_ID = "R1-T14-02"
LAYERS = ("P", "C", "T", "V")
STATE_LAYERS = {"S_PCT": ("P", "C", "T"), "S_PCVT": ("P", "C", "T", "V")}
STEP_SPEC = {
    "C_GIVEN_P": (("P",), "C"),
    "T_GIVEN_PC": (("P", "C"), "T"),
    "V_GIVEN_PCT": (("P", "C", "T"), "V"),
}
FAMILY_SPEC = {
    "F1_GLOBAL_PCT": ("S_PCT", "global", ("P",), ("C", "T")),
    "F2_GLOBAL_PCVT": ("S_PCVT", "global", ("P",), ("C", "T", "V")),
    "F3_C_GIVEN_P": ("S_PCT", "nested", ("P",), ("C",)),
    "F4_T_GIVEN_PC": ("S_PCT", "nested", ("P", "C"), ("T",)),
    "F5_V_GIVEN_PCT": ("S_PCVT", "nested", ("P", "C", "T"), ("V",)),
}
INDICATOR_PAIRS = {
    "P": ("P1_NATR14", "P2_LogRange20"),
    "C": ("C1_LogMASpread_5_60", "C2_AdjVWAPSpread_5_60"),
    "T": ("T1_ER20", "T2_AbsTrendT20"),
    "V": ("V1_TurnoverShrink20_60", "V2_AmountLevel20Pct"),
}


class R1T1402Error(RuntimeError):
    pass


@dataclass(frozen=True)
class BaseScoreData:
    W: int
    security_code: np.ndarray
    security_id: np.ndarray
    trading_date: np.ndarray
    year: np.ndarray
    calendar_ordinal: np.ndarray
    score: dict[str, np.ndarray]
    score_min: dict[str, np.ndarray]
    eligible: dict[str, np.ndarray]
    status: dict[str, np.ndarray]
    reason_hash: dict[str, np.ndarray]
    block_starts: np.ndarray
    block_lengths: np.ndarray
    block_id: np.ndarray
    within_block: np.ndarray


def run_r1_t14_02_formal_structural_revalidation(
    *,
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    verify_input_hashes: bool = True,
    n_perm_override: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = _load_json(config_path)
    Draft202012Validator(_load_json(SCHEMA_PATH)).validate(config)
    _validate_governance(config)
    if verify_input_hashes:
        _verify_inputs(config)
    n_perm = int(n_perm_override or config["null_model"]["N_perm"])
    if n_perm_override is None and n_perm != 10000:
        raise R1T1402Error("formal_N_perm_must_equal_10000")
    if n_perm < 2:
        raise R1T1402Error("N_perm_must_be_at_least_2")
    output_dir.mkdir(parents=True, exist_ok=False)

    import duckdb

    con = duckdb.connect()
    con.execute(f"SET threads={int(config['parallelism']['duckdb_threads'])}")
    con.execute(
        "SET memory_limit=?", [str(config["parallelism"]["duckdb_memory_limit"])]
    )
    _attach_inputs(con, config)
    registry = _load_registry(config)
    robust_envelopes = _load_robust_envelopes(config)
    _write_csv(output_dir / "r1_t14_02_candidate_registry.csv", registry)

    existence_rows: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    intralayer_rows: list[dict[str, Any]] = []
    interlayer_rows: list[dict[str, Any]] = []
    loyo_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    candidates: dict[str, CandidateData] = {}
    state_cache: dict[tuple[str, str], dict[str, Any]] = {}
    step_cache: dict[tuple[str, str], dict[str, Any]] = {}

    for W in (120, 250):
        _heartbeat(run_id, "load_base_scores", W=W)
        base = _load_base_score_data(con, W)
        specs = [row for row in registry if int(row["W"]) == W]
        for spec in specs:
            vector_id = str(spec["formal_vector_id"])
            data = _candidate_from_base(base, spec)
            candidates[vector_id] = data
            for state in ("S_PCT", "S_PCVT"):
                profile = _state_profile(data, state)
                state_cache[(vector_id, state)] = profile
                if state not in _relevant_states(spec):
                    continue
                existence_rows.extend(_existence_rows(spec, state, profile))
                interval_rows.append(_interval_row(spec, state, profile))
                year_rows.extend(
                    _year_state_rows(spec, state, profile, config["years"])
                )
                reconciliation_rows.append(
                    _reconcile_r0_state(con, spec, state, profile)
                )
            for step_id in STEP_SPEC:
                pooled, grouped, loyo = _interlayer_profiles(
                    spec, data, step_id, config["years"]
                )
                step_cache[(vector_id, step_id)] = pooled
                interlayer_rows.append(pooled)
                interlayer_rows.extend(grouped)
                loyo_rows.extend(loyo)
        intralayer_rows.extend(_intralayer_rows_for_window(con, specs, W))

    denominator_rows = _denominator_reconciliation_rows(
        registry=registry,
        step_cache=step_cache,
        config=config,
    )

    for spec in registry:
        vector_id = str(spec["formal_vector_id"])
        if bool(spec["baseline_reuse"]):
            continue
        baseline = _baseline_spec(registry, int(spec["W"]))
        for state in _relevant_states(spec):
            identity_rows.append(
                _identity_row(
                    spec,
                    state,
                    state_cache[(vector_id, state)],
                    state_cache[(str(baseline["formal_vector_id"]), state)],
                )
            )

    _write_csv(
        output_dir / "r1_t14_02_r0_lineage_reconciliation.csv", reconciliation_rows
    )
    _write_csv(output_dir / "r1_t14_02_existence_profile.csv", existence_rows)
    _write_csv(output_dir / "r1_t14_02_intralayer_profile.csv", intralayer_rows)
    _write_csv(output_dir / "r1_t14_02_interlayer_profile.csv", interlayer_rows)
    _write_csv(output_dir / "r1_t14_02_identity_overlap.csv", identity_rows)
    _write_csv(output_dir / "r1_t14_02_interval_profile.csv", interval_rows)
    _write_csv(output_dir / "r1_t14_02_year_profile.csv", year_rows)
    _write_csv(output_dir / "r1_t14_02_leave_one_year_out.csv", loyo_rows)
    _write_csv(
        output_dir / "r1_t14_02_denominator_reconciliation.csv", denominator_rows
    )

    _heartbeat(run_id, "formal_null_start", N_perm=n_perm)
    null_results, family_max_rows, multiplicity_rows, replicate_manifest = (
        _run_formal_null(
            registry=registry,
            candidates=candidates,
            state_cache=state_cache,
            step_cache=step_cache,
            n_perm=n_perm,
            root_seed=int(config["null_model"]["root_seed"]),
            run_id=run_id,
        )
    )
    _write_csv(output_dir / "r1_t14_02_null_results.csv", null_results)
    write_json_atomic(
        output_dir / "r1_t14_02_null_replicates_manifest.json", replicate_manifest
    )
    _write_csv(output_dir / "r1_t14_02_family_max_statistic.csv", family_max_rows)
    _write_csv(output_dir / "r1_t14_02_multiplicity_results.csv", multiplicity_rows)

    neighborhood_rows = _neighborhood_rows(
        registry, state_cache, step_cache, multiplicity_rows
    )
    dominance_rows = _dominance_rows(
        registry,
        state_cache,
        step_cache,
        identity_rows,
        robust_envelopes,
        config,
    )
    decision_rows = _decision_rows(
        registry,
        state_cache,
        step_cache,
        interlayer_rows,
        multiplicity_rows,
        year_rows,
        loyo_rows,
        neighborhood_rows,
        dominance_rows,
        config,
    )
    _write_csv(output_dir / "r1_t14_02_neighborhood_profile.csv", neighborhood_rows)
    _write_csv(output_dir / "r1_t14_02_complexity_dominance_matrix.csv", dominance_rows)
    _write_csv(output_dir / "r1_t14_02_candidate_decision_matrix.csv", decision_rows)

    anomaly = _anomaly_scan(
        run_id,
        code_commit,
        registry,
        reconciliation_rows,
        existence_rows,
        interval_rows,
        null_results,
        multiplicity_rows,
        decision_rows,
        denominator_rows,
        dominance_rows,
        n_perm,
    )
    write_json_atomic(output_dir / "r1_t14_02_anomaly_scan.json", anomaly)
    diagnostic = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": anomaly["status"],
        "selection_path_not_independently_confirmed": True,
        "registry_vector_count": len(registry),
        "nonbaseline_vector_count": sum(
            not bool(row["baseline_reuse"]) for row in registry
        ),
        "N_perm": n_perm,
        "family_count": len(FAMILY_SPEC),
        "null_test_count": len(null_results),
        "family_max_row_count": len(family_max_rows),
        "denominator_reconciliation_row_count": len(denominator_rows),
        "candidate_status_counts": _count_by(decision_rows, "candidate_status"),
        "blocking_findings": anomaly["blocking_findings"],
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    write_json_atomic(output_dir / "r1_t14_02_diagnostic_summary.json", diagnostic)
    summary = _experiment_summary(
        config=config,
        config_path=config_path,
        output_dir=output_dir,
        run_id=run_id,
        code_commit=code_commit,
        n_perm=n_perm,
        elapsed=time.perf_counter() - started,
    )
    write_json_atomic(output_dir / "r1_t14_02_experiment_summary.json", summary)
    con.close()
    return summary


def _validate_governance(config: Mapping[str, Any]) -> None:
    if not config.get("selection_path_not_independently_confirmed"):
        raise R1T1402Error("selection_limitation_missing")
    upstream = config["upstream_binding"]
    if not upstream["goal_internal_t14_02_authorized"]:
        raise R1T1402Error("goal_internal_continuation_not_authorized")
    current_revision = config.get("protocol_version") in {
        "R1.v0.4.R1-T14-02.v2",
        "R1.v0.4.R1-T14-02.v3",
    }
    if current_revision:
        if (
            upstream["goal_internal_continuation_gate_status"]
            != "passed_after_repository_merge"
            or not upstream["repository_t14_02_gate_passed"]
            or not upstream.get("current_dependency_verified")
            or not upstream.get("stale_dependency")
        ):
            raise R1T1402Error("revised_repository_gate_not_authorized")
    elif (
        upstream["goal_internal_continuation_gate_status"] != "passed"
        or upstream["repository_t14_02_gate_passed"]
        or upstream.get("stale_dependency")
    ):
        raise R1T1402Error("legacy_author_draft_gate_invalid")
    governance = config["governance"]
    if (
        governance["scientific_review_status"] not in {"pending", "needs_revision"}
        or governance["formal_task_completed"]
        or governance["R1-T10_allowed_to_start"]
    ):
        raise R1T1402Error("author_draft_governance_violation")


def _verify_inputs(config: Mapping[str, Any]) -> None:
    upstream = config["upstream_binding"]
    upstream_refs = [
        ("result_package_path", "result_package_sha256"),
        ("result_analysis_path", "result_analysis_sha256"),
        ("artifact_manifest_path", "artifact_manifest_sha256"),
        ("candidate_registry_path", "candidate_registry_sha256"),
    ]
    current_revision = config.get("protocol_version") in {
        "R1.v0.4.R1-T14-02.v2",
        "R1.v0.4.R1-T14-02.v3",
    }
    if current_revision:
        upstream_refs.extend(
            [
                ("handoff_manifest_path", "handoff_manifest_sha256"),
                ("external_review_path", "external_review_sha256"),
                ("final_gate_validation_path", "final_gate_validation_sha256"),
            ]
        )
    for path_key, hash_key in upstream_refs:
        path = ROOT / upstream[path_key]
        if not path.is_file() or sha256_file(path) != upstream[hash_key]:
            raise R1T1402Error(f"upstream_hash_mismatch:{path_key}")
    package = _load_json(ROOT / upstream["result_package_path"])
    if current_revision:
        if (
            package.get("repository_final_gate_status") != "passed"
            or package.get("repository_merge_status") != "pending"
            or package.get("formal_task_completed") is not False
            or package.get("R1-T14-02_allowed_to_start") is not False
        ):
            raise R1T1402Error("upstream_final_package_boundary_invalid")
        handoff = _load_json(ROOT / upstream["handoff_manifest_path"])
        review = _load_json(ROOT / upstream["external_review_path"])
        final_gate = _load_json(ROOT / upstream["final_gate_validation_path"])
        if (
            package.get("handoff_manifest_sha256")
            != upstream["handoff_manifest_sha256"]
            or handoff.get("artifact_manifest_sha256")
            != upstream["artifact_manifest_sha256"]
            or handoff.get("candidate_registry_sha256")
            != upstream["candidate_registry_sha256"]
        ):
            raise R1T1402Error("upstream_cross_file_hash_mismatch")
        if (
            review.get("external_review_status") != "passed"
            or review.get("review_comment_id") != 4943245857
            or final_gate.get("status") != "passed"
            or final_gate.get("result_package_sha256")
            != upstream["result_package_sha256"]
        ):
            raise R1T1402Error("upstream_review_or_final_gate_invalid")
        _verify_merged_commit_binding(upstream)
        _verify_superseded_run(config["superseded_run"])
        for name, artifact in config["diagnostic_reconciliation_inputs"].items():
            path = ROOT / artifact["path"]
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise R1T1402Error(f"diagnostic_input_hash_mismatch:{name}")
    else:
        gate = package.get("gate_status", {})
        if gate.get(
            "goal_internal_continuation_gate_status"
        ) != "passed" or not gate.get("goal_internal_t14_02_authorized"):
            raise R1T1402Error("upstream_internal_gate_not_passed")
        if package.get("repository_final_gate_status") != "pending" or package.get(
            "formal_task_completed"
        ):
            raise R1T1402Error("upstream_external_review_boundary_invalid")
    for name, artifact in config["input_artifacts"].items():
        path = ROOT / artifact["path"]
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise R1T1402Error(f"input_hash_mismatch:{name}")


def _verify_merged_commit_binding(upstream: Mapping[str, Any]) -> None:
    head = str(upstream.get("exact_head_commit", ""))
    merge = str(upstream.get("merge_commit", ""))
    for commit in (head, merge):
        if (
            len(commit) != 40
            or subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=ROOT,
                capture_output=True,
            ).returncode
        ):
            raise R1T1402Error("upstream_commit_object_missing")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", head, merge],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        raise R1T1402Error("upstream_head_not_merged")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", merge, "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        raise R1T1402Error("upstream_merge_not_in_current_lineage")


def _verify_superseded_run(binding: Mapping[str, Any]) -> None:
    path = ROOT / str(binding.get("supersession_path", ""))
    if not path.is_file() or sha256_file(path) != binding.get("supersession_sha256"):
        raise R1T1402Error("supersession_record_hash_mismatch")
    record = _load_json(path)
    if (
        record.get("status") != "superseded"
        or record.get("superseded_run_id") != binding.get("run_id")
        or not record.get("supersession_reasons")
    ):
        raise R1T1402Error("supersession_record_semantics_invalid")


def _attach_inputs(con: Any, config: Mapping[str, Any]) -> None:
    aliases = {
        "dimension_score": "scoredim",
        "indicator_score": "scoreind",
        "baseline_daily_confirmation": "basedaily",
        "baseline_confirmed_interval": "baseinterval",
        "r0_t15_dimension_state": "t15dim",
        "r0_t15_nested_daily_state": "t15nested",
        "r0_t15_daily_confirmation": "t15daily",
        "r0_t15_confirmed_interval": "t15interval",
    }
    for key, alias in aliases.items():
        path = ROOT / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{path.as_posix()}' AS {alias} (READ_ONLY)")


def _load_registry(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = ROOT / config["upstream_binding"]["candidate_registry_path"]
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 10 or len({row["formal_vector_id"] for row in rows}) != 10:
        raise R1T1402Error("formal_registry_must_have_exactly_10_vectors")
    if sum(_as_bool(row["baseline_reuse"]) for row in rows) != 2:
        raise R1T1402Error("formal_registry_must_have_two_baselines")
    for row in rows:
        row["W"] = int(row["W"])
        row["K"] = int(row["K"])
        for key in ("qP", "qC", "qT", "qV"):
            row[key] = float(row[key])
        row["materialize"] = _as_bool(row["materialize"])
        row["baseline_reuse"] = _as_bool(row["baseline_reuse"])
        row["selection_path_not_independently_confirmed"] = True
    return rows


def _load_robust_envelopes(
    config: Mapping[str, Any],
) -> dict[tuple[int, str, str], float]:
    artifact = config["diagnostic_reconciliation_inputs"]["t14_01_robust_envelope"]
    path = ROOT / artifact["path"]
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    envelopes: dict[tuple[int, str, str], float] = {}
    for row in rows:
        if row.get("role") != "baseline":
            continue
        key = (int(row["W"]), str(row["scope"]), str(row["metric"]))
        if key in envelopes:
            raise R1T1402Error(f"duplicate_robust_envelope:{key}")
        envelopes[key] = float(row["robust_envelope"])
    required = {
        (W, scope, metric)
        for W in (120, 250)
        for scope, metric in (
            ("S_PCT", "confirmed_coverage"),
            ("S_PCVT", "confirmed_coverage"),
            ("T_GIVEN_PC", "delta"),
            ("T_GIVEN_PC", "lift"),
            ("V_GIVEN_PCT", "delta"),
            ("V_GIVEN_PCT", "lift"),
        )
    }
    if not required.issubset(envelopes):
        missing = sorted(required - set(envelopes))
        raise R1T1402Error(f"scope_specific_robust_envelope_missing:{missing}")
    if config["robust_envelope_policy"].get("fallback_allowed") is not False:
        raise R1T1402Error("robust_envelope_fallback_must_be_disabled")
    return envelopes


def _load_base_score_data(con: Any, W: int) -> BaseScoreData:
    fields: list[str] = []
    for layer in LAYERS:
        fields.extend(
            (
                f"max(score_dimension) FILTER (WHERE dimension='{layer}') AS {layer}_score",
                f"max(score_dimension_min) FILTER (WHERE dimension='{layer}') AS {layer}_score_min",
                f"max(eligible_dimension::INTEGER) FILTER (WHERE dimension='{layer}')::TINYINT AS {layer}_eligible",
                f"max(CASE validity_status WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 WHEN 'diagnostic_required' THEN 2 WHEN 'blocked' THEN 3 ELSE 1 END) FILTER (WHERE dimension='{layer}')::TINYINT AS {layer}_status",
                f"max(hash(reason_codes)) FILTER (WHERE dimension='{layer}')::UBIGINT AS {layer}_reason_hash",
            )
        )
    arrays = con.execute(
        f"""
        WITH wide AS (
          SELECT security_id,trading_date,{",".join(fields)}
          FROM scoredim.r0_t05_dimension_score_results
          WHERE percentile_window_W=?
          GROUP BY security_id,trading_date
          HAVING count(*)=4
        ), calendar AS (
          SELECT trading_date,row_number() OVER (ORDER BY trading_date)::INTEGER AS calendar_ordinal
          FROM (SELECT DISTINCT trading_date FROM wide)
        )
        SELECT dense_rank() OVER (ORDER BY security_id)::INTEGER-1 AS security_code,
          security_id,trading_date::INTEGER AS trading_date,substr(trading_date,1,4)::INTEGER AS year,
          calendar_ordinal,{",".join(f"{layer}_score,{layer}_score_min,{layer}_eligible,{layer}_status,{layer}_reason_hash" for layer in LAYERS)}
        FROM wide JOIN calendar USING(trading_date)
        ORDER BY security_id,trading_date
        """,
        [W],
    ).fetchnumpy()
    security_code = np.asarray(arrays["security_code"], dtype=np.int32)
    year = np.asarray(arrays["year"], dtype=np.int16)
    ordinal = np.asarray(arrays["calendar_ordinal"], dtype=np.int32)
    starts, lengths, block_id, within = derive_continuous_blocks(
        security_code, year, ordinal
    )
    return BaseScoreData(
        W=W,
        security_code=security_code,
        security_id=np.asarray(arrays["security_id"], dtype=object),
        trading_date=np.asarray(arrays["trading_date"], dtype=np.int32),
        year=year,
        calendar_ordinal=ordinal,
        score={
            layer: np.asarray(arrays[f"{layer}_score"], dtype=float) for layer in LAYERS
        },
        score_min={
            layer: np.asarray(arrays[f"{layer}_score_min"], dtype=float)
            for layer in LAYERS
        },
        eligible={
            layer: np.asarray(arrays[f"{layer}_eligible"], dtype=np.int8)
            for layer in LAYERS
        },
        status={
            layer: np.asarray(arrays[f"{layer}_status"], dtype=np.int8)
            for layer in LAYERS
        },
        reason_hash={
            layer: np.asarray(arrays[f"{layer}_reason_hash"], dtype=np.uint64)
            for layer in LAYERS
        },
        block_starts=starts,
        block_lengths=lengths,
        block_id=block_id,
        within_block=within,
    )


def _candidate_from_base(base: BaseScoreData, spec: Mapping[str, Any]) -> CandidateData:
    layers: dict[str, LayerPayload] = {}
    for layer in LAYERS:
        q = float(spec[f"q{layer}"])
        valid = (
            (base.status[layer] == VALID)
            & (base.eligible[layer] == 1)
            & np.isfinite(base.score[layer])
            & np.isfinite(base.score_min[layer])
        )
        raw = np.full(len(base.security_code), RAW_NULL, dtype=np.int8)
        raw[valid] = RAW_FALSE
        raw[
            valid
            & (base.score[layer] + 1e-12 >= 1.0 - q)
            & (base.score_min[layer] + 1e-12 >= 1.0 - q - 0.1)
        ] = RAW_TRUE
        layers[layer] = LayerPayload(
            raw=raw, status=base.status[layer], reason_hash=base.reason_hash[layer]
        )
    nested_raw: dict[str, np.ndarray] = {}
    nested_status: dict[str, np.ndarray] = {}
    for state, state_layers in STATE_LAYERS.items():
        raw, status = ordered_and(
            tuple(layers[x].raw for x in state_layers),
            tuple(layers[x].status for x in state_layers),
        )
        nested_raw[state], nested_status[state] = raw, status
    return CandidateData(
        W=base.W,
        security_code=base.security_code,
        security_id=base.security_id,
        trading_date=base.trading_date,
        year=base.year,
        calendar_ordinal=base.calendar_ordinal,
        layers=layers,
        nested_raw=nested_raw,
        nested_status=nested_status,
        block_starts=base.block_starts,
        block_lengths=base.block_lengths,
        block_id=base.block_id,
        within_block=base.within_block,
    )


def _relevant_states(spec: Mapping[str, Any]) -> tuple[str, ...]:
    role = str(spec["state_line_role"])
    return tuple(state for state in ("S_PCT", "S_PCVT") if state in role)


def _state_profile(data: CandidateData, state: str) -> dict[str, Any]:
    raw = data.nested_raw[state]
    status = data.nested_status[state]
    confirmed = _confirmation_array(raw, status, data.security_code, 3)
    raw_runs = _run_records(raw, status, data)
    confirmed_runs = [record for record in raw_runs if record["raw_duration"] >= 3]
    for record in confirmed_runs:
        record["confirmed_duration"] = record["raw_duration"] - 2
        record["confirmation_date"] = int(data.trading_date[record["start_index"] + 2])
    return {
        "raw": raw,
        "status": status,
        "confirmed": confirmed,
        "raw_runs": raw_runs,
        "confirmed_runs": confirmed_runs,
        "raw_true_count": int(np.count_nonzero(raw == RAW_TRUE)),
        "confirmed_true_count": int(np.count_nonzero(confirmed == RAW_TRUE)),
        "eligible_count": int(np.count_nonzero((status == VALID) & (raw != RAW_NULL))),
        "raw_security_count": int(np.unique(data.security_code[raw == RAW_TRUE]).size),
        "confirmed_security_count": int(
            np.unique(data.security_code[confirmed == RAW_TRUE]).size
        ),
        "data": data,
    }


def _confirmation_array(
    raw: np.ndarray, status: np.ndarray, security_code: np.ndarray, K: int
) -> np.ndarray:
    result = np.full(len(raw), RAW_NULL, dtype=np.int8)
    valid = (status == VALID) & (raw != RAW_NULL)
    result[valid] = RAW_FALSE
    true_indices = np.flatnonzero((raw == RAW_TRUE) & (status == VALID))
    if not true_indices.size:
        return result
    breaks = np.ones(true_indices.size, dtype=bool)
    breaks[1:] = (true_indices[1:] != true_indices[:-1] + 1) | (
        security_code[true_indices[1:]] != security_code[true_indices[:-1]]
    )
    starts = np.flatnonzero(breaks)
    ends = np.r_[starts[1:], true_indices.size]
    for left, right in zip(starts, ends, strict=True):
        run = true_indices[left:right]
        if len(run) >= K:
            result[run[K - 1 :]] = RAW_TRUE
    return result


def _run_records(
    raw: np.ndarray, status: np.ndarray, data: CandidateData
) -> list[dict[str, Any]]:
    indices = np.flatnonzero((raw == RAW_TRUE) & (status == VALID))
    if not indices.size:
        return []
    breaks = np.ones(indices.size, dtype=bool)
    breaks[1:] = (indices[1:] != indices[:-1] + 1) | (
        data.security_code[indices[1:]] != data.security_code[indices[:-1]]
    )
    starts = np.flatnonzero(breaks)
    ends = np.r_[starts[1:], indices.size]
    records: list[dict[str, Any]] = []
    for left, right in zip(starts, ends, strict=True):
        start, end = int(indices[left]), int(indices[right - 1])
        open_interval = (
            end + 1 == len(raw)
            or data.security_code[end + 1] != data.security_code[start]
        )
        records.append(
            {
                "security_id": str(data.security_id[start]),
                "start_index": start,
                "end_index": end,
                "raw_start_date": int(data.trading_date[start]),
                "last_true_date": int(data.trading_date[end]),
                "raw_duration": end - start + 1,
                "is_open_interval": bool(open_interval),
                "cross_year": int(data.year[start]) != int(data.year[end]),
            }
        )
    return records


def _existence_rows(
    spec: Mapping[str, Any], state: str, profile: Mapping[str, Any]
) -> list[dict[str, Any]]:
    data: CandidateData = profile["data"]
    rows: list[dict[str, Any]] = []
    for level, array, count_key, security_key in (
        ("raw", profile["raw"], "raw_true_count", "raw_security_count"),
        (
            "confirmed",
            profile["confirmed"],
            "confirmed_true_count",
            "confirmed_security_count",
        ),
    ):
        mask = array == RAW_TRUE
        year_counts = [
            int(np.count_nonzero(mask & (data.year == year)))
            for year in sorted(set(data.year.tolist()))
        ]
        nonzero = [value for value in year_counts if value]
        total = sum(year_counts)
        shares = [value / total for value in nonzero] if total else []
        rows.append(
            {
                **_vector_fields(spec),
                "state_line": state,
                "analysis_level": level,
                "eligible_day_count": profile["eligible_count"],
                "state_true_day_count": profile[count_key],
                "coverage": _safe_div(profile[count_key], profile["eligible_count"]),
                "unique_security_count": profile[security_key],
                "nonzero_year_count": len(nonzero),
                "max_year_share": max(shares, default=None),
                "year_hhi": sum(value * value for value in shares) if shares else None,
                "effective_years": _safe_div(
                    1.0, sum(value * value for value in shares)
                )
                if shares
                else None,
                "selection_path_not_independently_confirmed": True,
            }
        )
    return rows


def _interval_row(
    spec: Mapping[str, Any], state: str, profile: Mapping[str, Any]
) -> dict[str, Any]:
    records = profile["confirmed_runs"]
    durations = [int(row["confirmed_duration"]) for row in records]
    return {
        **_vector_fields(spec),
        "state_line": state,
        "interval_count": len(records),
        "confirmed_day_count_from_intervals": sum(durations),
        "duration_mean": float(np.mean(durations)) if durations else None,
        "duration_median": float(np.median(durations)) if durations else None,
        "duration_q90": float(np.quantile(durations, 0.90)) if durations else None,
        "duration_q95": float(np.quantile(durations, 0.95)) if durations else None,
        "duration_max": max(durations, default=None),
        "single_day_fragment_count": sum(value == 1 for value in durations),
        "fragment_rate": _safe_div(
            sum(value == 1 for value in durations), len(durations)
        ),
        "open_interval_count": sum(bool(row["is_open_interval"]) for row in records),
        "cross_year_interval_count": sum(bool(row["cross_year"]) for row in records),
        "conservation_mismatch": sum(durations) - int(profile["confirmed_true_count"]),
        "selection_path_not_independently_confirmed": True,
    }


def _year_state_rows(
    spec: Mapping[str, Any],
    state: str,
    profile: Mapping[str, Any],
    years_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    data: CandidateData = profile["data"]
    rows = []
    total_confirmed = int(profile["confirmed_true_count"])
    for year in years_config["values"]:
        year_mask = data.year == int(year)
        raw_count = int(np.count_nonzero(year_mask & (profile["raw"] == RAW_TRUE)))
        confirmed_count = int(
            np.count_nonzero(year_mask & (profile["confirmed"] == RAW_TRUE))
        )
        rows.append(
            {
                **_vector_fields(spec),
                "profile_type": "state",
                "state_or_step": state,
                "year": int(year),
                "partial_year": int(year) in years_config["partial_years"],
                "eligible_day_count": int(
                    np.count_nonzero(year_mask & (profile["status"] == VALID))
                ),
                "raw_state_day_count": raw_count,
                "confirmed_state_day_count": confirmed_count,
                "confirmed_year_share": _safe_div(confirmed_count, total_confirmed),
                "delta": None,
                "lift": None,
                "selection_path_not_independently_confirmed": True,
            }
        )
    return rows


def _reconcile_r0_state(
    con: Any, spec: Mapping[str, Any], state: str, profile: Mapping[str, Any]
) -> dict[str, Any]:
    if spec["baseline_reuse"]:
        daily_source = "basedaily.r0_t07_daily_confirmation_results"
        interval_source = "baseinterval.r0_t07_confirmed_interval_results"
        where, params = (
            "percentile_window_W=? AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name=?",
            [int(spec["W"]), state],
        )
    else:
        daily_source = "t15daily.r0_t15_daily_confirmation_results"
        interval_source = "t15interval.r0_t15_confirmed_interval_results"
        where, params = (
            "formal_vector_id=? AND state_name=?",
            [str(spec["formal_vector_id"]), state],
        )
    upstream = con.execute(
        f"SELECT count(*) FILTER (WHERE raw_state=true),count(*) FILTER (WHERE confirmed_state=true),count(DISTINCT security_id) FILTER (WHERE confirmed_state=true) FROM {daily_source} WHERE {where}",
        params,
    ).fetchone()
    intervals = con.execute(
        f"SELECT count(*),coalesce(sum(confirmed_duration_observations),0) FROM {interval_source} WHERE {where}",
        params,
    ).fetchone()
    derived = (
        profile["raw_true_count"],
        profile["confirmed_true_count"],
        profile["confirmed_security_count"],
        len(profile["confirmed_runs"]),
        sum(int(row["confirmed_duration"]) for row in profile["confirmed_runs"]),
    )
    expected = tuple(int(value) for value in (*upstream, *intervals))
    mismatch = sum(a != b for a, b in zip(derived, expected, strict=True))
    return {
        **_vector_fields(spec),
        "state_line": state,
        "derived_raw_days": derived[0],
        "r0_raw_days": expected[0],
        "derived_confirmed_days": derived[1],
        "r0_confirmed_days": expected[1],
        "derived_security_count": derived[2],
        "r0_security_count": expected[2],
        "derived_interval_count": derived[3],
        "r0_interval_count": expected[3],
        "derived_interval_duration_sum": derived[4],
        "r0_interval_duration_sum": expected[4],
        "mismatch_count": mismatch,
        "reconciliation_status": "passed" if mismatch == 0 else "blocked_return_to_R0",
        "selection_path_not_independently_confirmed": True,
    }


def _intralayer_rows_for_window(
    con: Any, specs: Sequence[Mapping[str, Any]], W: int
) -> list[dict[str, Any]]:
    cache: dict[tuple[str, float], dict[str, Any]] = {}
    for layer, (indicator_a, indicator_b) in INDICATOR_PAIRS.items():
        q_values = sorted({float(spec[f"q{layer}"]) for spec in specs})
        values_sql = ",".join(f"({q:.12g})" for q in q_values)
        query = f"""
        WITH wide AS (
          SELECT security_id,trading_date,
            max(score) FILTER (WHERE indicator_id='{indicator_a}') AS a,
            max(score) FILTER (WHERE indicator_id='{indicator_b}') AS b,
            max(validity_status) FILTER (WHERE indicator_id='{indicator_a}') AS a_status,
            max(validity_status) FILTER (WHERE indicator_id='{indicator_b}') AS b_status
          FROM scoreind.r0_t05_indicator_score_results
          WHERE percentile_window_W=? AND indicator_id IN ('{indicator_a}','{indicator_b}')
          GROUP BY security_id,trading_date
        ), valid AS (
          SELECT *,
            rank() OVER (ORDER BY a)+(count(*) OVER (PARTITION BY a)-1)/2.0 AS rank_a,
            rank() OVER (ORDER BY b)+(count(*) OVER (PARTITION BY b)-1)/2.0 AS rank_b
          FROM wide WHERE a_status='valid' AND b_status='valid' AND a IS NOT NULL AND b IS NOT NULL
        ), qs(q) AS (VALUES {values_sql})
        SELECT q,count(*) AS N,
          count(*) FILTER (WHERE a>=1-q AND b>=1-q) AS both_hit,
          count(*) FILTER (WHERE a>=1-q AND b<1-q) AS a_only,
          count(*) FILTER (WHERE a<1-q AND b>=1-q) AS b_only,
          count(*) FILTER (WHERE a<1-q AND b<1-q) AS neither,
          corr(rank_a,rank_b) AS spearman
        FROM valid CROSS JOIN qs GROUP BY q ORDER BY q
        """
        for row in _query_dicts(con, query, [W]):
            n, both, a_only, b_only = (
                int(row[key]) for key in ("N", "both_hit", "a_only", "b_only")
            )
            cache[(layer, float(row["q"]))] = {
                "indicator_a": indicator_a,
                "indicator_b": indicator_b,
                "common_eligible_rows": n,
                "both_hit": both,
                "a_only": a_only,
                "b_only": b_only,
                "neither": int(row["neither"]),
                "A_given_B": _safe_div(both, both + b_only),
                "B_given_A": _safe_div(both, both + a_only),
                "jaccard": _safe_div(both, both + a_only + b_only),
                "continuous_score_spearman": float(row["spearman"]),
            }
    rows = []
    for spec in specs:
        for layer in LAYERS:
            q = float(spec[f"q{layer}"])
            metrics = cache[(layer, q)]
            rows.append(
                {
                    **_vector_fields(spec),
                    "layer": layer,
                    "q_dimension": q,
                    **metrics,
                    "redundancy_conflict": "redundant"
                    if metrics["jaccard"] >= 0.8
                    else "complementary"
                    if metrics["jaccard"] >= 0.4
                    else "conflict_or_sparse",
                    "threshold_response_scope": "frozen_q_and_immediate_neighbors",
                    "selection_path_not_independently_confirmed": True,
                }
            )
    return rows


def _interlayer_profiles(
    spec: Mapping[str, Any],
    data: CandidateData,
    step_id: str,
    years_config: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    parent_layers, target = STEP_SPEC[step_id]
    parent_raw, parent_status = ordered_and(
        tuple(data.layers[layer].raw for layer in parent_layers),
        tuple(data.layers[layer].status for layer in parent_layers),
    )
    target_payload = data.layers[target]
    valid = (
        (parent_status == VALID)
        & (parent_raw != RAW_NULL)
        & (target_payload.status == VALID)
        & (target_payload.raw != RAW_NULL)
    )
    parent = parent_raw == RAW_TRUE
    target_true = target_payload.raw == RAW_TRUE
    counts = _four_counts(valid, parent, target_true)
    pooled = {
        **_vector_fields(spec),
        "step_id": step_id,
        "analysis_level": "pooled",
        "group_id": "ALL",
        **_step_metrics(*counts),
        "selection_path_not_independently_confirmed": True,
    }
    grouped: list[dict[str, Any]] = []
    year_counts: dict[int, tuple[int, int, int, int]] = {}
    for year in years_config["values"]:
        mask = data.year == int(year)
        values = _four_counts(valid & mask, parent, target_true)
        year_counts[int(year)] = values
        grouped.append(
            {
                **_vector_fields(spec),
                "step_id": step_id,
                "analysis_level": "year",
                "group_id": int(year),
                **_step_metrics(*values),
                "selection_path_not_independently_confirmed": True,
            }
        )
    for code in np.unique(data.security_code):
        mask = data.security_code == code
        values = _four_counts(valid & mask, parent, target_true)
        grouped.append(
            {
                **_vector_fields(spec),
                "step_id": step_id,
                "analysis_level": "security",
                "group_id": _security_hash(
                    str(data.security_id[np.flatnonzero(mask)[0]])
                ),
                **_step_metrics(*values),
                "selection_path_not_independently_confirmed": True,
            }
        )
    loyo = []
    for year in years_config["values"]:
        values = tuple(
            counts[index] - year_counts[int(year)][index] for index in range(4)
        )
        loyo.append(
            {
                **_vector_fields(spec),
                "step_id": step_id,
                "left_out_year": int(year),
                **_step_metrics(*values),
                "selection_path_not_independently_confirmed": True,
            }
        )
    return pooled, grouped, loyo


def _four_counts(
    valid: np.ndarray, parent: np.ndarray, target: np.ndarray
) -> tuple[int, int, int, int]:
    return (
        int(np.count_nonzero(valid & parent & target)),
        int(np.count_nonzero(valid & parent & ~target)),
        int(np.count_nonzero(valid & ~parent & target)),
        int(np.count_nonzero(valid & ~parent & ~target)),
    )


def _step_metrics(n11: int, n10: int, n01: int, n00: int) -> dict[str, Any]:
    N = n11 + n10 + n01 + n00
    parent_count, target_count = n11 + n10, n11 + n01
    retention = _safe_div(n11, parent_count)
    marginal = _safe_div(target_count, N)
    nonanchor = _safe_div(n01, n01 + n00)
    parent_rate = _safe_div(parent_count, N)
    joint_rate = _safe_div(n11, N)
    expected = (
        parent_rate * marginal
        if parent_rate is not None and marginal is not None
        else None
    )
    return {
        "N": N,
        "n11": n11,
        "n10": n10,
        "n01": n01,
        "n00": n00,
        "retention": retention,
        "target_marginal": marginal,
        "lift": _safe_div(retention, marginal),
        "delta": retention - marginal
        if retention is not None and marginal is not None
        else None,
        "nonanchor_target_rate": nonanchor,
        "delta_nonanchor": retention - nonanchor
        if retention is not None and nonanchor is not None
        else None,
        "joint_rate": joint_rate,
        "independence_expected_joint_rate": expected,
        "joint_excess": joint_rate - expected
        if joint_rate is not None and expected is not None
        else None,
    }


def _denominator_reconciliation_rows(
    *,
    registry: Sequence[Mapping[str, Any]],
    step_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    inputs = config["diagnostic_reconciliation_inputs"]
    with (ROOT / inputs["t14_01_interlayer_profile"]["path"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        t14_rows = list(csv.DictReader(handle))
    with (ROOT / inputs["r1_t06_layer_step_profile"]["path"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        t06_rows = list(csv.DictReader(handle))
    t14_index = {
        (row["candidate_q_vector_id"], int(row["W"]), row["step_id"]): row
        for row in t14_rows
        if row["profile_type"] == "pooled"
    }
    t06_index = {
        (int(row["W"]), row["step_id"]): row
        for row in t06_rows
        if abs(float(row["q"]) - 0.2) < 1e-12
    }
    rows: list[dict[str, Any]] = []
    count_fields = ("n11", "n10", "n01", "n00")
    for spec in registry:
        state = (
            "S_PCT"
            if spec["request_role"] == "baseline_reference"
            else _relevant_states(spec)[0]
        )
        if spec["request_role"] == "baseline_reference":
            step = "T_GIVEN_PC"
        else:
            step = "T_GIVEN_PC" if state == "S_PCT" else "V_GIVEN_PCT"
        vector_id = str(spec["formal_vector_id"])
        diagnostic = t14_index[
            (str(spec["candidate_q_vector_id"]), int(spec["W"]), step)
        ]
        formal = step_cache[(vector_id, step)]
        shared_baseline = step_cache[(_baseline_id(int(spec["W"])), step)]
        baseline = t06_index[(int(spec["W"]), step)]
        t14_metrics = {
            "N": int(diagnostic["N"]),
            **{field: int(diagnostic[field]) for field in count_fields},
            "retention": float(diagnostic["retention"]),
            "target_marginal": float(diagnostic["target_marginal_rate"]),
            "lift": float(diagnostic["lift"]),
            "delta": float(diagnostic["delta"]),
        }
        formal_metrics = {
            "N": int(formal["N"]),
            **{field: int(formal[field]) for field in count_fields},
            "retention": float(formal["retention"]),
            "target_marginal": float(formal["target_marginal"]),
            "lift": float(formal["lift"]),
            "delta": float(formal["delta"]),
        }
        t06_metrics = {
            "N": int(baseline["N"]),
            **{field: int(baseline[field]) for field in count_fields},
            "retention": float(baseline["retention"]),
            "target_marginal": float(baseline["target_marginal_rate"]),
            "lift": float(baseline["lift"]),
            "delta": float(baseline["delta"]),
        }
        shared_baseline_metrics = {
            "N": int(shared_baseline["N"]),
            **{field: int(shared_baseline[field]) for field in count_fields},
            "retention": float(shared_baseline["retention"]),
            "target_marginal": float(shared_baseline["target_marginal"]),
            "lift": float(shared_baseline["lift"]),
            "delta": float(shared_baseline["delta"]),
        }
        count_mismatch = sum(
            t14_metrics[field] != formal_metrics[field]
            for field in ("N", *count_fields)
        )
        baseline_mismatch = sum(
            shared_baseline_metrics[field] != t06_metrics[field]
            for field in ("N", *count_fields)
        )
        baseline_parent_true_mismatch = sum(
            shared_baseline_metrics[field] != t06_metrics[field]
            for field in ("n11", "n10")
        )
        baseline_parent_false_expansion = (
            shared_baseline_metrics["n01"]
            + shared_baseline_metrics["n00"]
            - t06_metrics["n01"]
            - t06_metrics["n00"]
        )
        baseline_reconciliation_pass = (
            baseline_parent_true_mismatch == 0
            and baseline_parent_false_expansion >= 0
            and shared_baseline_metrics["n01"] >= t06_metrics["n01"]
            and shared_baseline_metrics["n00"] >= t06_metrics["n00"]
            and abs(shared_baseline_metrics["retention"] - t06_metrics["retention"])
            <= 1e-15
        )
        t14_gate = t14_metrics["delta"] > 0 and t14_metrics["lift"] > 1
        formal_gate = formal_metrics["delta"] > 0 and formal_metrics["lift"] > 1
        row = {
            **_vector_fields(spec),
            "state_line": state,
            "step_id": step,
            "t14_01_denominator_scope": "strict_required_layer_common_valid",
            "t14_02_denominator_scope": (
                "ordered_short_circuit_parent_plus_target_valid"
            ),
            "r1_t06_denominator_scope": "step_specific_minimal_common_valid",
            **{f"t14_01_{key}": value for key, value in t14_metrics.items()},
            **{f"t14_02_{key}": value for key, value in formal_metrics.items()},
            **{f"r1_t06_baseline_{key}": value for key, value in t06_metrics.items()},
            **{
                f"t14_02_shared_baseline_{key}": value
                for key, value in shared_baseline_metrics.items()
            },
            "t14_01_vs_t14_02_four_cell_mismatch_count": count_mismatch,
            "t14_02_vs_r1_t06_baseline_four_cell_mismatch_count": baseline_mismatch,
            "t14_02_vs_r1_t06_parent_true_cell_mismatch_count": (
                baseline_parent_true_mismatch
            ),
            "t14_02_vs_r1_t06_parent_false_expansion_count": (
                baseline_parent_false_expansion
            ),
            "t14_02_vs_r1_t06_retention_change": (
                shared_baseline_metrics["retention"] - t06_metrics["retention"]
            ),
            "t14_02_vs_r1_t06_baseline_reconciliation_status": (
                "passed"
                if baseline_reconciliation_pass
                else "blocked_unexplained_denominator_difference"
            ),
            "delta_change_from_denominator": (
                formal_metrics["delta"] - t14_metrics["delta"]
            ),
            "lift_change_from_denominator": (
                formal_metrics["lift"] - t14_metrics["lift"]
            ),
            "difference_source": (
                "none"
                if count_mismatch == 0
                else "ordered_short_circuit_parent_status_vs_strict_required_layer_validity"
            ),
            "baseline_difference_source": (
                "ordered_short_circuit_expands_parent_false_rows_only"
                if baseline_mismatch
                else "none"
            ),
            "affected_structural_gate_t14_01": t14_gate,
            "affected_structural_gate_t14_02": formal_gate,
            "affected_structural_gate_flip": t14_gate != formal_gate,
            "selection_path_not_independently_confirmed": True,
        }
        rows.append(row)

    for W in (120, 250):
        for state in ("S_PCT", "S_PCVT"):
            group = [
                row
                for row in rows
                if int(row["W"]) == W
                and row["state_line"] == state
                and row["request_role"] != "baseline_reference"
            ]
            t14_rank = {
                row["formal_vector_id"]: rank
                for rank, row in enumerate(
                    sorted(
                        group,
                        key=lambda item: (
                            -float(item["t14_01_delta"]),
                            str(item["formal_vector_id"]),
                        ),
                    ),
                    start=1,
                )
            }
            formal_rank = {
                row["formal_vector_id"]: rank
                for rank, row in enumerate(
                    sorted(
                        group,
                        key=lambda item: (
                            -float(item["t14_02_delta"]),
                            str(item["formal_vector_id"]),
                        ),
                    ),
                    start=1,
                )
            }
            for row in group:
                vector_id = row["formal_vector_id"]
                row["affected_delta_rank_t14_01"] = t14_rank[vector_id]
                row["affected_delta_rank_t14_02"] = formal_rank[vector_id]
                row["affected_delta_rank_flip"] = (
                    t14_rank[vector_id] != formal_rank[vector_id]
                )
    for row in rows:
        if row["request_role"] == "baseline_reference":
            row["affected_delta_rank_t14_01"] = None
            row["affected_delta_rank_t14_02"] = None
            row["affected_delta_rank_flip"] = False
    return rows


def _identity_row(
    spec: Mapping[str, Any],
    state: str,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    c = candidate["confirmed"] == RAW_TRUE
    b = baseline["confirmed"] == RAW_TRUE
    intersection, union = int(np.count_nonzero(c & b)), int(np.count_nonzero(c | b))
    c_sec = set(candidate["data"].security_id[c].tolist())
    b_sec = set(baseline["data"].security_id[b].tolist())
    c_intervals = {
        (row["security_id"], row["raw_start_date"], row["last_true_date"])
        for row in candidate["confirmed_runs"]
    }
    b_intervals = {
        (row["security_id"], row["raw_start_date"], row["last_true_date"])
        for row in baseline["confirmed_runs"]
    }
    return {
        **_vector_fields(spec),
        "state_line": state,
        "baseline_vector_id": _baseline_id(int(spec["W"])),
        "confirmed_jaccard": _safe_div(intersection, union),
        "baseline_retention": _safe_div(intersection, int(np.count_nonzero(b))),
        "candidate_novelty": _safe_div(
            int(np.count_nonzero(c & ~b)), int(np.count_nonzero(c))
        ),
        "added_day_count": int(np.count_nonzero(c & ~b)),
        "lost_day_count": int(np.count_nonzero(b & ~c)),
        "security_overlap_jaccard": _safe_div(len(c_sec & b_sec), len(c_sec | b_sec)),
        "interval_overlap_jaccard": _safe_div(
            len(c_intervals & b_intervals), len(c_intervals | b_intervals)
        ),
        "selection_path_not_independently_confirmed": True,
    }


def _run_formal_null(
    *,
    registry: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, CandidateData],
    state_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    step_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    n_perm: int,
    root_seed: int,
    run_id: str,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    values: dict[tuple[str, str], np.ndarray] = {}
    observed: dict[tuple[str, str], float] = {}
    plan_chains: dict[str, str] = {}
    family_candidates: dict[str, list[Mapping[str, Any]]] = {}
    for family, (state, role, parent_layers, shifted_layers) in FAMILY_SPEC.items():
        family_candidates[family] = []
        for W in (120, 250):
            specs = _family_specs(registry, W, state)
            family_candidates[family].extend(specs)
            base_data = candidates[str(_baseline_spec(registry, W)["formal_vector_id"])]
            parent_raw, parent_status = ordered_and(
                tuple(base_data.layers[x].raw for x in parent_layers),
                tuple(base_data.layers[x].status for x in parent_layers),
            )
            parent = np.flatnonzero((parent_raw == RAW_TRUE) & (parent_status == VALID))
            for spec in specs:
                vector_id = str(spec["formal_vector_id"])
                values[(family, vector_id)] = np.empty(n_perm, dtype=float)
                if role == "global":
                    observed[(family, vector_id)] = float(
                        state_cache[(vector_id, state)]["confirmed_true_count"]
                    ) / len(base_data.security_code)
                else:
                    step_id = {
                        "F3_C_GIVEN_P": "C_GIVEN_P",
                        "F4_T_GIVEN_PC": "T_GIVEN_PC",
                        "F5_V_GIVEN_PCT": "V_GIVEN_PCT",
                    }[family]
                    observed[(family, vector_id)] = float(
                        step_cache[(vector_id, step_id)]["retention"]
                    )
            chain = hashlib.sha256()
            for replicate_id in range(1, n_perm + 1):
                sources: dict[str, np.ndarray] = {}
                plans: list[tuple[str, np.ndarray]] = []
                for layer in shifted_layers:
                    seed = derived_seed(
                        root_seed, f"W{W}_{family}", family, replicate_id, layer
                    )
                    offsets = deterministic_offsets(base_data.block_lengths, seed)
                    plans.append((layer, offsets))
                    sources[layer] = shifted_source_indices(
                        parent,
                        base_data.block_starts,
                        base_data.block_lengths,
                        base_data.block_id,
                        base_data.within_block,
                        offsets,
                    )
                chain.update(bytes.fromhex(offset_plan_hash(plans)))
                for spec in specs:
                    vector_id = str(spec["formal_vector_id"])
                    data = candidates[vector_id]
                    if role == "global":
                        active = np.ones(len(parent), dtype=bool)
                        for layer in shifted_layers:
                            payload = data.layers[layer]
                            source = sources[layer]
                            active &= (payload.raw[source] == RAW_TRUE) & (
                                payload.status[source] == VALID
                            )
                        values[(family, vector_id)][replicate_id - 1] = (
                            _confirmed_coverage_fast(
                                parent[active],
                                data.security_code,
                                len(data.security_code),
                                3,
                            )
                        )
                    else:
                        layer = shifted_layers[0]
                        payload = data.layers[layer]
                        source = sources[layer]
                        metrics = nested_retention_metrics(
                            parent, payload.raw[source], payload.status[source]
                        )
                        values[(family, vector_id)][replicate_id - 1] = float(
                            metrics["nested_retention"]
                        )
                if replicate_id % max(1, min(250, n_perm)) == 0:
                    _heartbeat(
                        run_id,
                        "formal_null",
                        family=family,
                        W=W,
                        replicate_id=replicate_id,
                        N_perm=n_perm,
                    )
            plan_chains[f"{family}_W{W}"] = chain.hexdigest()
    null_rows: list[dict[str, Any]] = []
    multiplicity_rows: list[dict[str, Any]] = []
    family_max_rows: list[dict[str, Any]] = []
    for family, specs in family_candidates.items():
        stats: dict[str, tuple[float, float, float]] = {}
        for spec in specs:
            vector_id = str(spec["formal_vector_id"])
            array = values[(family, vector_id)]
            mean, sd, obs = (
                float(np.mean(array)),
                float(np.std(array, ddof=1)),
                observed[(family, vector_id)],
            )
            if not math.isfinite(sd) or sd == 0:
                raise R1T1402Error(f"null_sd_zero:{family}:{vector_id}")
            stats[vector_id] = (mean, sd, obs)
        matrix = np.vstack(
            [
                (
                    values[(family, str(spec["formal_vector_id"]))]
                    - stats[str(spec["formal_vector_id"])][0]
                )
                / stats[str(spec["formal_vector_id"])][1]
                for spec in specs
            ]
        )
        maxima = np.max(matrix, axis=0)
        for replicate_id, maximum in enumerate(maxima, 1):
            family_max_rows.append(
                {
                    "family_id": family,
                    "replicate_id": replicate_id,
                    "N_perm": n_perm,
                    "family_candidate_count": len(specs),
                    "max_studentized_statistic": float(maximum),
                    "selection_path_not_independently_confirmed": True,
                }
            )
        for spec in specs:
            vector_id = str(spec["formal_vector_id"])
            array = values[(family, vector_id)]
            mean, sd, obs = stats[vector_id]
            z_observed = (obs - mean) / sd
            n_extreme = int(np.count_nonzero(array >= obs))
            n_family_extreme = int(np.count_nonzero(maxima >= z_observed))
            common = {
                **_vector_fields(spec),
                "family_id": family,
                "N_perm": n_perm,
                "primary_statistic": "confirmed_coverage"
                if FAMILY_SPEC[family][1] == "global"
                else "nested_retention",
                "observed_value": obs,
                "null_mean": mean,
                "null_sd": sd,
                "joint_lift": _safe_div(obs, mean),
                "joint_excess": obs - mean,
                "z_observed": z_observed,
                "empirical_p": (n_extreme + 1) / (n_perm + 1),
                "family_adjusted_p": (n_family_extreme + 1) / (n_perm + 1),
                "n_extreme": n_extreme,
                "n_family_extreme": n_family_extreme,
                "selection_path_not_independently_confirmed": True,
            }
            null_rows.append(common)
            multiplicity_rows.append(
                {
                    **common,
                    "family_candidate_count": len(specs),
                    "multiplicity_method": "studentized_family_max_statistic_common_replicate_schedule",
                    "null_status": "passed",
                }
            )
    manifest = {
        "task_id": TASK_ID,
        "N_perm": n_perm,
        "p_floor": 1 / (n_perm + 1),
        "family_count": len(FAMILY_SPEC),
        "candidate_replicate_value_count": sum(len(array) for array in values.values()),
        "family_max_row_count": len(family_max_rows),
        "full_candidate_replicates_committed": False,
        "representation": "aggregate_null_results_plus_complete_family_max_sequence_and_offset_plan_chain_hashes",
        "common_schedule_scope": "same replicate id shared across W120,W250,baseline,centers,neighbors within family",
        "offset_plan_chain_sha256": plan_chains,
        "selection_path_not_independently_confirmed": True,
    }
    return null_rows, family_max_rows, multiplicity_rows, manifest


def _confirmed_coverage_fast(
    indices: np.ndarray, security_code: np.ndarray, eligible_count: int, K: int
) -> float:
    if not indices.size:
        return 0.0
    breaks = np.ones(indices.size, dtype=bool)
    breaks[1:] = (indices[1:] != indices[:-1] + 1) | (
        security_code[indices[1:]] != security_code[indices[:-1]]
    )
    starts = np.flatnonzero(breaks)
    ends = np.r_[starts[1:], indices.size]
    lengths = ends - starts
    confirmed = int(np.maximum(lengths - K + 1, 0).sum())
    return confirmed / eligible_count


def _family_specs(
    registry: Sequence[Mapping[str, Any]], W: int, state: str
) -> list[Mapping[str, Any]]:
    rows = [
        row
        for row in registry
        if int(row["W"]) == W and state in str(row["state_line_role"])
    ]
    if len(rows) != 3:
        raise R1T1402Error(
            f"family_registry_must_have_baseline_center_neighbor:W{W}:{state}"
        )
    return sorted(rows, key=lambda row: str(row["candidate_q_vector_id"]))


def _neighborhood_rows(
    registry: Sequence[Mapping[str, Any]],
    state_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    step_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    multiplicity: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    p_index = {(row["family_id"], row["formal_vector_id"]): row for row in multiplicity}
    rows = []
    for center in (row for row in registry if row["request_role"] == "center"):
        state = "S_PCT" if "S_PCT" in str(center["state_line_role"]) else "S_PCVT"
        neighbor = next(
            row
            for row in registry
            if row["request_role"] == "immediate_neighbor"
            and row["center_id"] == center["center_id"]
        )
        family = "F1_GLOBAL_PCT" if state == "S_PCT" else "F2_GLOBAL_PCVT"
        nested_family = "F4_T_GIVEN_PC" if state == "S_PCT" else "F5_V_GIVEN_PCT"
        center_global, neighbor_global = (
            p_index[(family, center["formal_vector_id"])],
            p_index[(family, neighbor["formal_vector_id"])],
        )
        center_nested, neighbor_nested = (
            p_index[(nested_family, center["formal_vector_id"])],
            p_index[(nested_family, neighbor["formal_vector_id"])],
        )
        direction = all(
            float(row["joint_excess"]) > 0
            for row in (center_global, neighbor_global, center_nested, neighbor_nested)
        )
        neighbor_pass = (
            float(neighbor_global["family_adjusted_p"]) <= 0.05
            and float(neighbor_nested["family_adjusted_p"]) <= 0.05
        )
        rows.append(
            {
                **_vector_fields(center),
                "state_line": state,
                "neighbor_vector_id": neighbor["formal_vector_id"],
                "center_neighbor_global_excess_direction_consistent": direction,
                "center_neighbor_nested_excess_direction_consistent": direction,
                "neighbor_non_degenerate": state_cache[
                    (neighbor["formal_vector_id"], state)
                ]["confirmed_true_count"]
                > 0,
                "neighbor_adjusted_null_pass": neighbor_pass,
                "isolated_peak_warning": not neighbor_pass,
                "neighborhood_status": "passed"
                if direction and neighbor_pass
                else "isolated_peak_warning",
                "selection_path_not_independently_confirmed": True,
            }
        )
    return rows


def _dominance_rows(
    registry: Sequence[Mapping[str, Any]],
    state_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    step_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    identity_rows: Sequence[Mapping[str, Any]],
    robust_envelopes: Mapping[tuple[int, str, str], float],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    identity_index = {
        (row["formal_vector_id"], row["state_line"]): row for row in identity_rows
    }
    rows = []
    envelope_source = config["diagnostic_reconciliation_inputs"][
        "t14_01_robust_envelope"
    ]
    for spec in (row for row in registry if not row["baseline_reuse"]):
        state = _relevant_states(spec)[0]
        baseline = _baseline_spec(registry, int(spec["W"]))
        candidate_profile, baseline_profile = (
            state_cache[(spec["formal_vector_id"], state)],
            state_cache[(baseline["formal_vector_id"], state)],
        )
        step = "T_GIVEN_PC" if state == "S_PCT" else "V_GIVEN_PCT"
        c_step, b_step = (
            step_cache[(spec["formal_vector_id"], step)],
            step_cache[(baseline["formal_vector_id"], step)],
        )
        c_cov = (
            candidate_profile["confirmed_true_count"]
            / candidate_profile["eligible_count"]
        )
        b_cov = (
            baseline_profile["confirmed_true_count"]
            / baseline_profile["eligible_count"]
        )
        improvements = {
            "coverage": c_cov - b_cov,
            "delta": float(c_step["delta"]) - float(b_step["delta"]),
            "lift_excess": (float(c_step["lift"]) - 1) - (float(b_step["lift"]) - 1),
        }
        envelope = {
            "coverage": robust_envelopes[(int(spec["W"]), state, "confirmed_coverage")],
            "delta": robust_envelopes[(int(spec["W"]), step, "delta")],
            "lift_excess": robust_envelopes[(int(spec["W"]), step, "lift")],
        }
        material_improvement = any(
            improvements[key] > envelope[key] for key in improvements
        )
        material_degradation = any(
            improvements[key] < -envelope[key] for key in improvements
        )
        beyond = material_improvement or material_degradation
        baseline_dominates = not material_improvement and material_degradation
        equivalent = not beyond
        rows.append(
            {
                **_vector_fields(spec),
                "state_line": state,
                "baseline_vector_id": baseline["formal_vector_id"],
                "confirmed_coverage_change": improvements["coverage"],
                "affected_delta_change": improvements["delta"],
                "affected_lift_excess_change": improvements["lift_excess"],
                "confirmed_coverage_robust_envelope": envelope["coverage"],
                "affected_delta_robust_envelope": envelope["delta"],
                "affected_lift_excess_robust_envelope": envelope["lift_excess"],
                "robust_envelope_source_path": envelope_source["path"],
                "robust_envelope_source_sha256": envelope_source["sha256"],
                "robust_envelope_source_policy": (
                    "R1-T14-01_scope_specific_max_LOYO_MAD_fallback"
                ),
                "material_improvement": material_improvement,
                "material_degradation": material_degradation,
                "confirmed_jaccard": identity_index[(spec["formal_vector_id"], state)][
                    "confirmed_jaccard"
                ],
                "improvement_beyond_stability_envelope": beyond,
                "baseline_dominates": baseline_dominates,
                "complexity_not_justified": not material_improvement,
                "prefer_shared_q": not material_improvement,
                "dominance_status": "baseline_dominates"
                if baseline_dominates
                else "stability_envelope_equivalent"
                if equivalent
                else "tradeoff_not_dominated",
                "selection_path_not_independently_confirmed": True,
            }
        )
    return rows


def _decision_rows(
    registry: Sequence[Mapping[str, Any]],
    state_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    step_cache: Mapping[tuple[str, str], Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    multiplicity: Sequence[Mapping[str, Any]],
    year_rows: Sequence[Mapping[str, Any]],
    loyo_rows: Sequence[Mapping[str, Any]],
    neighborhood: Sequence[Mapping[str, Any]],
    dominance: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    p = {(row["family_id"], row["formal_vector_id"]): row for row in multiplicity}
    n = {row["formal_vector_id"]: row for row in neighborhood}
    d = {row["formal_vector_id"]: row for row in dominance}
    thresholds = config["formal_thresholds"]
    rows = []
    for spec in registry:
        if spec["baseline_reuse"]:
            continue
        vector_id = spec["formal_vector_id"]
        state = _relevant_states(spec)[0]
        baseline = _baseline_spec(registry, int(spec["W"]))
        baseline_id = baseline["formal_vector_id"]
        if state == "S_PCT":
            family_members = (
                ("F1_GLOBAL_PCT", vector_id),
                ("F3_C_GIVEN_P", vector_id),
                ("F4_T_GIVEN_PC", vector_id),
            )
            affected_step = "T_GIVEN_PC"
        else:
            parent = next(
                row
                for row in registry
                if row["candidate_q_vector_id"] == spec["same_parameter_parent_id"]
            )
            parent_id = parent["formal_vector_id"]
            family_members = (
                ("F1_GLOBAL_PCT", parent_id),
                ("F3_C_GIVEN_P", parent_id),
                ("F4_T_GIVEN_PC", parent_id),
                ("F2_GLOBAL_PCVT", vector_id),
                ("F5_V_GIVEN_PCT", vector_id),
            )
            affected_step = "V_GIVEN_PCT"
        null_pass = all(
            float(p[(family, member_id)]["joint_lift"]) > 1
            and float(p[(family, member_id)]["joint_excess"]) > 0
            and float(p[(family, member_id)]["family_adjusted_p"])
            <= thresholds["family_adjusted_p_max"]
            for family, member_id in family_members
        )
        v_nested_formal_pass = state != "S_PCVT" or (
            float(p[("F5_V_GIVEN_PCT", vector_id)]["joint_lift"]) > 1
            and float(p[("F5_V_GIVEN_PCT", vector_id)]["joint_excess"]) > 0
            and float(p[("F5_V_GIVEN_PCT", vector_id)]["family_adjusted_p"])
            <= thresholds["family_adjusted_p_max"]
        )
        max_year = max(
            (
                float(row["confirmed_year_share"])
                for row in year_rows
                if row["formal_vector_id"] == vector_id
                and row["state_or_step"] == state
                and row["confirmed_year_share"] not in (None, "")
            ),
            default=0.0,
        )
        loyo_values = [
            row
            for row in loyo_rows
            if row["formal_vector_id"] == vector_id and row["step_id"] == affected_step
        ]
        loyo_stable = bool(loyo_values) and all(
            float(row["delta"]) > 0 and float(row["lift"]) > 1
            for row in loyo_values
            if row["delta"] is not None and row["lift"] is not None
        )
        neighborhood_pass = n.get(vector_id, {}).get("neighborhood_status") == "passed"
        complexity_pass = not d.get(vector_id, {}).get("complexity_not_justified", True)
        affected_rows = [
            row
            for row in interlayer_rows
            if row["formal_vector_id"] == vector_id and row["step_id"] == affected_step
        ]
        year_delta = [
            float(row["delta"])
            for row in affected_rows
            if row["analysis_level"] == "year" and row["delta"] is not None
        ]
        security_delta = [
            float(row["delta"])
            for row in affected_rows
            if row["analysis_level"] == "security" and row["delta"] is not None
        ]
        pooled_delta = float(step_cache[(vector_id, affected_step)]["delta"])
        security_median_delta = (
            float(np.median(security_delta)) if security_delta else None
        )
        security_negative_delta_share = _safe_div(
            sum(value < 0 for value in security_delta), len(security_delta)
        )
        pooled_security_reversal = security_median_delta is None or _sign(
            pooled_delta
        ) != _sign(security_median_delta)
        year_delta_conflict = any(
            _sign(value) != _sign(pooled_delta) for value in year_delta
        )
        parent_child_raw_violations = int(
            np.count_nonzero(
                (state_cache[(vector_id, "S_PCVT")]["raw"] == RAW_TRUE)
                & (state_cache[(vector_id, "S_PCT")]["raw"] != RAW_TRUE)
            )
        )
        parent_child_confirmed_violations = int(
            np.count_nonzero(
                (state_cache[(vector_id, "S_PCVT")]["confirmed"] == RAW_TRUE)
                & (state_cache[(vector_id, "S_PCT")]["confirmed"] != RAW_TRUE)
            )
        )
        same_parent = (
            parent_child_raw_violations == 0 and parent_child_confirmed_violations == 0
        )
        if state == "S_PCVT":
            candidate_ratio = _safe_div(
                state_cache[(vector_id, "S_PCVT")]["confirmed_true_count"],
                state_cache[(vector_id, "S_PCT")]["confirmed_true_count"],
            )
            baseline_ratio = _safe_div(
                state_cache[(baseline_id, "S_PCVT")]["confirmed_true_count"],
                state_cache[(baseline_id, "S_PCT")]["confirmed_true_count"],
            )
            selectivity_retained = _v_selectivity_retained(
                candidate_ratio, baseline_ratio
            )
            candidate_ratio_lt_one = candidate_ratio is not None and candidate_ratio < 1
            v_selectivity_guard_pass = (
                selectivity_retained is not None
                and selectivity_retained >= thresholds["v_selectivity_retained_min"]
                and candidate_ratio_lt_one
                and v_nested_formal_pass
                and same_parent
            )
        else:
            candidate_ratio = None
            baseline_ratio = None
            selectivity_retained = None
            candidate_ratio_lt_one = True
            v_selectivity_guard_pass = True
        ratio_scope = "confirmed_state_days" if state == "S_PCVT" else None
        try:
            warning_codes = list(json.loads(str(spec.get("warnings", "[]"))))
        except json.JSONDecodeError as exc:
            raise R1T1402Error("candidate_warning_payload_invalid") from exc
        security_heterogeneity_warning = (
            state == "S_PCVT"
            and security_negative_delta_share is not None
            and security_negative_delta_share
            > thresholds["security_negative_delta_share_warning_min_exclusive"]
        )
        if security_heterogeneity_warning:
            warning_codes.append("V_security_negative_delta_share_material")
        warning_codes = sorted(set(str(value) for value in warning_codes))
        if (
            not null_pass
            or max_year > thresholds["max_year_share"]
            or not loyo_stable
            or year_delta_conflict
            or pooled_security_reversal
            or not same_parent
            or not v_selectivity_guard_pass
        ):
            status = "do_not_advance"
        elif not neighborhood_pass or not complexity_pass:
            status = "review_only"
        elif warning_codes:
            status = "formal_structure_supported_with_warning"
        else:
            status = "formal_structure_supported"
        rows.append(
            {
                **_vector_fields(spec),
                "state_line": state,
                "global_and_nested_adjusted_null_pass": null_pass,
                "max_year_share": max_year,
                "year_gate_pass": max_year <= thresholds["max_year_share"],
                "year_level_delta_conflict": year_delta_conflict,
                "loyo_direction_stable": loyo_stable,
                "pooled_delta": pooled_delta,
                "security_median_delta": security_median_delta,
                "security_negative_delta_share": security_negative_delta_share,
                "security_heterogeneity_warning": security_heterogeneity_warning,
                "candidate_warning_codes": json.dumps(
                    warning_codes, ensure_ascii=False, separators=(",", ":")
                ),
                "pooled_security_sign_reversal": pooled_security_reversal,
                "parent_child_raw_violation_count": parent_child_raw_violations,
                "parent_child_confirmed_violation_count": parent_child_confirmed_violations,
                "parent_child_gate_pass": same_parent,
                "neighborhood_gate_pass": neighborhood_pass,
                "complexity_return_gate_pass": complexity_pass,
                "v_candidate_pcvt_pct_ratio": candidate_ratio,
                "v_baseline_pcvt_pct_ratio": baseline_ratio,
                "v_ratio_scope": ratio_scope,
                "v_selectivity_retained": selectivity_retained,
                "v_candidate_ratio_lt_one": candidate_ratio_lt_one,
                "v_nested_formal_pass": v_nested_formal_pass,
                "v_selectivity_guard_pass": v_selectivity_guard_pass,
                "candidate_status": status,
                "R1_T10_positive_handoff_recommended": status
                in {
                    "formal_structure_supported",
                    "formal_structure_supported_with_warning",
                },
                "selection_path_not_independently_confirmed": True,
                "scientific_review_status": config["governance"][
                    "scientific_review_status"
                ],
                "formal_task_completed": False,
            }
        )
    return rows


def _anomaly_scan(
    run_id: str,
    code_commit: str,
    registry: Sequence[Mapping[str, Any]],
    reconciliation: Sequence[Mapping[str, Any]],
    existence: Sequence[Mapping[str, Any]],
    intervals: Sequence[Mapping[str, Any]],
    null_results: Sequence[Mapping[str, Any]],
    multiplicity: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    denominator_reconciliation: Sequence[Mapping[str, Any]],
    dominance: Sequence[Mapping[str, Any]],
    n_perm: int,
) -> dict[str, Any]:
    checks = [
        _check(
            "exact_frozen_registry",
            len(registry) == 10
            and sum(not row["baseline_reuse"] for row in registry) == 8,
        ),
        _check(
            "r0_lineage_reconciliation",
            all(int(row["mismatch_count"]) == 0 for row in reconciliation),
        ),
        _check(
            "nondegenerate_states",
            all(
                int(row["state_true_day_count"]) > 0
                and int(row["state_true_day_count"]) < int(row["eligible_day_count"])
                for row in existence
            ),
        ),
        _check(
            "interval_conservation",
            all(int(row["conservation_mismatch"]) == 0 for row in intervals),
        ),
        _check("formal_N_perm", n_perm == 10000),
        _check(
            "five_complete_families",
            len(null_results) == 30
            and {row["family_id"] for row in null_results} == set(FAMILY_SPEC),
        ),
        _check(
            "null_sd_nonzero", all(float(row["null_sd"]) > 0 for row in null_results)
        ),
        _check(
            "multiplicity_complete",
            len(multiplicity) == 30
            and all(0 < float(row["family_adjusted_p"]) <= 1 for row in multiplicity),
        ),
        _check(
            "parent_child_geometry",
            all(
                int(row["parent_child_raw_violation_count"]) == 0
                and int(row["parent_child_confirmed_violation_count"]) == 0
                for row in decisions
            ),
        ),
        _check(
            "scope_specific_robust_envelope",
            len(dominance) == 8
            and all(
                row["robust_envelope_source_sha256"]
                == "a97c094de3b1a78564a2404721ec1ddd69ad0f1646f3e0396fc0d46a1bad2940"
                and (
                    bool(row["material_improvement"])
                    or bool(row["complexity_not_justified"])
                )
                for row in dominance
            ),
        ),
        _check(
            "denominator_reconciliation_complete",
            len(denominator_reconciliation) == 10
            and all(
                row["t14_02_vs_r1_t06_baseline_reconciliation_status"] == "passed"
                and not bool(row["affected_structural_gate_flip"])
                for row in denominator_reconciliation
            ),
        ),
        _check(
            "v_selectivity_guard",
            all(
                bool(row["v_selectivity_guard_pass"])
                for row in decisions
                if row["state_line"] == "S_PCVT"
            ),
        ),
        _check(
            "v_security_heterogeneity_warning_preserved",
            all(
                float(row["security_negative_delta_share"]) <= 0
                or bool(row["security_heterogeneity_warning"])
                for row in decisions
                if row["state_line"] == "S_PCVT" and row["request_role"] == "center"
            ),
        ),
        _check(
            "selection_limitation_propagated",
            all(
                _as_bool(row["selection_path_not_independently_confirmed"])
                for row in (*registry, *null_results, *decisions)
            ),
        ),
        _check(
            "repository_gate_closed",
            all(
                not _as_bool(row["formal_task_completed"])
                and row["scientific_review_status"] in {"pending", "needs_revision"}
                for row in decisions
            ),
        ),
    ]
    blocking = [row["check_id"] for row in checks if row["status"] != "passed"]
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": "passed" if not blocking else "blocked",
        "checks": checks,
        "blocking_findings": blocking,
        "unresolved_findings": blocking,
        "selection_path_not_independently_confirmed": True,
    }


def _experiment_summary(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    n_perm: int,
    elapsed: float,
) -> dict[str, Any]:
    outputs = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            outputs[path.name] = {
                "path": _rel(path),
                "sha256": sha256_file(path),
                "row_count": _row_count(path),
            }
    return {
        "task_id": TASK_ID,
        "stage": "R1",
        "task_class": config["task_class"],
        "run_id": run_id,
        "code_commit": code_commit,
        "config_path": _rel(config_path),
        "config_sha256": sha256_file(config_path),
        "upstream_binding": config["upstream_binding"],
        "superseded_run": config.get("superseded_run"),
        "diagnostic_reconciliation_inputs": config.get(
            "diagnostic_reconciliation_inputs"
        ),
        "robust_envelope_policy": config.get("robust_envelope_policy"),
        "denominator_reconciliation_policy": config.get(
            "denominator_reconciliation_policy"
        ),
        "N_perm": n_perm,
        "selection_path_not_independently_confirmed": True,
        "runtime_dependencies": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "duckdb": _dependency_version("duckdb"),
        },
        "elapsed_seconds": elapsed,
        "output_paths": outputs,
        "scientific_review_status": config["governance"]["scientific_review_status"],
        "review_phase": config["governance"]["review_phase"],
        "independent_review_status": config["governance"]["independent_review_status"],
        "downstream_gate_allowed": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "formal_task_completed": False,
        "status": "completed",
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def _baseline_spec(registry: Sequence[Mapping[str, Any]], W: int) -> Mapping[str, Any]:
    return next(
        row for row in registry if int(row["W"]) == W and bool(row["baseline_reuse"])
    )


def _baseline_id(W: int) -> str:
    return "R0T15_df8773397c1c94724915" if W == 120 else "R0T15_d0211154bb6ed83d5fb1"


def _vector_fields(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: spec[key]
        for key in (
            "formal_vector_id",
            "candidate_q_vector_id",
            "W",
            "K",
            "qP",
            "qC",
            "qT",
            "qV",
            "request_role",
            "archetype",
            "center_id",
        )
    }


def _check(check_id: str, passed: bool) -> dict[str, str]:
    return {"check_id": check_id, "status": "passed" if passed else "blocked"}


def _safe_div(left: Any, right: Any) -> float | None:
    if left is None or right in (None, 0):
        return None
    return float(left) / float(right)


def _v_selectivity_retained(
    candidate_ratio: float | None, baseline_ratio: float | None
) -> float | None:
    if candidate_ratio is None or baseline_ratio is None:
        return None
    return _safe_div(1 - candidate_ratio, 1 - baseline_ratio)


def _sign(value: float, tolerance: float = 1e-12) -> str:
    if value > tolerance:
        return "positive"
    if value < -tolerance:
        return "negative"
    return "zero"


def _security_hash(security_id: str) -> str:
    return (
        "security_sha256_"
        + hashlib.sha256(security_id.encode("utf-8")).hexdigest()[:20]
    )


def _as_bool(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _count_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row[key])] += 1
    return dict(result)


def _query_dicts(
    con: Any, query: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    cursor = con.execute(query, params or [])
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _heartbeat(run_id: str, phase: str, **fields: Any) -> None:
    print(
        canonical_json(
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "phase": phase,
                "heartbeat_at_utc": datetime.now(UTC).isoformat(),
                **fields,
            }
        ),
        flush=True,
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict | list | tuple):
        return canonical_json(value)
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _row_count(path: Path) -> int:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    return 1


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _dependency_version(name: str) -> str:
    module = __import__(name)
    return str(getattr(module, "__version__", "unknown"))


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
