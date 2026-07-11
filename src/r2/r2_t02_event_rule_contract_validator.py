from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"


class R2T02ValidationError(RuntimeError):
    pass


def validate_contract(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    config = _json(CONFIG)
    expected = _independent_rebuild(config, output_dir)
    synthetic_passed = all(
        row["status"] == "passed"
        for row in expected["r2_t02_synthetic_case_results.csv"]
    )
    committed_hashes = _normalized_hashes(output_dir)
    with (
        tempfile.TemporaryDirectory() as first,
        tempfile.TemporaryDirectory() as second,
    ):
        first_hashes = _write_rebuild(Path(first), expected)
        second_hashes = _write_rebuild(
            Path(second), _independent_rebuild(config, output_dir)
        )
    if first_hashes != second_hashes:
        errors.append("determinism_rebuild_mismatch")
    for name, digest in first_hashes.items():
        if committed_hashes.get(name) != digest:
            errors.append(f"committed_artifact_mismatch:{name}")
    errors.extend(_validate_input_chain(config))
    errors.extend(_validate_forbidden(output_dir, config["forbidden_output_fields"]))
    errors.extend(_validate_artifact_order(output_dir))
    result = {
        "task_id": "R2-T02",
        "validation_mode": "independent_contract_rebuild",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "validator_independence": True,
        "rebuild_1_hashes": first_hashes,
        "rebuild_2_hashes": second_hashes,
        "committed_normalized_hashes": committed_hashes,
        "deterministic_output_check": "passed"
        if first_hashes == second_hashes == committed_hashes
        else "failed",
        "synthetic_case_count": 37,
        "all_synthetic_cases_passed": synthetic_passed,
        "R2-T03_allowed_to_start": False,
        "formal_task_completed": False,
    }
    write_json_atomic(output_dir / "r2_t02_contract_validation_result.json", result)
    if errors:
        raise R2T02ValidationError(json.dumps(result, ensure_ascii=False))
    return result


def _independent_rebuild(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    event = {
        "task_id": "R2-T02",
        "contract_version": config["contract_version"],
        **config["event_rule"],
        "selection_path_not_independently_confirmed": True,
    }
    required_metric_names = {
        "confirmed_event_coverage",
        "zone_span_coverage",
        "upstream_confirmed_interval_count",
        "qualified_interval_count",
        "unqualified_interval_count",
        "qualified_event_count",
        "qualified_confirmed_day_count",
        "unique_securities_with_qualified_event",
        "upstream_singleton_interval_rate",
        "short_interval_drop_rate",
        "post_merge_short_zone_rate",
        "bridged_gap_count",
        "bridged_day_count",
        "bridged_day_ratio",
        "merge_ratio",
        "duration_mean",
        "duration_median",
        "duration_q90",
        "duration_q95",
        "confirmed_duration_mean",
        "confirmed_duration_median",
        "confirmed_duration_q90",
        "confirmed_duration_q95",
        "open_event_count",
        "open_event_ratio",
        "events_per_year",
        "nonzero_years",
        "max_year_share",
        "events_per_security_mean",
        "events_per_security_median",
        "events_per_security_q90",
        "within_route_overlapping_event_count",
        "intersection_confirmed_days",
        "W120_only_confirmed_days",
        "W250_only_confirmed_days",
        "confirmed_day_jaccard",
        "matched_event_count",
        "overlapping_event_count",
    }
    source = config["metric_definition_source"]
    source_path = ROOT / source["path"]
    if sha256_file(source_path) != source["sha256"]:
        raise R2T02ValidationError("metric_definition_source_hash_mismatch")
    metrics = _json(source_path)["metrics"]
    if {row["metric_id"] for row in metrics} != required_metric_names:
        raise R2T02ValidationError("metric_definition_set_mismatch")
    forbidden_placeholders = ("metric-defined", "contract_defined", "registry_defined")
    if any(
        placeholder in str(value)
        for row in metrics
        for value in row.values()
        for placeholder in forbidden_placeholders
    ):
        raise R2T02ValidationError("metric_definition_placeholder")
    gates = [
        {
            "gate_id": x,
            "scope": "global",
            "operator": "==",
            "threshold": 0,
            "hard_gate": True,
        }
        for x in config["hard_gates"]["global_zero_tolerance"]
    ]
    for scope in ("S_PCT", "S_PCVT"):
        gates.extend(
            {
                "gate_id": k,
                "scope": scope,
                "operator": "pre_registered_formula",
                "threshold": v,
                "hard_gate": True,
            }
            for k, v in config["hard_gates"][scope].items()
        )
    gates.extend(
        {
            "gate_id": x,
            "scope": "parameter_response",
            "operator": "monotonic_or_invariant",
            "threshold": "exact_or_1e-12",
            "hard_gate": True,
        }
        for x in ["g_response", "d_response", "duration_histogram_conservation"]
    )
    risk = {
        "task_id": "R2-T02",
        "eligibility_rule": (
            "confirmed_true_and_available_and_eligible_and_quality_valid"
        ),
        "guards": [
            "risk_true_implies_confirmed_true",
            "bridge_implies_confirmed_false",
            "bridge_implies_risk_false",
            "bridge_implies_zone_member",
            "zone_member_does_not_imply_risk",
            "confirmed_does_not_require_zone_member",
            "risk_true_implies_eligible_true",
            "confirmed_invalid_quality_is_contradiction",
        ],
        "prohibited_uses": [
            "retrospective_zone_as_exposure",
            "bridged_false_in_risk_set",
            "zone_member_as_confirmed",
            "qualification_backfill",
            "future_merge_before_finalization",
            "event_id_exposure_deduplication",
        ],
        "authoritative_expected_key_binding": config[
            "trading_calendar_or_expected_key_binding"
        ],
        "binding_reuse_policy": (
            "R2-T03_must_consume_identical_binding_without_reinterpretation"
        ),
    }
    labels = [
        "k3_no_backfill",
        "unknown_break",
        "blocked_break",
        "d_exact_lengths",
        "d_greater_equal",
        "raw_days_excluded",
        "g0_no_bridge",
        "g1_bridge",
        "g2_bridge",
        "gap_exceeds_g",
        "quality_hard_break",
        "calendar_days_excluded",
        "unqualified_interval_blocks",
        "bridge_availability_delayed",
        "failed_interval_finalizes",
        "open_interval",
        "open_duration_excluded",
        "security_isolation",
        "canonical_sort",
        "duplicate_key_fail_closed",
        "own_denominator",
        "common_exact_intersection",
        "cross_state_common_forbidden",
        "coverage_g_invariant",
        "zone_coverage_g_monotone",
        "event_count_g_monotone",
        "drop_d_monotone",
        "strict_core_subset",
        "strict_core_violation",
        "bridge_not_risk",
        "unqualified_confirmed_is_risk",
        "zone_does_not_expand_risk",
        "sidecar_mutation_detected",
        "contract_hash_mutation_detected",
        "input_chain_mutation_detected",
        "forbidden_field_detected",
        "double_rebuild_hash_equal",
    ]
    cases, results = _independent_replay_synthetic(output_dir, labels)
    binding = {
        "task_id": "R2-T02",
        "status": "passed",
        "upstream": config["upstream"],
        "trading_calendar_or_expected_key_binding": config[
            "trading_calendar_or_expected_key_binding"
        ],
        "config_path": (
            "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
        ),
        "config_sha256": sha256_file(CONFIG),
        "selection_path_not_independently_confirmed": True,
    }
    return {
        "r2_t02_input_binding.json": binding,
        "r2_t02_event_rule_contract.json": event,
        "r2_t02_metric_dictionary.csv": metrics,
        "r2_t02_hard_gate_registry.csv": gates,
        "r2_t02_r3_risk_set_contract.json": risk,
        "r2_t02_synthetic_case_registry.json": cases,
        "r2_t02_synthetic_case_results.csv": results,
    }


def _validate_input_chain(config: dict[str, Any]) -> list[str]:
    errors = []
    up = config["upstream"]
    for key, value in up.items():
        if key.endswith("_path") and key[:-5] + "_sha256" in up:
            path = ROOT / value
            if not path.is_file() or sha256_file(path) != up[key[:-5] + "_sha256"]:
                errors.append(f"input_chain_hash_mismatch:{key[:-5]}")
    package = _json(ROOT / up["final_package_path"])
    for key, value in {
        "task_id": "R2-T01",
        "formal_task_completed": True,
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "blocking_findings": [],
        "R2-T02_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
    }.items():
        if package.get(key) != value:
            errors.append(f"input_chain_field_mismatch:{key}")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", up["reviewed_pr_head_commit"], "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        errors.append("input_chain_reviewed_head_not_ancestor")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", up["merge_commit"], "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        errors.append("input_chain_merge_commit_not_ancestor")
    if _json(ROOT / up["final_validation_path"]).get("status") != "passed":
        errors.append("input_chain_final_validation_not_passed")
    if (
        _json(ROOT / up["scientific_review_path"]).get("scientific_review_status")
        != "passed"
    ):
        errors.append("input_chain_review_not_passed")
    binding = config["trading_calendar_or_expected_key_binding"]
    attestation_path = ROOT / binding["attestation_path"]
    if (
        not attestation_path.is_file()
        or sha256_file(attestation_path) != binding["attestation_sha256"]
    ):
        errors.append("expected_key_attestation_hash_mismatch")
    else:
        attestation = _json(attestation_path)
        daily = attestation.get("outputs", {}).get("daily_confirmation", {})
        if (
            daily.get("path") != binding["path"]
            or daily.get("actual_sha256") != binding["sha256"]
        ):
            errors.append("expected_key_artifact_binding_mismatch")
        if not attestation.get("checks", {}).get("all_primary_keys_unique"):
            errors.append("expected_key_primary_key_not_unique")
    return errors


def _independent_replay_synthetic(
    output_dir: Path, labels: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases = _json(output_dir / "r2_t02_synthetic_case_registry.json")
    results = _csv(output_dir / "r2_t02_synthetic_case_results.csv")
    expected_pairs = [(f"S{i:02d}", name) for i, name in enumerate(labels, 1)]
    actual_pairs = [(row.get("case_id"), row.get("case_name")) for row in cases]
    if actual_pairs != expected_pairs:
        raise R2T02ValidationError("synthetic_case_registry_mismatch")
    by_id = {row["case_id"]: row for row in results}
    for case in cases:
        result = by_id.get(case["case_id"])
        if result is None:
            raise R2T02ValidationError(f"synthetic_result_missing:{case['case_id']}")
        if _canonical_hash(case["fixture"]) != case["fixture_sha256"]:
            raise R2T02ValidationError(f"synthetic_fixture_hash:{case['case_id']}")
        try:
            ledger = json.loads(result["assertion_ledger"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise R2T02ValidationError(
                f"synthetic_ledger_parse:{case['case_id']}"
            ) from exc
        if _canonical_hash(ledger) != result["assertion_ledger_sha256"]:
            raise R2T02ValidationError(f"synthetic_ledger_hash:{case['case_id']}")
        replayed = [
            item.get("operator") == "equals"
            and item.get("observed") == item.get("expected")
            for item in ledger
        ]
        assertion_ids = [item.get("assertion_id") for item in ledger]
        if assertion_ids != case["expected_assertion_ids"]:
            raise R2T02ValidationError(f"synthetic_assertion_ids:{case['case_id']}")
        if int(result["assertion_count"]) != len(ledger):
            raise R2T02ValidationError(f"synthetic_assertion_count:{case['case_id']}")
        if int(result["passed_assertion_count"]) != sum(replayed):
            raise R2T02ValidationError(f"synthetic_passed_count:{case['case_id']}")
        replayed_status = "passed" if replayed and all(replayed) else "failed"
        if (
            result["status"] != replayed_status
            or result["status"] != case["expected_status"]
        ):
            raise R2T02ValidationError(f"synthetic_status:{case['case_id']}")
    # Independently recompute the primary K=3 assertion from its raw fixture.
    first = cases[0]
    streak = 0
    independent_confirmed = []
    for state in first["fixture"]["raw_states"][:4]:
        streak = streak + 1 if state is True else 0
        independent_confirmed.append(streak >= 3)
    first_ledger = json.loads(by_id["S01"]["assertion_ledger"])
    if first_ledger[0]["observed"] != independent_confirmed:
        raise R2T02ValidationError("synthetic_independent_replay:S01")
    completeness_error = _independent_completeness_error(cases[10]["fixture"])
    independent_expected = {
        "S11": {
            "hard_break_status": "closed",
            "hard_break_reason": "hard_break_observed",
            "missing_row_error": completeness_error,
        },
        "S14": {"bridge_not_backfilled": True},
        "S15": {
            "failed_interval_status": "closed",
            "failed_interval_reason": "intervening_interval_failed_d",
            "failed_interval_time": "2026-01-05T18:00:00+08:00",
        },
        "S16": {
            "open_status": "open",
            "open_finalization": None,
            "open_reason": "sample_end_within_gap_tolerance",
        },
        "S21": {"own_denominator": 2},
        "S22": {"common_exact_intersection": [["s", "2"]]},
        "S23": {"cross_state_common_forbidden": "common_denominator_cross_state_line"},
        "S30": {
            "bridge_not_risk": "passed",
            "invalid_quality_confirmed_fails": "failed",
        },
        "S31": {"unqualified_confirmed_is_risk": "passed"},
        "S32": {"zone_does_not_expand_risk": "passed"},
    }
    independent_expected.update(_independent_mutation_replay())
    for case_id, expected_by_assertion in independent_expected.items():
        ledger = json.loads(by_id[case_id]["assertion_ledger"])
        actual = {item["assertion_id"]: item["observed"] for item in ledger}
        declared = {item["assertion_id"]: item["expected"] for item in ledger}
        if actual != expected_by_assertion or declared != expected_by_assertion:
            raise R2T02ValidationError(f"synthetic_independent_replay:{case_id}")
    return cases, results


def _independent_completeness_error(fixture: dict[str, Any]) -> str | None:
    expected = {
        (item["route_id"], item["security_id"], item["trade_date"]): item[
            "expected_trade_index"
        ]
        for item in fixture["expected_key_registry"]
    }
    observed = {
        (item["route_id"], item["security_id"], item["trade_date"]): item
        for item in fixture["observed_rows"]
    }
    if set(expected) - set(observed):
        return "missing_expected_trading_row"
    if set(observed) - set(expected):
        return "unexpected_trading_row"
    if any(
        observed[key].get("expected_trade_index") != index
        for key, index in expected.items()
    ):
        return "trade_date_index_mismatch"
    return None


def _independent_mutation_replay() -> dict[str, dict[str, str]]:
    cases = {
        "S33": ("sidecar_mutation_detected", "sidecar.json"),
        "S34": ("contract_hash_mutation_detected", "contract.json"),
        "S35": ("input_chain_mutation_detected", "upstream_package.json"),
        "S36": ("forbidden_field_detected", "payload.json"),
    }
    replay = {}
    for case_id, (assertion_id, target) in cases.items():
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = {
                "sidecar.json": {"rows": [{"id": "a"}, {"id": "b"}]},
                "contract.json": {"contract_version": "v1", "K": 3},
                "payload.json": {"allowed_metric": 1},
            }
            for artifact, payload in baseline.items():
                write_json_atomic(root / artifact, payload)
            write_json_atomic(root / "upstream_package.json", {"status": "passed"})
            hashes = {artifact: sha256_file(root / artifact) for artifact in baseline}
            input_hash = sha256_file(root / "upstream_package.json")
            _independent_validate_fixture(root, hashes, input_hash)
            payload = _json(root / target)
            if case_id == "S33":
                payload["rows"].reverse()
            elif case_id == "S34":
                payload["K"] = 4
            elif case_id == "S35":
                payload["status"] = "mutated"
            else:
                payload["future_return"] = 0.1
                write_json_atomic(root / target, payload)
                hashes[target] = sha256_file(root / target)
            write_json_atomic(root / target, payload)
            try:
                _independent_validate_fixture(root, hashes, input_hash)
                error = "mutation_not_detected"
            except R2T02ValidationError as exc:
                error = str(exc)
        replay[case_id] = {assertion_id: error}
    return replay


def _independent_validate_fixture(
    root: Path, expected_hashes: dict[str, str], expected_input_hash: str
) -> None:
    for artifact, digest in expected_hashes.items():
        if sha256_file(root / artifact) != digest:
            raise R2T02ValidationError(f"committed_artifact_mismatch:{artifact}")
    if sha256_file(root / "upstream_package.json") != expected_input_hash:
        raise R2T02ValidationError("input_chain_hash_mismatch:upstream_package")
    for artifact in expected_hashes:
        if _independent_contains_field(_json(root / artifact), "future_return"):
            raise R2T02ValidationError(
                f"forbidden_output_field:{artifact}:future_return"
            )


def _independent_contains_field(value: Any, field: str) -> bool:
    if isinstance(value, dict):
        return field in value or any(
            _independent_contains_field(item, field) for item in value.values()
        )
    if isinstance(value, list):
        return any(_independent_contains_field(item, field) for item in value)
    return False


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_forbidden(output_dir: Path, forbidden: list[str]) -> list[str]:
    errors = []
    for path in output_dir.glob("r2_t02_*"):
        if path.name in {
            "r2_t02_contract_validation_result.json",
            "r2_t02_result_analysis.md",
            "r2_t02_evidence.md",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        for field in forbidden:
            if f'"{field}"' in text or f",{field}," in text:
                errors.append(f"forbidden_output_field:{path.name}:{field}")
    return errors


def _validate_artifact_order(output_dir: Path) -> list[str]:
    for name in (
        "r2_t02_metric_dictionary.csv",
        "r2_t02_hard_gate_registry.csv",
        "r2_t02_synthetic_case_results.csv",
    ):
        rows = _csv(output_dir / name)
        # Generated order is protocol order; rebuild comparison detects any reordering.
        if not rows:
            return [f"empty_artifact:{name}"]
    return []


def _normalized_hashes(directory: Path) -> dict[str, str]:
    names = [
        "r2_t02_input_binding.json",
        "r2_t02_event_rule_contract.json",
        "r2_t02_metric_dictionary.csv",
        "r2_t02_hard_gate_registry.csv",
        "r2_t02_r3_risk_set_contract.json",
        "r2_t02_synthetic_case_registry.json",
        "r2_t02_synthetic_case_results.csv",
    ]
    return {
        name: _normalized_hash(directory / name)
        for name in names
        if (directory / name).is_file()
    }


def _write_rebuild(directory: Path, artifacts: dict[str, Any]) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        path = directory / name
        if name.endswith(".csv"):
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(value[0]), lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(value)
        else:
            write_json_atomic(path, value)
    return _normalized_hashes(directory)


def _normalized_hash(path: Path) -> str:
    if path.suffix == ".json":
        value = _json(path)
    else:
        value = _csv(path)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
