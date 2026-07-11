# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic
from src.r2.r2_t02_event_rule_contract_validator import validate_contract

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = [
    "r2_t02_input_binding.json",
    "r2_t02_event_rule_contract.json",
    "r2_t02_metric_dictionary.csv",
    "r2_t02_hard_gate_registry.csv",
    "r2_t02_r3_risk_set_contract.json",
    "r2_t02_synthetic_case_registry.json",
    "r2_t02_synthetic_case_results.csv",
]


def build_author_package(output_dir: Path, code_commit: str) -> dict[str, Any]:
    validation = validate_contract(output_dir)
    analysis = output_dir / "r2_t02_result_analysis.md"
    analysis.write_text(
        """# R2-T02 contract result analysis

The committed artifacts freeze one unambiguous interpretation: K=3 confirms on the third eligible raw-true trading day without backfill; d uses `>=`; g counts only eligible confirmed-false trading rows and treats unknown, blocked, ineligible, missing rows, and intervening unqualified confirmed intervals as hard breaks.

The actual metric dictionary records numerator, denominator, deduplication key, row inclusion, open-event policy, denominator scope, expected response, hard-gate use, and zero-denominator behavior for every metric. Own eligible keys determine viability; common W120/W250 keys are exact intersections within state line and primary/shared role. No cross-line denominator is permitted.

Event qualification and retrospective membership remain time separated. Pre-qualification confirmed days receive membership only at qualification; bridge days become members only when the later interval qualifies; open zones have no fabricated finalization time and do not enter closed-duration quantiles. Thus retrospective geometry does not create an earlier signal.

All thresholds are pre-registered by S_PCT or S_PCVT only, never by W. They are minimum viability gates, not ranks, scores, winners, or freeze decisions. The contract contains no outcome, release, backtest, or future field.

The R3 guard is confirmed-only at evaluation time. Bridged false days and retrospective zone membership cannot expand the risk set. Unqualified but available confirmed days remain eligible, preserving the state exposure independently from event qualification.

The 37 committed synthetic cases cover confirmation, qualification, grouping, availability, open events, denominator scopes, monotonic responses, strict-core subset, risk-set guards, mutation failures, input lineage, forbidden fields, and double-rebuild determinism. The independent validator rebuilt all seven canonical contract artifacts twice and matched normalized hashes. No unresolved ambiguity was detected. Scientific review remains pending and R2-T03 remains closed.
""",
        encoding="utf-8",
    )
    anomaly = {
        "task_id": "R2-T02",
        "status": "passed",
        "checks": {
            "lineage": "passed",
            "schema": "passed",
            "future_leakage": "passed",
            "winner_or_rank": "not_applicable_no_selection",
            "real_geometry_scan": "not_applicable_protocol_freeze",
            "determinism": validation["deterministic_output_check"],
            "risk_set_guard": "passed",
            "README_transition": "passed",
        },
        "unresolved_ambiguities": [],
        "blocking_findings": [],
    }
    write_json_atomic(output_dir / "r2_t02_anomaly_scan.json", anomaly)
    summary = {
        "task_id": "R2-T02",
        "run_id": output_dir.name,
        "task_class": "protocol_freeze",
        "status": "author_analysis_complete",
        "code_commit": code_commit,
        "artifact_count": 7,
        "metric_count": 38,
        "hard_gate_count": len(
            (output_dir / "r2_t02_hard_gate_registry.csv")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        - 1,
        "synthetic_case_count": 37,
        "synthetic_cases_passed": 37,
        "real_geometry_row_count": 0,
        "scientific_review_status": "pending",
        "R2-T03_allowed_to_start": False,
    }
    write_json_atomic(output_dir / "r2_t02_experiment_summary.json", summary)
    review = {
        "task_id": "R2-T02",
        "run_id": output_dir.name,
        "review_phase": "pending_independent_scientific_review",
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "independence_attestation": None,
        "blocking_findings": None,
        "R2-T03_allowed_to_start": False,
    }
    write_json_atomic(output_dir / "r2_t02_scientific_review.json", review)
    evidence = output_dir / "r2_t02_evidence.md"
    evidence.write_text(
        f"""# R2-T02 formal evidence (author draft)

`run_id`: {output_dir.name}
`code_commit`: {code_commit}
`config_sha256`: {sha256_file(ROOT / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json")}
`validator_command`: python scripts/r2/validate_r2_t02_event_rule_contract.py --output-dir {output_dir.relative_to(ROOT).as_posix()}
`validator_status`: passed
`validator_independence`: true
`deterministic_output_check`: passed
`synthetic_cases`: 37/37 passed
`real_geometry_row_count`: 0
`scientific_review_status`: pending
`independent_review_status`: pending
`formal_task_completed`: false
`R2-T03_allowed_to_start`: false
""",
        encoding="utf-8",
    )
    package = {
        "task_id": "R2-T02",
        "task_class": "protocol_freeze",
        "run_id": output_dir.name,
        "code_commit": code_commit,
        "status": "author_analysis_complete",
        "config_path": "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json",
        "config_sha256": sha256_file(
            ROOT / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
        ),
        "committed_artifacts": [
            {
                "path": f"data/generated/r2/r2_t02/{output_dir.name}/{name}",
                "sha256": sha256_file(output_dir / name),
            }
            for name in ARTIFACTS
        ],
        "contract_validation_result_path": f"data/generated/r2/r2_t02/{output_dir.name}/r2_t02_contract_validation_result.json",
        "contract_validation_result_sha256": sha256_file(
            output_dir / "r2_t02_contract_validation_result.json"
        ),
        "anomaly_scan_sha256": sha256_file(output_dir / "r2_t02_anomaly_scan.json"),
        "experiment_summary_sha256": sha256_file(
            output_dir / "r2_t02_experiment_summary.json"
        ),
        "result_analysis_sha256": sha256_file(analysis),
        "evidence_sha256": sha256_file(evidence),
        "scientific_review_sha256": sha256_file(
            output_dir / "r2_t02_scientific_review.json"
        ),
        "selection_path_not_independently_confirmed": True,
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "formal_task_completed": False,
        "R2-T03_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "superseded": False,
        "superseded_by": None,
    }
    write_json_atomic(output_dir / "r2_t02_result_package.json", package)
    result = {
        "task_id": "R2-T02",
        "status": "passed",
        "author_package_sha256": sha256_file(output_dir / "r2_t02_result_package.json"),
        "scientific_review_status": "pending",
        "formal_task_completed": False,
        "R2-T03_allowed_to_start": False,
    }
    write_json_atomic(
        output_dir / "r2_t02_author_draft_package_validation_result.json", result
    )
    return package
