"""Independent, fail-closed validation for the R2-T08 package.

This module deliberately does not import the T08 generator.  It reads the
T08 files directly and reads the authoritative T07 inputs through Git blobs.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import ROOT, git_blob_bytes, sha256_bytes, write_json

TASK_ID = "R2-T08"
CONFIG_PATH = "configs/r2/r2_t08_r2_gate_r3_handoff.v1.json"
INDEPENDENT_CHECK_IDS = [
    "t07_manifest_integrity_mismatch",
    "t07_validation_status_mismatch",
    "frozen_version_identity_mismatch",
    "canonical_interface_mismatch",
    "registry_policy_mismatch",
    "warning_limitation_mismatch",
    "window_strict_core_mismatch",
    "release_anchor_obligation_mismatch",
    "unique_r3_entrypoint_mismatch",
    "unexpected_field_violation",
    "committed_reference_mismatch",
    "downstream_gate_violation",
]


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _json_path(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_not_object:{path}")
    return value


def _csv_path(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _source_json(root: Path, commit: str, path: str) -> dict[str, Any]:
    return json.loads(git_blob_bytes(commit, path, root=root))


def _source_bytes(root: Path, commit: str, path: str) -> bytes:
    return git_blob_bytes(commit, path, root=root)


def _read_config(root: Path) -> dict[str, Any]:
    return _json_path(root / CONFIG_PATH)


def _load_t07(root: Path, run_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    input_binding = _json_path(run_dir / "r2_t08_input_binding.json")
    source_commit = input_binding.get("t07_merge_commit")
    if not isinstance(source_commit, str):
        raise ValueError("missing_t07_merge_commit")
    final_path = config["t07_binding"]["final_manifest_path"]
    final = _source_json(root, source_commit, final_path)
    base = str(Path(final_path).parent).replace("\\", "/")
    paths = {
        "output": f"{base}/r2_t07_output_manifest.json",
        "independent": f"{base}/r2_t07_independent_validation.json",
        "reconciliation": f"{base}/r2_t07_registry_reconciliation.json",
        "forbidden": f"{base}/r2_t07_forbidden_use_audit.json",
        "anomaly": f"{base}/r2_t07_anomaly_scan.json",
        "committed": f"{base}/r2_t07_committed_artifact_validation.json",
        "interval": f"{base}/r2_interval_rule_registry.json",
        "event": f"{base}/r2_event_state_machine_registry.json",
        "decision": f"{base}/r2_freeze_decision_log.json",
        "state": f"{base}/r2_state_version_registry.csv",
    }
    loaded: dict[str, Any] = {
        "source_commit": source_commit,
        "final_path": final_path,
        "final": final,
    }
    for key, path in paths.items():
        if key == "state":
            text = _source_bytes(root, source_commit, path).decode("utf-8")
            loaded[key] = list(csv.DictReader(text.splitlines()))
        else:
            loaded[key] = _source_json(root, source_commit, path)
    return loaded


def _core_reference_mismatch(
    root: Path, config: dict[str, Any], t07: dict[str, Any]
) -> int:
    final = t07["final"]
    output_by_path = {
        item.get("path"): item for item in t07["output"].get("artifacts", [])
    }
    committed_by_path = {
        item.get("path"): item
        for item in t07["committed"].get("validated_artifacts", [])
    }
    names = {
        "state_version_registry": "state_version_registry",
        "interval_rule_registry": "interval_rule_registry",
        "event_state_machine_registry": "event_state_machine_registry",
        "freeze_decision_log": "freeze_decision_log",
    }
    mismatch = 0
    for name, key in names.items():
        ref = final.get(key)
        if not isinstance(ref, dict):
            mismatch += 1
            continue
        path = ref.get("path")
        expected = config["t07_binding"]["core_artifact_sha256"][name]
        try:
            payload = _source_bytes(root, t07["source_commit"], path)
            blob = _git(root, "rev-parse", f"{t07['source_commit']}:{path}")
        except (subprocess.CalledProcessError, TypeError):
            mismatch += 1
            continue
        output = output_by_path.get(path, {})
        committed = committed_by_path.get(path, {})
        mismatch += (
            0
            if (
                ref.get("sha256") == expected
                and ref.get("size_bytes") == len(payload)
                and sha256_bytes(payload) == expected
                and output.get("sha256") == expected
                and output.get("size_bytes") == len(payload)
                and committed.get("committed_byte_sha256") == expected
                and committed.get("git_blob_sha") == blob
                and committed.get("size_bytes") == len(payload)
            )
            else 1
        )
    return mismatch


def _t07_status_mismatch(config: dict[str, Any], t07: dict[str, Any]) -> int:
    independent = t07["independent"]
    numeric = independent.get("checks", {})
    reconciliation = t07["reconciliation"]
    return (
        0
        if (
            len(numeric) == config["expected_counts"]["t07_independent_numeric_checks"]
            and all(isinstance(value, int) and value == 0 for value in numeric.values())
            and independent.get("failure_count") == 0
            and independent.get("status") == "passed"
            and len(reconciliation.get("checks", []))
            == config["expected_counts"]["t07_registry_reconciliation_checks"]
            and reconciliation.get("failure_count") == 0
            and reconciliation.get("status") == "passed"
            and all(
                row.get("status") == "passed" and row.get("mismatch_count") == 0
                for row in reconciliation["checks"]
            )
            and t07["forbidden"].get("status") == "passed"
            and t07["forbidden"].get("failure_count") == 0
            and t07["anomaly"].get("status") == "passed"
            and t07["anomaly"].get("anomaly_count") == 0
            and t07["committed"].get("status") == "passed"
            and t07["committed"].get("failure_count") == 0
            and len(t07["committed"].get("validated_artifacts", []))
            == config["expected_counts"]["t07_committed_artifact_count"]
        )
        else 1
    )


def _version_mismatch(
    config: dict[str, Any], rows: list[dict[str, str]], handoff: dict[str, Any]
) -> int:
    expected = config["expected_frozen_versions"]
    observed = [
        item.get("state_version_id") for item in handoff.get("frozen_versions", [])
    ]
    mismatch = (
        0
        if len(rows) == 2
        and observed == [item["state_version_id"] for item in expected]
        else 1
    )
    for spec, row in zip(expected, rows, strict=False):
        mismatch += (
            0
            if (
                row.get("state_version_id") == spec["state_version_id"]
                and row.get("state_line") == spec["state_line"]
                and row.get("W") == str(spec["W"])
                and row.get("K") == str(spec["K"])
                and row.get("d") == str(spec["d"])
                and row.get("g") == str(spec["g"])
                and row.get("strict_core_source_candidate_cell_id")
                == spec["strict_core_source"]
            )
            else 1
        )
    return mismatch


def _canonical_mismatch(
    config: dict[str, Any], handoff: dict[str, Any], final_acceptance: dict[str, Any]
) -> int:
    expected = config["t07_binding"]["canonical"]
    refs = {
        "daily": handoff.get("canonical_daily_state_ref"),
        "event": handoff.get("canonical_event_zone_ref"),
        "membership": handoff.get("canonical_event_membership_ref"),
    }
    mismatch = 0
    for key, ref in refs.items():
        spec = expected[key]
        mismatch += (
            0
            if isinstance(ref, dict)
            and ref.get("stable_multiset_sha256") == spec["stable_multiset_sha256"]
            and ref.get("row_count") == spec["row_count"]
            and ref.get("database_sha256") == expected["database_sha256"]
            else 1
        )
    mismatch += (
        0
        if final_acceptance.get("canonical_interfaces", {})
        .get("daily", {})
        .get("database_sha256")
        == expected["database_sha256"]
        else 1
    )
    return mismatch


def _unexpected_field_mismatch(run_dir: Path) -> int:
    expected = {
        "r2_t08_final_acceptance.json": {
            "task_id",
            "run_id",
            "execution_commit",
            "status",
            "acceptance_matrix_ref",
            "t07_final_freeze_manifest_ref",
            "frozen_version_count",
            "frozen_state_version_ids",
            "canonical_interfaces",
            "r2_evidence_chain_passed",
            "r3_handoff_eligible",
            "formal_task_completed",
            "R3_allowed_to_start",
            "activation_mode",
            "warnings",
            "limitations",
            "forbidden_reinterpretations",
        },
        "r2_t08_r3_handoff_manifest.json": {
            "handoff_id",
            "handoff_version",
            "task_id",
            "run_id",
            "lifecycle",
            "activation_mode",
            "unique_r3_entrypoint",
            "alternative_entrypoints",
            "r3_handoff_eligible",
            "R3_allowed_to_start",
            "frozen_versions",
            "final_freeze_manifest_ref",
            "state_version_registry_ref",
            "interval_rule_registry_ref",
            "event_state_machine_registry_ref",
            "freeze_decision_log_ref",
            "canonical_daily_state_ref",
            "canonical_event_zone_ref",
            "canonical_event_membership_ref",
            "frozen_window_matrix_ref",
            "strict_core_contract",
            "state_risk_set_contract",
            "qualified_event_risk_set_contract",
            "exit_quality_censor_contract",
            "release_anchor_obligation_ref",
            "warnings",
            "limitations",
            "forbidden_reinterpretations",
            "source_bindings",
        },
    }
    return sum(
        1 for name, keys in expected.items() if set(_json_path(run_dir / name)) != keys
    )


def _compute_checks(
    root: Path, run_dir: Path, config: dict[str, Any]
) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    try:
        t07 = _load_t07(root, run_dir, config)
        handoff = _json_path(run_dir / "r2_t08_r3_handoff_manifest.json")
        final_acceptance = _json_path(run_dir / "r2_t08_final_acceptance.json")
        windows = _csv_path(run_dir / "r2_t08_frozen_window_matrix.csv")
        release = _json_path(run_dir / "r2_t08_release_anchor_obligation.json")
        output_manifest = (
            _json_path(run_dir / "r2_t08_output_manifest.json")
            if (run_dir / "r2_t08_output_manifest.json").exists()
            else None
        )
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        return {key: 1 for key in INDEPENDENT_CHECK_IDS}, [f"input_read:{exc}"]

    expected = config["expected_frozen_versions"]
    final = t07["final"]
    manifest_ok = (
        final.get("task_id") == "R2-T07"
        and final.get("run_id") == config["t07_binding"]["authoritative_run"]
        and sha256_bytes(_source_bytes(root, t07["source_commit"], t07["final_path"]))
        == config["t07_binding"]["final_manifest_sha256"]
        and final_acceptance.get("t07_final_freeze_manifest_ref", {}).get("path")
        == t07["final_path"]
        and final_acceptance.get("t07_final_freeze_manifest_ref", {}).get(
            "committed_byte_sha256"
        )
        == config["t07_binding"]["final_manifest_sha256"]
    )
    validation_ok = _t07_status_mismatch(config, t07) == 0
    versions_ok = _version_mismatch(config, t07["state"], handoff) == 0
    canonical_ok = _canonical_mismatch(config, handoff, final_acceptance) == 0
    registry_ok = (
        t07["interval"].get("K") == 3
        and t07["interval"].get("d") == 2
        and t07["interval"].get("g") == 1
        and t07["interval"].get("confirmation_backfill_allowed") is False
        and t07["event"]
        .get("event_identity_policy", {})
        .get("cross_state_version_merge_allowed")
        is False
        and t07["event"]
        .get("source_contract_risk_set_policy", {})
        .get("missing_field_policy")
        == "fail_closed"
        and handoff.get("qualified_event_risk_set_contract", {}).get(
            "event_zone_member_is_not_a_substitute"
        )
        is True
        and handoff.get("state_risk_set_contract", {}).get("authoritative_field")
        == "r2_canonical_daily_state.state_risk_set_eligible"
        and handoff.get("strict_core_contract", {}).get("is_independent_product")
        is False
        and handoff.get("strict_core_contract", {}).get("is_independent_state_version")
        is False
        and handoff.get("strict_core_contract", {}).get(
            "is_independent_event_namespace"
        )
        is False
        and handoff.get("exit_quality_censor_contract", {}).get(
            "confirmed_exit_is_not_release"
        )
        is True
        and handoff.get("exit_quality_censor_contract", {}).get(
            "quality_break_is_not_release"
        )
        is True
        and handoff.get("exit_quality_censor_contract", {}).get(
            "right_censor_is_not_release"
        )
        is True
    )
    warning_ok = (
        handoff.get("warnings")
        == {item["state_version_id"]: item["warning_codes"] for item in expected}
        and set(config["global_limitations"]).issubset(
            set(handoff.get("limitations", []))
        )
        and set(config["forbidden_reinterpretations"]).issubset(
            set(handoff.get("forbidden_reinterpretations", []))
        )
    )
    window_ok = (
        len(windows) == 2
        and all(
            row.get("frozen_windows") == '["W120"]'
            and row.get("overlap_handling_required") == "False"
            and row.get("status") == "not_applicable_single_frozen_window"
            and row.get("frozen_state_version_ids", "").startswith("[")
            for row in windows
        )
        and all(
            item.get("strict_core_source")
            in {x["strict_core_source"] for x in expected}
            for item in handoff.get("frozen_versions", [])
        )
    )
    release_ok = (
        release.get("selection_owner") == "R3"
        and release.get("selected_anchor") is None
        and len(release.get("candidates", [])) == 3
        and final_acceptance.get("r3_handoff_eligible") is True
    )
    unique_ok = (
        handoff.get("unique_r3_entrypoint") is True
        and handoff.get("alternative_entrypoints") == []
        and handoff.get("r3_handoff_eligible") is True
    )
    unexpected = _unexpected_field_mismatch(run_dir)
    committed_refs = _core_reference_mismatch(root, config, t07)
    expected_core = config["t07_binding"]["core_artifact_sha256"]
    for field, name in (
        ("state_version_registry_ref", "state_version_registry"),
        ("interval_rule_registry_ref", "interval_rule_registry"),
        ("event_state_machine_registry_ref", "event_state_machine_registry"),
        ("freeze_decision_log_ref", "freeze_decision_log"),
    ):
        ref = handoff.get(field, {})
        committed_refs += (
            0 if ref.get("committed_byte_sha256") == expected_core[name] else 1
        )
    downstream_ok = (
        final_acceptance.get("formal_task_completed") is False
        and final_acceptance.get("R3_allowed_to_start") is False
        and handoff.get("R3_allowed_to_start") is False
    )
    checks = {
        "t07_manifest_integrity_mismatch": 0 if manifest_ok else 1,
        "t07_validation_status_mismatch": 0 if validation_ok else 1,
        "frozen_version_identity_mismatch": 0 if versions_ok else 1,
        "canonical_interface_mismatch": 0 if canonical_ok else 1,
        "registry_policy_mismatch": 0 if registry_ok else 1,
        "warning_limitation_mismatch": 0 if warning_ok else 1,
        "window_strict_core_mismatch": 0 if window_ok else 1,
        "release_anchor_obligation_mismatch": 0 if release_ok else 1,
        "unique_r3_entrypoint_mismatch": 0 if unique_ok else 1,
        "unexpected_field_violation": unexpected,
        "committed_reference_mismatch": committed_refs,
        "downstream_gate_violation": 0 if downstream_ok else 1,
    }
    if output_manifest is not None:
        for item in output_manifest.get("artifacts", []):
            path = root / item.get("path", "")
            if not path.exists():
                path = run_dir / Path(item.get("path", "")).name
            if (
                not path.exists()
                or sha256_bytes(path.read_bytes()) != item.get("sha256")
                or path.stat().st_size != item.get("size_bytes")
            ):
                checks["committed_reference_mismatch"] += 1
                errors.append(f"output_manifest_artifact:{item.get('path')}")
    return checks, errors


def validate_run(output_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    config = _read_config(root)
    existing_path = output_dir / "r2_t08_independent_validation.json"
    existing = _json_path(existing_path) if existing_path.exists() else None
    checks, errors = _compute_checks(root, output_dir, config)
    if existing is not None and existing.get("checks") != checks:
        checks["unexpected_field_violation"] += 1
        errors.append("existing_independent_validation_mismatch")
    failure_count = sum(checks.values())
    result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if failure_count == 0 else "failed",
        "checks": checks,
        "failure_count": failure_count,
        "errors": errors,
        "formal_task_completed": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t08_independent_validation.json", result)
    anomaly = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if failure_count == 0 else "failed",
        "anomaly_count": failure_count,
        "anomalies": [] if failure_count == 0 else errors,
    }
    write_json(output_dir / "r2_t08_anomaly_scan.json", anomaly)
    return result
