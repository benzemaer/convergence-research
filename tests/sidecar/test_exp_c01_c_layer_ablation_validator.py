from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.sidecar.exp_c01_c_layer_ablation import (
    CSV_FIELDS,
    OUTPUT_FILES,
)
from src.sidecar.exp_c01_c_layer_ablation_validator import (
    scan_anomalies,
    validate_baseline_reconciliation,
    validate_manifest,
    validate_static_config,
)


def source_row(date: str, indicator_id: str, score: float) -> dict[str, object]:
    return {
        "security_id": "000001.SZ",
        "trading_date": date,
        "percentile_window_W": 120,
        "indicator_id": indicator_id,
        "score": score,
        "eligible": True,
        "validity_status": "valid",
    }


def fixture_rows() -> list[dict[str, object]]:
    return [
        source_row("2023-01-01", "C1_LogMASpread_5_60", 0.90),
        source_row("2023-01-01", "C2_AdjVWAPSpread_5_60", 0.70),
        source_row("2023-01-02", "C1_LogMASpread_5_60", 0.90),
        source_row("2023-01-02", "C2_AdjVWAPSpread_5_60", 0.50),
        source_row("2024-01-01", "C1_LogMASpread_5_60", 0.50),
        source_row("2024-01-01", "C2_AdjVWAPSpread_5_60", 0.90),
        source_row("2024-01-02", "C1_LogMASpread_5_60", 0.80),
        source_row("2024-01-02", "C2_AdjVWAPSpread_5_60", 0.80),
    ]


class ExpC01ValidatorTest(unittest.TestCase):
    def test_q_mismatch_and_forbidden_output_field_are_rejected(self) -> None:
        config = {
            "task_id": "EXP-C01",
            "parameters": {"W": 120, "q": 0.3, "weak_delta": 0.1},
            "denominator_scope": "pair_common_valid",
            "variants": [],
        }
        self.assertIn("config_q_mismatch", validate_static_config(config))

        from src.sidecar.exp_c01_c_layer_ablation_validator import _validate_csv_headers

        errors = _validate_csv_headers(
            "variant_profile", ("variant_id", "future_return")
        )
        self.assertTrue(any("forbidden_field" in error for error in errors))

    def test_reconciliation_mutation_is_caught(self) -> None:
        passed = {
            "expected_key_count": 2,
            "dimension_score_key_count": 2,
            "dimension_state_key_count": 2,
            "key_count": 2,
            "key_count_mismatch": 0,
            "score_mean_mismatch": 0,
            "score_min_mismatch": 0,
            "eligible_mismatch": 0,
            "active_mismatch": 0,
            "validity_mismatch": 0,
            "dimension_validity_mismatch": 0,
            "state_validity_mismatch": 0,
            "mismatch_total": 0,
            "status": "passed",
        }
        self.assertEqual(validate_baseline_reconciliation(passed), [])
        mutated = copy.deepcopy(passed)
        mutated["score_mean_mismatch"] = 1
        self.assertIn(
            "reconciliation_nonzero:score_mean_mismatch",
            validate_baseline_reconciliation(mutated),
        )

    def test_anomaly_scan_catches_all_zero_all_one_all_null_and_identical(self) -> None:
        headers = (
            "variant_id",
            "eligible_row_count",
            "active_true_count",
            "active_false_count",
        )
        all_zero = {
            "variant_profile": (
                headers,
                [
                    {
                        "variant_id": name,
                        "eligible_row_count": "2",
                        "active_true_count": "0",
                        "active_false_count": "2",
                    }
                    for name in ("baseline_pair", "c1_only", "c2_only")
                ],
            ),
            "overlap_profile": ((), []),
            "year_profile": ((), []),
            "security_profile": ((), []),
            "availability_profile": ((), []),
        }
        result = scan_anomalies(all_zero)
        self.assertTrue(any(item["code"] == "all_zero" for item in result["anomalies"]))

        all_one = copy.deepcopy(all_zero)
        all_one["variant_profile"] = (
            headers,
            [
                {
                    "variant_id": name,
                    "eligible_row_count": "2",
                    "active_true_count": "2",
                    "active_false_count": "0",
                }
                for name in ("baseline_pair", "c1_only", "c2_only")
            ],
        )
        result = scan_anomalies(all_one)
        self.assertTrue(any(item["code"] == "all_one" for item in result["anomalies"]))

        all_null = copy.deepcopy(all_zero)
        all_null["variant_profile"] = (
            headers,
            [
                {
                    "variant_id": name,
                    "eligible_row_count": "",
                    "active_true_count": "",
                    "active_false_count": "",
                }
                for name in ("baseline_pair", "c1_only", "c2_only")
            ],
        )
        result = scan_anomalies(all_null)
        self.assertTrue(any(item["code"] == "all_null" for item in result["anomalies"]))

        identical = copy.deepcopy(all_zero)
        identical["variant_profile"] = (
            headers,
            [
                {
                    "variant_id": name,
                    "eligible_row_count": "2",
                    "active_true_count": "1",
                    "active_false_count": "1",
                }
                for name in ("baseline_pair", "c1_only", "c2_only")
            ],
        )
        identical["overlap_profile"] = (
            ("symmetric_difference_count",),
            [{"symmetric_difference_count": "0"}] * 3,
        )
        result = scan_anomalies(identical)
        self.assertTrue(
            any(
                item["code"] == "three_variants_identical"
                for item in result["anomalies"]
            )
        )

    def test_manifest_hash_and_row_count_mutations_are_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            for key, fields in CSV_FIELDS.items():
                (output / OUTPUT_FILES[key]).write_text(
                    ",".join(fields) + "\n",
                    encoding="utf-8",
                )
            analysis = output / OUTPUT_FILES["result_analysis"]
            analysis.write_text("# analysis\n", encoding="utf-8")
            input_path = root / "input.duckdb"
            input_path.write_bytes(b"synthetic")
            config_path = root / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")

            files = {}
            for key in (
                "variant_profile",
                "overlap_profile",
                "score_comparison",
                "year_profile",
                "security_profile",
                "availability_profile",
                "result_analysis",
            ):
                path = output / OUTPUT_FILES[key]
                files[path.name] = {
                    "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "row_count": 0 if path.suffix == ".csv" else 1,
                }
            manifest = {
                "task_id": "EXP-C01",
                "parameters": {"W": 120, "q": 0.2},
                "variants": ["baseline_pair", "c1_only", "c2_only"],
                "denominator_scope": "pair_common_valid",
                "variant_rules": {
                    "baseline_pair": (
                        "pair_valid AND score_C_mean >= 0.80 AND score_C_min >= 0.70"
                    ),
                    "c1_only": "C1 valid AND score_C1 >= 0.80",
                    "c2_only": "C2 valid AND score_C2 >= 0.80",
                },
                "input_availability": {
                    "C1_LogMASpread_5_60": {
                        "input_row_count": 0,
                        "native_valid_count": 0,
                        "native_invalid_count": 0,
                        "pair_common_valid_count": 0,
                        "availability_gain_vs_pair": 0,
                    },
                    "C2_AdjVWAPSpread_5_60": {
                        "input_row_count": 0,
                        "native_valid_count": 0,
                        "native_invalid_count": 0,
                        "pair_common_valid_count": 0,
                        "availability_gain_vs_pair": 0,
                    },
                    "pair_common_valid": {
                        "input_row_count": 0,
                        "native_valid_count": 0,
                        "native_invalid_count": 0,
                        "pair_common_valid_count": 0,
                        "availability_gain_vs_pair": 0,
                    },
                },
                "baseline_reconciliation": {
                    "expected_key_count": 0,
                    "dimension_score_key_count": 0,
                    "dimension_state_key_count": 0,
                    "key_count": 0,
                    "key_count_mismatch": 0,
                    "score_mean_mismatch": 0,
                    "score_min_mismatch": 0,
                    "eligible_mismatch": 0,
                    "active_mismatch": 0,
                    "validity_mismatch": 0,
                    "dimension_validity_mismatch": 0,
                    "state_validity_mismatch": 0,
                    "mismatch_total": 0,
                    "status": "passed",
                },
                "files": files,
                "input_artifacts": {
                    "synthetic": {
                        "path": str(input_path),
                        "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                        "row_count": 0,
                    }
                },
                "config": {
                    "path": str(config_path),
                    "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                },
            }
            self.assertEqual(validate_manifest(manifest, output), [])
            mutated_hash = copy.deepcopy(manifest)
            mutated_hash["files"][OUTPUT_FILES["result_analysis"]]["sha256"] = "0" * 64
            self.assertIn(
                f"manifest_hash_mismatch:{OUTPUT_FILES['result_analysis']}",
                validate_manifest(mutated_hash, output),
            )
            mutated_rows = copy.deepcopy(manifest)
            mutated_rows["files"][OUTPUT_FILES["result_analysis"]]["row_count"] = 99
            self.assertIn(
                f"manifest_row_count_mismatch:{OUTPUT_FILES['result_analysis']}",
                validate_manifest(mutated_rows, output),
            )


if __name__ == "__main__":
    unittest.main()
