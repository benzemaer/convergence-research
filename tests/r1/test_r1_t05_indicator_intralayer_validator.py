from __future__ import annotations

import csv
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from src.r1.r1_t05_indicator_intralayer_diagnostics_validator import (
    R1T05ValidationError,
    validate_r1_t05_indicator_intralayer_diagnostics,
)

INDICATORS = [
    ("P", "A", "P1_NATR14", "P1_NATR14"),
    ("P", "B", "P2_LogRange20", "P2_LogRange20"),
    ("C", "A", "C1_LogMASpread_5_60", "C1_LogMASpread_5_60"),
    ("C", "B", "C2_AdjVWAPSpread_5_60", "C2_AdjVWAPSpread_5_60"),
    ("T", "A", "T1_ER20", "T1_ER20"),
    ("T", "B", "T2_AbsTrendT20", "T2_AbsTrendT20"),
    ("V", "A", "V1_TurnoverShrink20_60", "V1_TurnoverShrink20_60"),
    ("V", "B", "V2_AmountLevel20Pct", "V2_LogAmount20_base"),
]
LAYERS = [
    ("P", "P1_NATR14", "P2_LogRange20"),
    ("C", "C1_LogMASpread_5_60", "C2_AdjVWAPSpread_5_60"),
    ("T", "T1_ER20", "T2_AbsTrendT20"),
    ("V", "V1_TurnoverShrink20_60", "V2_AmountLevel20Pct"),
]
WS = (120, 250, 500)
QS = (0.1, 0.2, 0.3)


class R1T05ValidatorTest(unittest.TestCase):
    def test_complete_author_draft_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            result = validate_r1_t05_indicator_intralayer_diagnostics(
                summary_path=summary,
                result_package_path=package,
                root=root,
            )
            self.assertEqual(result["validator_status"], "passed")

    def test_threshold_accounting_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            threshold = root / "r1_t05_intralayer_threshold_structure.csv"
            rows = _read_rows(threshold)
            rows[0]["neither"] = str(int(rows[0]["neither"]) + 1)
            _write_csv(threshold, rows)
            _refresh_summary_hash(root, summary, "intralayer_threshold_structure_csv")
            with self.assertRaises(R1T05ValidationError) as raised:
                validate_r1_t05_indicator_intralayer_diagnostics(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("threshold_2x2_sum_mismatch", str(raised.exception))

    def test_hit_denominator_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            hit_path = root / "r1_t05_indicator_hit_duration.csv"
            rows = _read_rows(hit_path)
            rows[0]["eligible_day_count"] = rows[0]["total_row_count"]
            rows[0]["ineligible_day_count"] = "0"
            rows[0]["hit_rate"] = rows[0]["coverage"]
            _write_csv(hit_path, rows)
            _refresh_summary_hash(root, summary, "indicator_hit_duration_csv")
            with self.assertRaises(R1T05ValidationError) as raised:
                validate_r1_t05_indicator_intralayer_diagnostics(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("indicator_hit_denominator_mismatch", str(raised.exception))

    def test_percentile_bucket_sum_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            bucket_path = root / "r1_t05_indicator_percentile_bucket_distribution.csv"
            rows = _read_rows(bucket_path)
            rows[0]["bucket_count"] = str(int(rows[0]["bucket_count"]) + 1)
            _write_csv(bucket_path, rows)
            _refresh_summary_hash(
                root, summary, "indicator_percentile_bucket_distribution_csv"
            )
            with self.assertRaises(R1T05ValidationError) as raised:
                validate_r1_t05_indicator_intralayer_diagnostics(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("percentile_bucket_count_sum_mismatch", str(raised.exception))

    def test_reason_occurrence_share_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            reason_path = root / "r1_t05_validity_reason_profile.csv"
            rows = _read_rows(reason_path)
            rows[0]["reason_occurrence_share"] = "0.25"
            _write_csv(reason_path, rows)
            _refresh_summary_hash(root, summary, "validity_reason_profile_csv")
            with self.assertRaises(R1T05ValidationError) as raised:
                validate_r1_t05_indicator_intralayer_diagnostics(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn(
                "validity_reason_occurrence_share_mismatch", str(raised.exception)
            )

    def test_scientific_review_must_remain_pending_in_author_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            payload = json.loads(package.read_text(encoding="utf-8"))
            payload["gate_status"]["scientific_review_status"] = "passed"
            package.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(R1T05ValidationError) as raised:
                validate_r1_t05_indicator_intralayer_diagnostics(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("scientific_review_not_pending", str(raised.exception))


def _write_fixture(root: Path) -> tuple[Path, Path]:
    raw_rows = []
    for layer, role, indicator, raw_source in INDICATORS:
        raw_rows.append(
            {
                "layer": layer,
                "role": role,
                "indicator_id": indicator,
                "raw_source_indicator_id": raw_source,
                "raw_metric_name": "LogAmount20"
                if indicator == "V2_AmountLevel20Pct"
                else indicator,
                "total_row_count": "1730769",
                "valid_count": "1659385"
                if indicator == "C2_AdjVWAPSpread_5_60"
                else "1700000",
                "unknown_count": "38879"
                if indicator == "C2_AdjVWAPSpread_5_60"
                else "30000",
                "diagnostic_required_count": "0",
                "blocked_count": "32505"
                if indicator == "C2_AdjVWAPSpread_5_60"
                else "769",
                "raw_value_null_count": "30000",
                "valid_ratio": "0.95",
                "missing_ratio": "0.02",
                "unknown_ratio": "0.02",
                "blocked_ratio": "0.001",
                "mean": "1",
                "standard_deviation": "0.1",
                "minimum": "0",
                "q01": "0.01",
                "q05": "0.05",
                "q10": "0.1",
                "q20": "0.2",
                "q30": "0.3",
                "median": "0.5",
                "q90": "0.9",
                "q95": "0.95",
                "q99": "0.99",
                "maximum": "1",
                "raw_tail_ratio_outside_q01_q99": "0.02",
                "domain_violation_count": "0",
                "domain_violation_ratio": "0",
            }
        )
    _write_csv(root / "r1_t05_indicator_raw_distribution.csv", raw_rows)
    score_rows = []
    for layer, role, indicator, _ in INDICATORS:
        for w, eligible, unknown in zip(WS, (100, 80, 60), (0, 10, 20), strict=True):
            score_rows.append(
                {
                    "layer": layer,
                    "role": role,
                    "indicator_id": indicator,
                    "W": str(w),
                    "total_row_count": "100",
                    "eligible_count": str(eligible),
                    "ineligible_count": str(100 - eligible),
                    "valid_count": str(eligible),
                    "unknown_count": str(unknown),
                    "diagnostic_required_count": "0",
                    "blocked_count": "0",
                    "eligible_ratio": str(eligible / 100),
                    "percentile_mean": "0.5",
                    "percentile_std": "0.1",
                    "percentile_q01": "0.01",
                    "percentile_q05": "0.05",
                    "percentile_q10": "0.1",
                    "percentile_q20": "0.2",
                    "percentile_q30": "0.3",
                    "percentile_q50": "0.5",
                    "percentile_q90": "0.9",
                    "percentile_q95": "0.95",
                    "percentile_q99": "0.99",
                    "score_mean": "0.5",
                    "score_std": "0.1",
                    "score_q01": "0.01",
                    "score_q05": "0.05",
                    "score_q10": "0.1",
                    "score_q20": "0.2",
                    "score_q30": "0.3",
                    "score_q50": "0.5",
                    "score_q90": "0.9",
                    "score_q95": "0.95",
                    "score_q99": "0.99",
                    "percentile_tail_extreme_ratio": "0.02",
                    "reference_observation_count_min": str(w),
                    "reference_observation_count_max": str(w),
                    "score_formula_mismatch_count": "0",
                    "percentile_bounds_violation_count": "0",
                    "current_value_in_reference_set_true_count": "0",
                    "non_midrank_tie_method_count": "0",
                }
            )
    _write_csv(root / "r1_t05_indicator_score_distribution.csv", score_rows)
    bucket_rows = []
    buckets = [
        ("B00_00_01", "0", "0.01", "true", "true", 1),
        ("B01_01_05", "0.01", "0.05", "false", "true", 4),
        ("B02_05_10", "0.05", "0.10", "false", "true", 5),
        ("B03_10_20", "0.10", "0.20", "false", "true", 10),
        ("B04_20_30", "0.20", "0.30", "false", "true", 10),
        ("B05_30_50", "0.30", "0.50", "false", "true", 20),
        ("B06_50_90", "0.50", "0.90", "false", "true", 40),
        ("B07_90_95", "0.90", "0.95", "false", "true", 5),
        ("B08_95_99", "0.95", "0.99", "false", "true", 4),
        ("B09_99_100", "0.99", "1", "false", "true", 1),
    ]
    for layer, role, indicator, _ in INDICATORS:
        for w, eligible in zip(WS, (100, 80, 60), strict=True):
            for bucket_id, lower, upper, lower_inc, upper_inc, count in buckets:
                scaled_count = round(count * eligible / 100)
                bucket_rows.append(
                    {
                        "layer": layer,
                        "role": role,
                        "indicator_id": indicator,
                        "W": str(w),
                        "bucket_id": bucket_id,
                        "lower_bound": lower,
                        "upper_bound": upper,
                        "lower_inclusive": lower_inc,
                        "upper_inclusive": upper_inc,
                        "eligible_count": str(eligible),
                        "bucket_count": str(scaled_count),
                        "bucket_ratio_of_eligible": str(scaled_count / eligible),
                        "nominal_bucket_width": str(float(upper) - float(lower)),
                        "bucket_ratio_minus_nominal_width": "0",
                    }
                )
    _write_csv(
        root / "r1_t05_indicator_percentile_bucket_distribution.csv", bucket_rows
    )
    hit_rows = []
    for layer, role, indicator, _ in INDICATORS:
        for w in WS:
            for q, hits in zip(QS, (10, 20, 30), strict=True):
                hit_rows.append(
                    {
                        "layer": layer,
                        "role": role,
                        "indicator_id": indicator,
                        "W": str(w),
                        "q": str(q),
                        "total_row_count": "100",
                        "eligible_day_count": "80",
                        "ineligible_day_count": "20",
                        "hit_true_day_count": str(hits),
                        "hit_false_day_count": str(80 - hits),
                        "hit_null_day_count": "20",
                        "hit_rate": str(hits / 80),
                        "coverage": str(hits / 100),
                        "unique_security_count_hit": "10",
                        "nonzero_year_count": "2",
                        "segment_count": str(hits),
                        "strict_onset_count": str(hits - 1),
                        "left_censored_start_count": "1",
                        "total_hit_duration": str(hits),
                        "mean_duration": "1",
                        "std_duration": "0",
                        "min_duration": "1",
                        "q10": "1",
                        "q25": "1",
                        "q50": "1",
                        "q75": "1",
                        "q90": "1",
                        "q95": "1",
                        "q99": "1",
                        "max_duration": "1",
                        "single_day_segment_count": str(hits),
                        "single_day_fragment_ratio": "1",
                    }
                )
    _write_csv(root / "r1_t05_indicator_hit_duration.csv", hit_rows)
    corr_rows = []
    diag_rows = []
    threshold_rows = []
    for layer, a, b in LAYERS:
        for w in WS:
            corr_rows.append(
                {
                    "layer": layer,
                    "indicator_a": a,
                    "indicator_b": b,
                    "W": str(w),
                    "eligible_rows": "100",
                    "unique_security_count": "10",
                    "pooled_spearman_score": "0.5",
                    "pooled_spearman_percentile": "0.5",
                    "security_spearman_computable_count": "10",
                    "security_spearman_q25": "0.4",
                    "security_spearman_median": "0.5",
                    "security_spearman_q75": "0.6",
                    "positive_security_share": "1",
                    "negative_security_share": "0",
                    "zero_security_share": "0",
                    "pooled_vs_security_median_sign_consistency": "true",
                }
            )
            diag_rows.append(
                {
                    "layer": layer,
                    "indicator_a": a,
                    "indicator_b": b,
                    "W": str(w),
                    "common_eligible_rows": "100",
                    "unique_security_count": "10",
                    "pooled_spearman_score": "0.5",
                    "security_spearman_median": "0.5",
                    "q20_both_hit": "10",
                    "q20_indicator_a_only": "5",
                    "q20_indicator_b_only": "5",
                    "q20_neither": "80",
                    "q20_A_hit_count": "15",
                    "q20_B_hit_count": "15",
                    "q20_Jaccard": "0.5",
                    "diagnostic_status": "complementary_structure",
                }
            )
            for q, both, neither in zip(QS, (5, 10, 15), (85, 80, 75), strict=True):
                threshold_rows.append(
                    {
                        "layer": layer,
                        "indicator_a": a,
                        "indicator_b": b,
                        "W": str(w),
                        "q": str(q),
                        "common_eligible_rows": "100",
                        "both_hit": str(both),
                        "indicator_a_only": "5",
                        "indicator_b_only": "5",
                        "neither": str(neither),
                        "A_hit_count": str(both + 5),
                        "B_hit_count": str(both + 5),
                        "A_hit_rate": "0.15",
                        "B_hit_rate": "0.15",
                        "both_hit_rate": str(both / 100),
                        "A_given_B": "0.6666666666666666",
                        "B_given_A": "0.6666666666666666",
                        "Jaccard": "0.5",
                        "A_given_B_denominator_zero": "false",
                        "B_given_A_denominator_zero": "false",
                        "Jaccard_denominator_zero": "false",
                        "joint_segment_count": str(both),
                        "joint_strict_onset_count": str(both - 1),
                        "joint_left_censored_start_count": "1",
                        "joint_total_duration": str(both),
                        "joint_mean_duration": "1",
                        "joint_median_duration": "1",
                        "joint_q90_duration": "1",
                        "joint_q95_duration": "1",
                        "joint_max_duration": "1",
                        "joint_single_day_segment_count": str(both),
                        "joint_single_day_fragment_ratio": "1",
                    }
                )
    _write_csv(root / "r1_t05_intralayer_correlation.csv", corr_rows)
    _write_csv(root / "r1_t05_intralayer_threshold_structure.csv", threshold_rows)
    _write_csv(root / "r1_t05_intralayer_diagnostic_summary.csv", diag_rows)
    recon_rows = []
    for layer, role, indicator, _ in INDICATORS:
        for w in WS:
            for q in QS:
                recon_rows.append(
                    {
                        "layer": layer,
                        "role": role,
                        "indicator_id": indicator,
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
    _write_csv(root / "r1_t05_r0_t06_reconciliation.csv", recon_rows)
    _write_csv(
        root / "r1_t05_validity_reason_profile.csv",
        [
            {
                "source_level": "raw_metric",
                "layer": "P",
                "indicator_id": "P1_NATR14",
                "raw_source_indicator_id": "P1_NATR14",
                "W": "",
                "validity_status": "unknown",
                "reason_code": "window_insufficient",
                "total_row_count": "100",
                "reason_occurrence_count": "10",
                "row_count": "10",
                "row_prevalence": "0.1",
                "reason_occurrence_share": "1",
            }
        ],
    )
    checks = {
        "primary_output_nonempty": "passed",
        "c2_repaired_validity": "passed",
        "raw_domain": "passed",
        "score_formula": "passed",
        "w_availability_response": "passed",
        "indicator_hit_accounting": "passed",
        "percentile_bucket_distribution": "passed",
        "q_hit_nesting": "passed",
        "spearman_reconciliation": "passed",
        "threshold_accounting": "passed",
        "r0_t06_reconciliation": "passed",
        "validity_reason_denominator": "passed",
        "diagnostic_status_complete": "passed",
        "forbidden_output_tokens": "passed",
    }
    summary_payload = {
        "task_id": "R1-T05",
        "status": "completed",
        "run_id": "R1-T05-SYNTH",
        "code_commit": "a" * 40,
        "checks": checks,
        "blocked_reasons": [],
        "downstream_gates": {
            "R1-T06_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
        "output_paths": {},
    }
    for path in sorted(root.glob("r1_t05_*")):
        if path.suffix != ".csv":
            continue
        role = {
            "r1_t05_indicator_raw_distribution.csv": "indicator_raw_distribution_csv",
            "r1_t05_indicator_score_distribution.csv": (
                "indicator_score_distribution_csv"
            ),
            "r1_t05_indicator_percentile_bucket_distribution.csv": (
                "indicator_percentile_bucket_distribution_csv"
            ),
            "r1_t05_indicator_hit_duration.csv": "indicator_hit_duration_csv",
            "r1_t05_intralayer_correlation.csv": "intralayer_correlation_csv",
            "r1_t05_intralayer_threshold_structure.csv": (
                "intralayer_threshold_structure_csv"
            ),
            "r1_t05_intralayer_diagnostic_summary.csv": (
                "intralayer_diagnostic_summary_csv"
            ),
            "r1_t05_validity_reason_profile.csv": "validity_reason_profile_csv",
            "r1_t05_r0_t06_reconciliation.csv": "r0_t06_reconciliation_csv",
        }[path.name]
        summary_payload["output_paths"][role] = {
            "path": path.name,
            "sha256": _sha(path),
        }
    summary = root / "summary.json"
    summary.write_text(json.dumps(summary_payload, sort_keys=True), encoding="utf-8")
    package = root / "package.json"
    package.write_text(
        json.dumps(
            {
                "task_id": "R1-T05",
                "run_id": "R1-T05-SYNTH",
                "code_commit": "a" * 40,
                "gate_status": {"scientific_review_status": "pending"},
                "downstream_gate_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary, package


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
