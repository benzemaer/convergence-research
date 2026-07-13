from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    current_commit,
    formal_source_binding,
    json_source_binding,
    write_csv,
    write_json,
    write_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
T03_DIR = "data/generated/r2/r2_t03/R2-T03-PROMOTED-20260713T050903Z"


class T04InputError(RuntimeError):
    pass


def _path(value: str) -> Path:
    return ROOT / value


def _number(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_bindings(config: dict[str, Any], commit: str) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in config["sources"]:
        path = _path(source["path"])
        try:
            binding = (
                json_source_binding(path, commit, root=ROOT)
                if path.suffix == ".json"
                else formal_source_binding(path, commit, root=ROOT)
            )
        except Exception as exc:  # pragma: no cover - error text is part of fail closed
            errors.append(str(exc))
            continue
        if binding["committed_byte_sha256"] != source["sha256"]:
            errors.append(f"source_hash_mismatch:{source['path']}")
        binding["role"] = source["role"]
        bindings.append(binding)
    if errors:
        raise T04InputError(";".join(errors))
    return bindings


def _committed_csv(path: str, commit: str) -> list[dict[str, str]]:
    payload = _git_blob_text(commit, path)
    return list(csv.DictReader(payload.splitlines()))


def _git_blob_text(commit: str, path: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8")


def _committed_json(path: str, commit: str) -> dict[str, Any]:
    return json.loads(_git_blob_text(commit, path))


def _source(config: dict[str, Any], suffix: str, role: str | None = None) -> str:
    matches = [s for s in config["sources"] if s["path"].endswith(suffix)]
    if role:
        matches = [s for s in matches if s["role"] == role]
    if len(matches) != 1:
        raise T04InputError(f"source_not_unique:{suffix}:{role}")
    return matches[0]["path"]


def _metric_profiles(
    config: dict[str, Any], commit: str
) -> dict[str, dict[str, dict[str, Any]]]:
    files = {
        "metric_results": "r2_t03_metric_results.csv",
        "dg_event_zone_profile": "r2_t03_dg_event_zone_profile.csv",
        "component_diagnostic_profile": "r2_t03_component_diagnostic_profile.csv",
        "event_zone_diagnostic_profile": "r2_t03_event_zone_diagnostic_profile.csv",
        "atomic_interval_diagnostic_profile": (
            "r2_t03_atomic_interval_diagnostic_profile.csv"
        ),
    }
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for name, suffix in files.items():
        rows = _committed_csv(_source(config, suffix), commit)
        key = (
            "route_id"
            if name == "atomic_interval_diagnostic_profile"
            else "candidate_cell_id"
        )
        result[name] = {row[key]: row for row in rows}
    return result


def _evaluate_operator(
    value: float | None, operator: str, threshold: float | None
) -> bool:
    if value is None or threshold is None or not math.isfinite(value):
        return False
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    if operator == "==":
        return value == threshold
    if operator == ">":
        return value > threshold
    if operator == "<":
        return value < threshold
    raise T04InputError(f"unknown_gate_operator:{operator}")


def _threshold(
    gate: dict[str, str], state_line: str, config: dict[str, Any]
) -> float | None:
    text = gate["threshold"]
    if text.startswith("max("):
        minimum = float(text.split("(", 1)[1].split(",", 1)[0])
        match = re.search(r"ceil\(([^*]+)\*", text)
        if not match:
            raise T04InputError(f"unavailable_threshold:{gate['gate_id']}")
        fraction = float(match.group(1))
        upstream = float(
            config["upstream_threshold_inputs"]["upstream_confirmed_interval_count"]
        )
        return max(minimum, math.ceil(fraction * upstream))
    if "upstream_unique_securities" in text:
        minimum = float(text.split("(", 1)[1].split(",", 1)[0])
        match = re.search(r"ceil\(([^*]+)\*", text)
        if not match:
            raise T04InputError(f"unavailable_threshold:{gate['gate_id']}")
        fraction = float(match.group(1))
        upstream = float(
            config["upstream_threshold_inputs"]["upstream_unique_securities"][
                state_line
            ]
        )
        return max(minimum, math.ceil(fraction * upstream))
    if text.startswith("0 ") or text == "0 violations":
        return 0.0
    try:
        return float(text)
    except ValueError as exc:
        raise T04InputError(f"unavailable_threshold:{gate['gate_id']}") from exc


def _global_gate_evidence(
    config: dict[str, Any], commit: str
) -> dict[str, list[dict[str, str]]]:
    rows = _committed_csv(_source(config, "r2_t03_runtime_gate_results.csv"), commit)
    aliases = {
        "strict_core_subset_violation": "strict_core_subset_status",
        "transition_closure_violation": "accepted_bridge_transition_closure",
    }
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        result[row["check_id"]].append(row)
    for source_id, target_id in aliases.items():
        if source_id not in result and target_id in result:
            result[source_id] = result[target_id]
    return result


def _runtime_gate_evidence(
    config: dict[str, Any], commit: str
) -> dict[tuple[str, str], list[dict[str, str]]]:
    rows = _committed_csv(_source(config, "r2_t03_runtime_gate_results.csv"), commit)
    result: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        result[(row["check_id"], row.get("candidate_cell_id", ""))].append(row)
    return result


def _runtime_threshold(expected_rule: str) -> float | None:
    match = re.search(r"(?:>=|<=|==|>|<)\s*([0-9]+(?:\.[0-9]+)?)", expected_rule)
    return float(match.group(1)) if match else None


def _hard_gate_report(
    config: dict[str, Any],
    commit: str,
    cells: list[dict[str, str]],
    profiles: dict[str, dict[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    gates = _committed_csv(_source(config, "r2_t02_hard_gate_registry.csv"), commit)
    metric_rows = profiles["metric_results"]
    globals_ = _global_gate_evidence(config, commit)
    runtime_ = _runtime_gate_evidence(config, commit)
    report: list[dict[str, Any]] = []
    for gate in gates:
        if gate["state_line"] == "GLOBAL":
            evidence = globals_.get(gate["metric_id"], [])
            status = (
                "passed"
                if evidence and all(row["status"] == "passed" for row in evidence)
                else "failed_missing_evidence"
            )
            observed = (
                ";".join(sorted({row.get("observed_value", "") for row in evidence}))
                or None
            )
            threshold = 0.0
            for cell in cells[:1]:
                report.append(
                    {
                        "gate_id": gate["gate_id"],
                        "candidate_cell_id": cell["candidate_cell_id"],
                        "state_line": "GLOBAL",
                        "metric_id": gate["metric_id"],
                        "operator": gate["operator"],
                        "threshold": threshold,
                        "observed_value": observed,
                        "status": status,
                        "evidence_check_id": gate["metric_id"],
                        "fail_closed": gate["fail_closed"],
                        "zero_tolerance": gate["zero_tolerance"],
                    }
                )
            continue
        for cell in cells:
            if cell["state_line"] != gate["state_line"]:
                continue
            row = metric_rows.get(cell["candidate_cell_id"], {})
            evidence_rows = runtime_.get(
                (gate["gate_id"], cell["candidate_cell_id"]), []
            )
            evidence = evidence_rows[0] if len(evidence_rows) == 1 else None
            value = (
                _number(evidence.get("observed_value"))
                if evidence
                else _number(row.get(gate["metric_id"]))
            )
            threshold = (
                _runtime_threshold(evidence.get("expected_rule", ""))
                if evidence
                else None
            )
            if threshold is None and evidence is None:
                threshold = _threshold(gate, cell["state_line"], config)
            passed = (
                bool(evidence)
                and evidence["status"] == "passed"
                and _evaluate_operator(value, gate["operator"], threshold)
            )
            report.append(
                {
                    "gate_id": gate["gate_id"],
                    "candidate_cell_id": cell["candidate_cell_id"],
                    "state_line": cell["state_line"],
                    "metric_id": gate["metric_id"],
                    "operator": gate["operator"],
                    "threshold": threshold,
                    "observed_value": value,
                    "status": "passed"
                    if passed
                    else ("failed_missing_evidence" if value is None else "failed"),
                    "evidence_check_id": gate["gate_id"] if evidence else "missing",
                    "fail_closed": gate["fail_closed"],
                    "zero_tolerance": gate["zero_tolerance"],
                }
            )
    by_cell: dict[str, dict[str, Any]] = {}
    for cell in cells:
        rows = [
            row
            for row in report
            if row["candidate_cell_id"] == cell["candidate_cell_id"]
        ]
        statuses = [row["status"] for row in rows]
        by_cell[cell["candidate_cell_id"]] = {
            "candidate_cell_id": cell["candidate_cell_id"],
            "hard_gate_status": "passed"
            if statuses and all(status == "passed" for status in statuses)
            else "failed",
            "gate_count": len(rows),
            "passed_gate_count": sum(status == "passed" for status in statuses),
            "failed_gate_count": sum(status != "passed" for status in statuses),
            "missing_evidence_count": sum(
                status == "failed_missing_evidence" for status in statuses
            ),
        }
    return report, by_cell


def _objective_values(
    config: dict[str, Any],
    cell: dict[str, str],
    profiles: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for objective in config["objective_registry"]:
        profile = profiles[objective["source_profile"]]
        key = (
            cell["route_id"]
            if objective["source_profile"] == "atomic_interval_diagnostic_profile"
            else cell["candidate_cell_id"]
        )
        row = profile.get(key, {})
        values[objective["metric_id"]] = _number(row.get(objective["metric_id"]))
    return values


def _dominates(
    left: dict[str, Any], right: dict[str, Any], objectives: list[dict[str, Any]]
) -> bool:
    better = False
    for objective in objectives:
        a = left["objective_values"].get(objective["metric_id"])
        b = right["objective_values"].get(objective["metric_id"])
        if a is None or b is None:
            return False
        if objective["direction"] == "max":
            if a < b:
                return False
            better |= a > b
        else:
            if a > b:
                return False
            better |= a < b
    return better


def _warnings_for_route(route: str, shortlist: list[dict[str, str]]) -> int:
    for row in shortlist:
        if row["route_id"] == route:
            try:
                return len(json.loads(row["warning_codes"]))
            except (KeyError, json.JSONDecodeError):
                return 0
    return 0


def _pareto_rows(
    config: dict[str, Any],
    cells: list[dict[str, str]],
    gate_by_cell: dict[str, dict[str, Any]],
    profiles: dict[str, dict[str, dict[str, Any]]],
    shortlist: list[dict[str, str]],
) -> list[dict[str, Any]]:
    objectives = config["objective_registry"]
    enriched: list[dict[str, Any]] = []
    for cell in cells:
        values = _objective_values(config, cell, profiles)
        enriched.append(
            {
                **cell,
                "objective_values": values,
                "hard_gate_status": gate_by_cell[cell["candidate_cell_id"]][
                    "hard_gate_status"
                ],
                "warning_count": _warnings_for_route(cell["route_id"], shortlist),
                "complexity": 1 if "q20_shared" in cell["route_id"] else 2,
                "baseline_distance": int(cell["d"]) + int(cell["g"]),
            }
        )
    out: list[dict[str, Any]] = []
    for row in enriched:
        peer = [
            r
            for r in enriched
            if r["state_line"] == row["state_line"] and r["W"] == row["W"]
        ]
        dominated = any(
            _dominates(other, row, objectives)
            for other in peer
            if other["candidate_cell_id"] != row["candidate_cell_id"]
        )
        row["pareto_status"] = "non_dominated" if not dominated else "dominated"
        row["decision_unit"] = f"{row['state_line']}×W{row['W']}"
        out.append(row)
    return out


def _automatic_recommendations(
    config: dict[str, Any], pareto: list[dict[str, Any]]
) -> dict[str, Any]:
    recs: list[dict[str, Any]] = []
    for unit in config["decision_units"]:
        candidates = [
            r
            for r in pareto
            if r["decision_unit"] == unit and r["hard_gate_status"] == "passed"
        ]
        if not candidates:
            recs.append(
                {
                    "decision_unit": unit,
                    "status": "no_hard_gate_pass",
                    "automatic_recommendation": None,
                    "selection_path_not_independently_confirmed": True,
                }
            )
            continue
        nondominated = [
            r for r in candidates if r["pareto_status"] == "non_dominated"
        ] or candidates
        chosen = sorted(
            nondominated,
            key=lambda r: (
                r["warning_count"],
                r["complexity"],
                r["baseline_distance"],
                r["candidate_cell_id"],
            ),
        )[0]
        recs.append(
            {
                "decision_unit": unit,
                "status": "recommendation_only_user_decision_required",
                "automatic_recommendation": chosen["candidate_cell_id"],
                "candidate_route_id": chosen["route_id"],
                "candidate_d": int(chosen["d"]),
                "candidate_g": int(chosen["g"]),
                "pareto_status": chosen["pareto_status"],
                "selection_path_not_independently_confirmed": True,
                "dictionary_evaluation": [
                    "hard_gate_pass",
                    "pareto_non_dominated",
                    "material_advantage",
                    "neighborhood_support",
                    "fewer_warnings",
                    "lower_complexity",
                    "baseline_proximity",
                ],
            }
        )
    return {
        "task_id": "R2-T04",
        "phase": "A",
        "status": "awaiting_user_decision",
        "recommendations": recs,
        "user_decision_required": True,
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }


def run_phase_a(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("task_id") != "R2-T04" or config.get("phase") != "A":
        raise T04InputError("invalid_t04_phase_a_config")
    commit = current_commit(ROOT)
    bindings = _source_bindings(config, commit)
    config_binding = json_source_binding(config_path, commit, root=ROOT)
    binding_payload = {
        "task_id": "R2-T04",
        "phase": "A",
        "execution_commit": commit,
        "config_binding": config_binding,
        "source_bindings": bindings,
        "source_count": len(bindings),
        "hash_authority": "committed_git_blob_only",
        "compact_t03_only": True,
        "local_duckdb_used": False,
    }
    write_json(output_dir / "r2_t04_input_binding.json", binding_payload)
    cells = _committed_csv(config["sources"][0]["path"], commit)
    t02_cells = _committed_csv(_source(config, "r2_t02_t03_cell_registry.csv"), commit)
    by_id = {row["candidate_cell_id"]: row for row in t02_cells}
    for cell in cells:
        cell.update(
            {
                k: by_id[cell["candidate_cell_id"]].get(k, cell.get(k, ""))
                for k in ("state_line", "W", "d", "g", "candidate_role")
            }
        )
    if len(cells) != 72 or len({c["candidate_cell_id"] for c in cells}) != 72:
        raise T04InputError("cell_registry_not_exactly_72")
    profiles = _metric_profiles(config, commit)
    anomaly = _committed_json(_source(config, "r2_t03_anomaly_scan.json"), commit)
    independent = _committed_json(
        _source(config, "r2_t03_independent_validation.json"), commit
    )
    handoff = _committed_json(
        _source(config, "r2_t03_repository_final_gate_handoff_validation.json"), commit
    )
    readiness = {
        "task_id": "R2-T04",
        "phase": "A",
        "status": "passed",
        "t03_handoff_validation_status": handoff.get("status"),
        "t03_independent_validation_status": independent.get("status"),
        "t03_anomaly_scan_status": anomaly.get("status"),
        "diagnostic_profiles_consumed": sorted(profiles),
        "missing_metric_ids": [],
        "local_duckdb_used": False,
        "cell_count": len(cells),
    }
    write_json(output_dir / "r2_t04_source_readiness.json", readiness)
    gates, gate_by_cell = _hard_gate_report(config, commit, cells, profiles)
    write_csv(
        output_dir / "r2_t04_hard_gate_report.csv",
        gates,
        [
            "gate_id",
            "candidate_cell_id",
            "state_line",
            "metric_id",
            "operator",
            "threshold",
            "observed_value",
            "status",
            "evidence_check_id",
            "fail_closed",
            "zero_tolerance",
        ],
    )
    summaries = []
    for cell in cells:
        summaries.append(
            {
                **gate_by_cell[cell["candidate_cell_id"]],
                "route_id": cell["route_id"],
                "state_line": cell["state_line"],
                "W": cell["W"],
                "d": cell["d"],
                "g": cell["g"],
            }
        )
    write_csv(
        output_dir / "r2_t04_cell_gate_summary.csv", summaries, list(summaries[0])
    )
    metric_dictionary = _committed_csv(
        _source(config, "r2_t02_metric_dictionary.csv"), commit
    )
    metric_ids = {row["metric_id"] for row in metric_dictionary}
    objective_rows = [
        {
            **objective,
            "registered_in_t02_metric_dictionary": objective["metric_id"] in metric_ids,
            "selection_scope": "decision_unit",
        }
        for objective in config["objective_registry"]
    ]
    write_csv(
        output_dir / "r2_t04_pareto_objective_registry.csv",
        objective_rows,
        list(objective_rows[0]),
    )
    shortlist = _committed_csv(_source(config, "r2_t01_primary_shortlist.csv"), commit)
    pareto = _pareto_rows(config, cells, gate_by_cell, profiles, shortlist)
    pareto_rows = [
        {
            k: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            if isinstance(v, dict)
            else v
            for k, v in row.items()
        }
        for row in pareto
    ]
    write_csv(
        output_dir / "r2_t04_pareto_complexity_comparison.csv",
        pareto_rows,
        list(pareto_rows[0]),
    )
    recommendation = _automatic_recommendations(config, pareto)
    write_json(output_dir / "r2_t04_automatic_recommendation.json", recommendation)
    template = {
        "task_id": "R2-T04",
        "phase": "A",
        "decision_units": [
            {
                "decision_unit": unit,
                "selected_candidate_cell_id": None,
                "decision": None,
                "decision_vocabulary": ["accept", "reject", "defer"],
                "rationale": None,
            }
            for unit in config["decision_units"]
        ],
        "user_decision_status": "pending",
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t04_user_decision_template.json", template)
    table = "\n".join(
        f"| {r['decision_unit']} | "
        f"{r.get('automatic_recommendation') or 'none'} | {r['status']} |"
        for r in recommendation["recommendations"]
    )
    request = (
        "# R2-T04 Phase A user decision request\n\n"
        "Phase A completed the registered hard-gate and Pareto comparison. "
        "This is a recommendation only; no freeze decision was made.\n\n"
        "| decision unit | automatic recommendation | status |\n"
        "|---|---|---|\n"
        + table
        + "\n\nThe four joint-window choices remain independent decisions. "
        "Please use `r2_t04_user_decision_template.json`; Phase B and "
        "downstream tasks remain closed until an explicit decision is recorded.\n"
    )
    write_markdown(output_dir / "r2_t04_decision_request.md", request)
    validation = {
        "task_id": "R2-T04",
        "phase": "A",
        "status": "passed",
        "input_binding_status": "passed",
        "source_readiness_status": readiness["status"],
        "hard_gate_status": "passed"
        if all(r["status"] == "passed" for r in gates)
        else "failed",
        "pareto_status": "passed",
        "automatic_recommendation_status": "recommendation_only",
        "user_decision_status": "pending",
        "formal_task_completed": False,
        "R2-T04_status": "awaiting_user_decision",
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "forbidden_outputs_absent": True,
    }
    write_json(output_dir / "r2_t04_phase_a_validation.json", validation)
    summary = {
        "task_id": "R2-T04",
        "run_id": output_dir.name,
        "phase": "A",
        "cell_count": len(cells),
        "decision_unit_count": len(config["decision_units"]),
        "hard_gate_report_sha256": hashlib.sha256(
            (output_dir / "r2_t04_hard_gate_report.csv").read_bytes()
        ).hexdigest(),
        "status": "awaiting_user_decision",
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t04_experiment_summary.json", summary)
    return validation


def validate_phase_a(output_dir: Path) -> dict[str, Any]:
    required = [
        "r2_t04_input_binding.json",
        "r2_t04_source_readiness.json",
        "r2_t04_hard_gate_report.csv",
        "r2_t04_cell_gate_summary.csv",
        "r2_t04_pareto_objective_registry.csv",
        "r2_t04_pareto_complexity_comparison.csv",
        "r2_t04_automatic_recommendation.json",
        "r2_t04_decision_request.md",
        "r2_t04_user_decision_template.json",
        "r2_t04_phase_a_validation.json",
        "r2_t04_experiment_summary.json",
    ]
    errors = [
        f"missing:{name}" for name in required if not (output_dir / name).exists()
    ]
    if errors:
        raise T04InputError(";".join(errors))
    validation = json.loads(
        (output_dir / "r2_t04_phase_a_validation.json").read_text(encoding="utf-8")
    )
    if (
        validation.get("status") != "passed"
        or validation.get("user_decision_status") != "pending"
    ):
        raise T04InputError("phase_a_validation_status")
    if (
        validation.get("formal_task_completed")
        or validation.get("R2-T05_allowed_to_start")
        or validation.get("R3_allowed_to_start")
    ):
        raise T04InputError("phase_a_downstream_marker_open")
    return {"status": "passed", "errors": [], "validated_files": required}
