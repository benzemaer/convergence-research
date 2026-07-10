from __future__ import annotations

import csv
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from src.r1.r1_t06_contemporaneous_retention_lift_validator import (
    R1T06ValidationError,
    validate_r1_t06_contemporaneous_retention_lift,
)

STEPS = ("C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT")
WS = (120, 250, 500)
QS = (0.1, 0.2, 0.3)


class R1T06ValidatorTest(unittest.TestCase):
    def test_complete_author_draft_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            result = validate_r1_t06_contemporaneous_retention_lift(
                summary_path=summary,
                result_package_path=package,
                root=root,
            )
            self.assertEqual(result["validator_status"], "passed")

    def test_primary_formula_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            primary = root / "r1_t06_layer_step_profile.csv"
            rows = _read_rows(primary)
            rows[0]["retention"] = "0"
            _write_csv(primary, rows)
            _refresh_summary_hash(root, summary, "layer_step_profile_csv")
            with self.assertRaises(R1T06ValidationError) as raised:
                validate_r1_t06_contemporaneous_retention_lift(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("primary_formula_mismatch:retention", str(raised.exception))

    def test_dimension_reconciliation_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            recon = root / "r1_t06_dimension_state_reconciliation.csv"
            rows = _read_rows(recon)
            rows[0]["active_mismatch_count"] = "1"
            _write_csv(recon, rows)
            _refresh_summary_hash(root, summary, "dimension_state_reconciliation_csv")
            with self.assertRaises(R1T06ValidationError) as raised:
                validate_r1_t06_contemporaneous_retention_lift(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("dimension_active_mismatch", str(raised.exception))

    def test_nested_false_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            recon = root / "r1_t06_r0_nested_reconciliation.csv"
            rows = _read_rows(recon)
            rows[0]["derived_false_count"] = "79"
            rows[0]["false_count_mismatch"] = "true"
            _write_csv(recon, rows)
            _refresh_summary_hash(root, summary, "r0_nested_reconciliation_csv")
            with self.assertRaises(R1T06ValidationError) as raised:
                validate_r1_t06_contemporaneous_retention_lift(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("nested_false_count_mismatch", str(raised.exception))

    def test_q_nesting_reversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            recon = root / "r1_t06_q_nesting_reconciliation.csv"
            rows = _read_rows(recon)
            rows[0]["missing_from_higher_q_count"] = "1"
            rows[0]["symmetric_difference_count"] = "1"
            _write_csv(recon, rows)
            _refresh_summary_hash(root, summary, "q_nesting_reconciliation_csv")
            with self.assertRaises(R1T06ValidationError) as raised:
                validate_r1_t06_contemporaneous_retention_lift(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("q_nesting_missing_from_higher", str(raised.exception))

    def test_author_draft_scientific_review_must_remain_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            payload = json.loads(package.read_text(encoding="utf-8"))
            payload["gate_status"]["scientific_review_status"] = "passed"
            package.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(R1T06ValidationError) as raised:
                validate_r1_t06_contemporaneous_retention_lift(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("scientific_review_not_pending", str(raised.exception))


def _write_fixture(root: Path) -> tuple[Path, Path]:
    primary_rows = []
    for step_index, step in enumerate(STEPS):
        for w_index, w in enumerate(WS):
            n = 100 - w_index * 10 - step_index * 5
            for q_index, q in enumerate(QS):
                n11 = 10 + q_index * 5 - step_index
                n10 = 20 + q_index * 3
                n01 = 15 + q_index * 4
                n00 = n - n11 - n10 - n01
                primary_rows.append(_primary_row(step, w, q, n11, n10, n01, n00))
    _write_csv(root / "r1_t06_layer_step_profile.csv", primary_rows)
    denom_rows = []
    for row in primary_rows:
        all4 = int(row["N"]) if row["step_id"] == "V_GIVEN_PCT" else int(row["N"]) - 5
        denom_rows.append(
            {
                "step_id": row["step_id"],
                "W": row["W"],
                "q": row["q"],
                "primary_step_denominator": row["N"],
                "all4_common_denominator": str(all4),
                "denominator_retention_ratio": str(all4 / int(row["N"])),
                "primary_retention": row["retention"],
                "all4_restricted_retention": row["retention"],
                "retention_difference": "0",
                "primary_lift": row["lift"],
                "all4_restricted_lift": row["lift"],
                "lift_difference": "0",
                "primary_delta": row["delta"],
                "all4_restricted_delta": row["delta"],
                "delta_difference": "0",
            }
        )
    _write_csv(root / "r1_t06_denominator_sensitivity.csv", denom_rows)
    _write_csv(root / "r1_t06_year_step_profile.csv", _year_rows(primary_rows))
    _write_csv(root / "r1_t06_security_step_summary.csv", _security_rows(primary_rows))
    _write_csv(root / "r1_t06_r0_nested_reconciliation.csv", _nested_rows())
    _write_csv(root / "r1_t06_dimension_state_reconciliation.csv", _dimension_rows())
    _write_csv(root / "r1_t06_q_nesting_reconciliation.csv", _q_nesting_rows())
    summary_payload = {
        "task_id": "R1-T06",
        "status": "completed",
        "run_id": "R1-T06-SYNTH",
        "code_commit": "a" * 40,
        "checks": {
            name: "passed"
            for name in (
                "primary_output_nonempty",
                "all_zero_check",
                "all_one_check",
                "all_null_check",
                "validity_rate_check",
                "coverage_check",
                "parameter_response_check",
                "baseline_challenger_check",
                "nested_invariant_check",
                "funnel_accounting_check",
                "denominator_integrity_check",
                "sample_size_check",
                "upstream_consistency_check",
                "scale_shift_check",
                "time_alignment_check",
                "future_leakage_check",
                "post_hoc_selection_check",
                "conclusion_support_check",
            )
        },
        "blocked_reasons": [],
        "downstream_gates": {
            "R1-T07_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
        "output_paths": {},
    }
    role_by_name = {
        "r1_t06_layer_step_profile.csv": "layer_step_profile_csv",
        "r1_t06_denominator_sensitivity.csv": "denominator_sensitivity_csv",
        "r1_t06_year_step_profile.csv": "year_step_profile_csv",
        "r1_t06_security_step_summary.csv": "security_step_summary_csv",
        "r1_t06_r0_nested_reconciliation.csv": "r0_nested_reconciliation_csv",
        "r1_t06_dimension_state_reconciliation.csv": (
            "dimension_state_reconciliation_csv"
        ),
        "r1_t06_q_nesting_reconciliation.csv": "q_nesting_reconciliation_csv",
    }
    for path in root.glob("r1_t06_*.csv"):
        summary_payload["output_paths"][role_by_name[path.name]] = {
            "path": path.name,
            "sha256": _sha(path),
        }
    summary = root / "summary.json"
    summary.write_text(json.dumps(summary_payload, sort_keys=True), encoding="utf-8")
    package = root / "package.json"
    package.write_text(
        json.dumps(
            {
                "task_id": "R1-T06",
                "run_id": "R1-T06-SYNTH",
                "code_commit": "a" * 40,
                "gate_status": {
                    "scientific_review_status": "pending",
                    "review_phase": "author_analysis_complete",
                    "readme_gate_updated": False,
                },
                "downstream_gate_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary, package


def _primary_row(
    step: str, w: int, q: float, n11: int, n10: int, n01: int, n00: int
) -> dict[str, str]:
    n = n11 + n10 + n01 + n00
    anchor = n11 + n10
    target = n11 + n01
    retention = n11 / anchor
    target_rate = target / n
    lift = retention / target_rate
    delta = retention - target_rate
    anchor_false = n01 + n00
    nonanchor = n01 / anchor_false
    anchor_rate = anchor / n
    child_rate = n11 / n
    return {
        "task_id": "R1-T06",
        "run_id": "R1-T06-SYNTH",
        "code_commit": "a" * 40,
        "step_id": step,
        "anchor_state": {
            "C_GIVEN_P": "P",
            "T_GIVEN_PC": "S_PC",
            "V_GIVEN_PCT": "S_PCT",
        }[step],
        "target_dimension": {"C_GIVEN_P": "C", "T_GIVEN_PC": "T", "V_GIVEN_PCT": "V"}[
            step
        ],
        "child_state": {
            "C_GIVEN_P": "S_PC",
            "T_GIVEN_PC": "S_PCT",
            "V_GIVEN_PCT": "S_PCVT",
        }[step],
        "W": str(w),
        "q": str(q),
        "K": "not_applicable",
        "required_dimensions": {
            "C_GIVEN_P": "P,C",
            "T_GIVEN_PC": "P,C,T",
            "V_GIVEN_PCT": "P,C,T,V",
        }[step],
        "denominator_scope": "step_specific_minimal_common_valid",
        "N": str(n),
        "n11": str(n11),
        "n10": str(n10),
        "n01": str(n01),
        "n00": str(n00),
        "anchor_true_count": str(anchor),
        "anchor_false_count": str(anchor_false),
        "target_true_count": str(target),
        "target_false_count": str(n10 + n00),
        "child_true_count": str(n11),
        "anchor_rate": str(anchor_rate),
        "target_marginal_rate": str(target_rate),
        "child_joint_rate": str(child_rate),
        "retention": str(retention),
        "nonanchor_target_rate": str(nonanchor),
        "lift": str(lift),
        "delta": str(delta),
        "delta_nonanchor": str(retention - nonanchor),
        "independence_expected_joint_rate": str(anchor_rate * target_rate),
        "joint_excess": str(child_rate - anchor_rate * target_rate),
        "retention_denominator_zero": "false",
        "lift_denominator_zero": "false",
        "nonanchor_denominator_zero": "false",
        "nonzero_year_count": "2",
        "positive_delta_year_count": "2",
        "negative_delta_year_count": "0",
        "undefined_year_count": "0",
        "max_year_denominator_share": "0.5",
        "pooled_vs_year_median_sign_consistency": "true",
        "association_direction": "positive_same_time_association",
        "warnings": "",
    }


def _year_rows(primary: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in primary:
        for year in ("2020", "2021"):
            rows.append(
                {
                    "step_id": row["step_id"],
                    "W": row["W"],
                    "q": row["q"],
                    "year": year,
                    "N": str(int(row["N"]) // 2),
                    "n11": str(int(row["n11"]) // 2),
                    "n10": str(int(row["n10"]) // 2),
                    "n01": str(int(row["n01"]) // 2),
                    "n00": str(int(row["n00"]) // 2),
                    "anchor_true_count": row["anchor_true_count"],
                    "target_true_count": row["target_true_count"],
                    "retention": row["retention"],
                    "target_marginal_rate": row["target_marginal_rate"],
                    "lift": row["lift"],
                    "delta": row["delta"],
                    "delta_nonanchor": row["delta_nonanchor"],
                    "year_share_of_step_denominator": "0.5",
                }
            )
    return rows


def _security_rows(primary: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "step_id": row["step_id"],
            "W": row["W"],
            "q": row["q"],
            "security_count_total": "800",
            "retention_computable_security_count": "800",
            "lift_computable_security_count": "800",
            "anchor_count_q25": "1",
            "anchor_count_median": "2",
            "anchor_count_q75": "3",
            "retention_q25": row["retention"],
            "retention_median": row["retention"],
            "retention_q75": row["retention"],
            "lift_q25": row["lift"],
            "lift_median": row["lift"],
            "lift_q75": row["lift"],
            "delta_q25": row["delta"],
            "delta_median": row["delta"],
            "delta_q75": row["delta"],
            "positive_delta_security_share": "1",
            "negative_delta_security_share": "0",
            "pooled_vs_security_median_sign_consistency": "true",
        }
        for row in primary
    ]


def _nested_rows() -> list[dict[str, str]]:
    rows = []
    for w in WS:
        for q in QS:
            for state, count in (("S_P", 1), ("S_PC", 2), ("S_PCT", 3), ("S_PCVT", 4)):
                rows.append(
                    {
                        "W": str(w),
                        "q": str(q),
                        "state_name": state,
                        "required_dimension_count": str(count),
                        "common_valid_row_count": "100",
                        "derived_true_count": "20",
                        "r0_true_count": "20",
                        "derived_false_count": "80",
                        "r0_false_count": "80",
                        "derived_null_count": "0",
                        "r0_null_count": "0",
                        "missing_key_count": "0",
                        "row_mismatch_count": "0",
                        "true_count_mismatch": "false",
                        "false_count_mismatch": "false",
                        "null_count_mismatch": "false",
                    }
                )
    return rows


def _q_nesting_rows() -> list[dict[str, str]]:
    rows = []
    for scope_id in ("P", "C", "T", "V"):
        for w in WS:
            for q_low, q_high in (("0.1", "0.2"), ("0.2", "0.3")):
                rows.append(_q_nesting_row("dimension_active", scope_id, w, q_low, q_high))
    for scope_type in ("anchor_active", "child_active", "denominator_keys"):
        for step in STEPS:
            for w in WS:
                for q_low, q_high in (("0.1", "0.2"), ("0.2", "0.3")):
                    rows.append(_q_nesting_row(scope_type, step, w, q_low, q_high))
    return rows


def _q_nesting_row(
    scope_type: str, scope_id: str, w: int, q_low: str, q_high: str
) -> dict[str, str]:
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "W": str(w),
        "q_low": q_low,
        "q_high": q_high,
        "lower_set_count": "10",
        "higher_set_count": "12",
        "missing_from_higher_q_count": "0",
        "missing_from_lower_q_count": "0",
        "symmetric_difference_count": "0",
    }


def _dimension_rows() -> list[dict[str, str]]:
    rows = []
    for dimension in ("P", "C", "T", "V"):
        for w in WS:
            for q in QS:
                rows.append(
                    {
                        "dimension": dimension,
                        "W": str(w),
                        "q": str(q),
                        "r0_t06_row_count": "100",
                        "state_eligible_count": "80",
                        "state_active_true_count": "20",
                        "state_active_false_count": "60",
                        "state_active_null_count": "20",
                        "score_eligible_count": "80",
                        "recomputed_active_true_count": "20",
                        "recomputed_active_false_count": "60",
                        "recomputed_active_null_count": "20",
                        "active_mismatch_count": "0",
                    }
                )
    return rows


def _refresh_summary_hash(root: Path, summary: Path, role: str) -> None:
    payload = json.loads(summary.read_text(encoding="utf-8"))
    path = root / payload["output_paths"][role]["path"]
    payload["output_paths"][role]["sha256"] = _sha(path)
    summary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
