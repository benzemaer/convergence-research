from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.sidecar.exp_c01_c_layer_ablation import (
    CSV_FIELDS,
    OUTPUT_FILES,
    build_profiles,
)
from src.sidecar.exp_c01_c_layer_ablation_validator import (
    _validate_result_analysis,
    recompute_readback_metrics,
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

    def test_independent_readback_recomputation_catches_formula_mutations(self) -> None:
        profiles = build_profiles(fixture_rows())
        artifacts = {key: (CSV_FIELDS[key], profiles[key]) for key in CSV_FIELDS}
        self.assertEqual(recompute_readback_metrics(artifacts)["status"], "passed")
        mutated = copy.deepcopy(artifacts)
        mutated["variant_profile"][1][0]["valid_step_count"] += 1
        result = recompute_readback_metrics(mutated)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "variant:baseline_pair:valid_step_count",
            result["mismatches"],
        )
        mutated_year = copy.deepcopy(artifacts)
        mutated_year["year_profile"][1][0]["jaccard"] = 0.0
        year_result = recompute_readback_metrics(mutated_year)
        self.assertEqual(year_result["status"], "failed")
        self.assertTrue(
            any(
                item.startswith("implied_intersection_mismatch:year:")
                for item in year_result["mismatches"]
            )
        )
        mutated_security = copy.deepcopy(artifacts)
        mutated_security["security_profile"][1][0]["baseline_retention"] = 0.0
        security_result = recompute_readback_metrics(mutated_security)
        self.assertEqual(security_result["status"], "failed")
        self.assertTrue(
            any(
                item.startswith("implied_intersection_mismatch:security:")
                for item in security_result["mismatches"]
            )
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

    def test_anomaly_scan_checks_candidate_identity_response_separately(self) -> None:
        artifacts = {
            "variant_profile": (
                (),
                [
                    {
                        "variant_id": "baseline_pair",
                        "eligible_row_count": "100",
                        "active_true_count": "100",
                        "active_false_count": "0",
                    },
                    {
                        "variant_id": "c1_only",
                        "eligible_row_count": "100",
                        "active_true_count": "100",
                        "active_false_count": "0",
                    },
                    {
                        "variant_id": "c2_only",
                        "eligible_row_count": "100",
                        "active_true_count": "10",
                        "active_false_count": "90",
                    },
                ],
            ),
            "overlap_profile": (
                (),
                [
                    {
                        "left_variant": "baseline_pair",
                        "right_variant": "c1_only",
                        "symmetric_difference_count": "0",
                    },
                    {
                        "left_variant": "baseline_pair",
                        "right_variant": "c2_only",
                        "symmetric_difference_count": "1",
                    },
                ],
            ),
            "year_profile": ((), []),
            "security_profile": ((), []),
            "availability_profile": ((), []),
        }
        result = scan_anomalies(artifacts)
        codes = {item["code"] for item in result["anomalies"]}
        self.assertIn("candidate_no_identity_response:c1_only", codes)
        self.assertNotIn("candidate_no_identity_response:c2_only", codes)
        self.assertIn("candidate_active_count_order_of_magnitude_shift", codes)

        five_x = copy.deepcopy(artifacts)
        five_x["variant_profile"][1][2]["active_true_count"] = "500"
        five_x["variant_profile"][1][2]["active_false_count"] = "0"
        five_x_result = scan_anomalies(five_x)
        self.assertIn(
            "candidate_active_count_order_of_magnitude_shift",
            {item["code"] for item in five_x_result["anomalies"]},
        )

    def test_anomaly_scan_uses_active_year_and_security_concentration(self) -> None:
        artifacts = {
            "variant_profile": (
                (),
                [
                    {
                        "variant_id": variant,
                        "eligible_row_count": "11",
                        "active_true_count": "10",
                        "active_false_count": "1",
                    }
                    for variant in ("baseline_pair", "c1_only", "c2_only")
                ],
            ),
            "overlap_profile": ((), []),
            "year_profile": (
                (),
                [
                    {
                        "calendar_year": "2023",
                        "candidate_variant": candidate,
                        "baseline_true_count": "9",
                        "candidate_true_count": "9",
                        "common_valid_rows": "10",
                    }
                    for candidate in ("c1_only", "c2_only")
                ]
                + [
                    {
                        "calendar_year": "2024",
                        "candidate_variant": candidate,
                        "baseline_true_count": "1",
                        "candidate_true_count": "1",
                        "common_valid_rows": "1",
                    }
                    for candidate in ("c1_only", "c2_only")
                ],
            ),
            "security_profile": (
                (),
                [
                    {
                        "security_id": "s1",
                        "candidate_variant": "c1_only",
                        "baseline_true_count": "10",
                        "candidate_true_count": "10",
                        "valid_row_count": "1",
                    },
                    {
                        "security_id": "s2",
                        "candidate_variant": "c1_only",
                        "baseline_true_count": "0",
                        "candidate_true_count": "0",
                        "valid_row_count": "9",
                    },
                ],
            ),
            "availability_profile": ((), []),
        }
        result = scan_anomalies(artifacts)
        codes = {item["code"] for item in result["anomalies"]}
        self.assertIn("year_active_concentration", codes)
        self.assertIn("baseline_security_active_concentration", codes)
        self.assertIn("candidate_security_active_concentration", codes)
        concentration = next(
            item
            for item in result["anomalies"]
            if item["code"] == "year_active_concentration"
        )
        self.assertEqual(concentration["detail"]["dominant_year"], 2023)
        self.assertAlmostEqual(concentration["detail"]["share"], 0.9)
        self.assertAlmostEqual(concentration["detail"]["max_year_active_share"], 0.9)
        self.assertEqual(concentration["detail"]["dominant_year_active_count"], 9)

    def test_result_analysis_requires_all_review_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.md"
            path.write_text("# incomplete\n", encoding="utf-8")
            errors = _validate_result_analysis(path)
        self.assertTrue(
            any(
                error.startswith("result_analysis_missing_section:") for error in errors
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
            import duckdb

            source_declarations = {
                "indicator_score": {
                    "path": "indicator.duckdb",
                    "table": "indicator_table",
                },
                "dimension_score": {
                    "path": "dimension.duckdb",
                    "table": "dimension_table",
                },
                "dimension_state": {
                    "path": "state.duckdb",
                    "table": "state_table",
                },
            }
            required_columns = {
                "indicator_score": [
                    "security_id",
                    "trading_date",
                    "percentile_window_W",
                    "indicator_id",
                    "score",
                    "eligible",
                    "validity_status",
                ],
                "dimension_score": [
                    "security_id",
                    "trading_date",
                    "percentile_window_W",
                    "dimension",
                    "score_dimension",
                    "score_dimension_min",
                    "eligible_dimension",
                    "validity_status",
                ],
                "dimension_state": [
                    "security_id",
                    "trading_date",
                    "percentile_window_W",
                    "q",
                    "weak_delta",
                    "dimension",
                    "dimension_active_weak",
                    "validity_status",
                ],
            }
            sql_types = {
                "security_id": "VARCHAR",
                "trading_date": "DATE",
                "percentile_window_W": "INTEGER",
                "indicator_id": "VARCHAR",
                "score": "DOUBLE",
                "eligible": "BOOLEAN",
                "validity_status": "VARCHAR",
                "dimension": "VARCHAR",
                "score_dimension": "DOUBLE",
                "score_dimension_min": "DOUBLE",
                "eligible_dimension": "BOOLEAN",
                "q": "DOUBLE",
                "weak_delta": "DOUBLE",
                "dimension_active_weak": "BOOLEAN",
            }
            source_manifest_artifacts = {}
            input_artifacts = {}
            for name, declaration in source_declarations.items():
                path = root / declaration["path"]
                columns = required_columns[name]
                con = duckdb.connect(str(path))
                con.execute(
                    f"CREATE TABLE {declaration['table']} ("
                    + ", ".join(f"{column} {sql_types[column]}" for column in columns)
                    + ")"
                )
                con.close()
                file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                source_declaration = {
                    **declaration,
                    "sha256": file_hash,
                    "row_count": 0,
                }
                source_manifest_artifacts[name] = source_declaration
                input_artifacts[name] = {
                    "filename": path.name,
                    "path": str(path),
                    "sha256": file_hash,
                    "row_count": 0,
                    "source_full_row_count": 0,
                    "query_filtered_row_count": 0,
                    "actual_table": declaration["table"],
                    "required_columns": columns,
                    "actual_columns": columns,
                    "source_manifest_declared_path": declaration["path"],
                    "source_manifest_declared_sha256": file_hash,
                    "source_manifest_declared_row_count": 0,
                    "source_manifest_declared_table": declaration["table"],
                }
            source_manifest = {
                "schema_version": "synthetic_source.v1",
                "input_artifacts": source_manifest_artifacts,
            }
            source_manifest_path = root / "source_manifest.json"
            source_manifest_path.write_text(
                json.dumps(source_manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
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
                "source_manifest_path": str(source_manifest_path),
                "source_manifest_sha256": hashlib.sha256(
                    source_manifest_path.read_bytes()
                ).hexdigest(),
                "source_manifest_schema_version": "synthetic_source.v1",
                "source_manifest_artifacts": source_manifest_artifacts,
                "input_artifacts": input_artifacts,
                "config": {
                    "path": str(config_path),
                    "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                },
            }
            self.assertEqual(validate_manifest(manifest, output), [])
            mutated_source = copy.deepcopy(manifest)
            mutated_source["source_manifest_sha256"] = "0" * 64
            self.assertIn(
                "manifest_source_manifest_hash_mismatch",
                validate_manifest(mutated_source, output),
            )
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
