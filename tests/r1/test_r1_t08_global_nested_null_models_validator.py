from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

from src.r1.r1_t08_global_nested_null_models import _test_registry
from src.r1.r1_t08_global_nested_null_models_validator import (
    _check_reconciliation,
    _check_replicates,
    _check_results,
)
from src.r1.r1_t08_null_engine import extreme_count, percentile_interval


class R1T08ValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            Path("configs/r1/r1_t08_global_nested_null_models.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.tests = _test_registry(config["candidate_registry"])

    def test_registry_moves_only_preregistered_component_layers(self) -> None:
        index = {row["null_model_id"]: row for row in self.tests[:5]}
        self.assertEqual(index["GLOBAL_PCT_SYNC"]["shifted_layers"], "C,T")
        self.assertEqual(index["GLOBAL_PCVT_SYNC"]["shifted_layers"], "C,T,V")
        self.assertEqual(index["C_GIVEN_P"]["shifted_layers"], "C")
        self.assertEqual(index["T_GIVEN_PC"]["shifted_layers"], "T")
        self.assertEqual(index["V_GIVEN_PCT"]["shifted_layers"], "V")
        self.assertTrue(all("S_PCT" not in row["shifted_layers"] for row in self.tests))

    def test_replicate_validator_rejects_missing_duplicate_and_failed_rows(
        self,
    ) -> None:
        test = self.tests[0]
        rows = [self._replicate(test, index) for index in (1, 2, 2)]
        rows[0]["failed_flag"] = "1"
        errors: list[str] = []
        _check_replicates([test], rows, 3, errors)
        self.assertTrue(any("replicate_id_incomplete" in error for error in errors))
        self.assertTrue(any("replicate_id_duplicate" in error for error in errors))
        self.assertTrue(any("failed_replicate" in error for error in errors))

    def test_result_validator_recomputes_tail_p_interval_and_effect(self) -> None:
        test = self.tests[0]
        values = np.array([0.1, 0.2, 0.4])
        replicates = [
            self._replicate(test, index + 1, value=value)
            for index, value in enumerate(values)
        ]
        observed = 0.3
        low, high = percentile_interval(values)
        extreme = extreme_count(values, observed, "upper")
        result = self._result(
            test,
            observed=observed,
            mean=float(np.mean(values)),
            median=float(np.median(values)),
            low=low,
            high=high,
            extreme=extreme,
            empirical_p=(extreme + 1) / 4,
        )
        errors: list[str] = []
        _check_results([test], replicates, [result] * 3, 3, errors)
        self.assertTrue(any("result_duplicate" in error for error in errors))
        self.assertTrue(any("result_row_count_mismatch" in error for error in errors))

        bad = deepcopy(result)
        bad["tail"] = "lower"
        bad["n_extreme"] = "0"
        bad["empirical_p"] = "0.0"
        errors = []
        _check_results([test], replicates, [bad], 3, errors)
        self.assertTrue(any("tail_mismatch" in error for error in errors))
        self.assertTrue(any("n_extreme_mismatch" in error for error in errors))
        self.assertTrue(any("empirical_p" in error for error in errors))

    def test_reconciliation_rejects_funnel_and_parent_child_violations(self) -> None:
        rows = []
        for W in ("120", "250"):
            for state, true_count in (("S_PCT", "2"), ("S_PCVT", "1")):
                rows.append(self._reconciliation(W, state, true_count))
        rows[1]["raw_state_true_count"] = "3"
        rows[2]["raw_state_null_count"] = "2"
        errors: list[str] = []
        _check_reconciliation(rows, errors)
        self.assertTrue(any("parent_child_invariant" in error for error in errors))
        self.assertTrue(any("observed_funnel" in error for error in errors))

    @staticmethod
    def _replicate(
        test: dict[str, object], index: int, value: float = 0.2
    ) -> dict[str, str]:
        return {
            "test_group_id": str(test["test_group_id"]),
            "replicate_id": str(index),
            "N_perm": "3",
            "failed_flag": "0",
            "offset_plan_hash": "a" * 64,
            "confirmed_coverage": str(value),
            "duration_mean": str(value),
            "duration_median": str(value),
            "fragment_rate": str(value),
            "nested_retention": str(value),
        }

    @staticmethod
    def _result(
        test: dict[str, object],
        *,
        observed: float,
        mean: float,
        median: float,
        low: float,
        high: float,
        extreme: int,
        empirical_p: float,
    ) -> dict[str, str]:
        sd = float(np.std([0.1, 0.2, 0.4], ddof=1))
        return {
            "test_group_id": str(test["test_group_id"]),
            "statistic_name": "confirmed_coverage",
            "tail": "upper",
            "observed_value": str(observed),
            "null_mean": str(mean),
            "null_median": str(median),
            "null_interval_low": str(low),
            "null_interval_high": str(high),
            "observed_null_ratio": str(observed / mean),
            "observed_null_difference": str(observed - mean),
            "n_extreme": str(extreme),
            "empirical_p": str(empirical_p),
            "z_score_descriptive": str((observed - mean) / sd),
            "failed_simulation_count": "0",
        }

    @staticmethod
    def _reconciliation(W: str, state: str, true_count: str) -> dict[str, str]:
        row = {
            "W": W,
            "state_line": state,
            "key_count": "4",
            "raw_state_true_count": true_count,
            "raw_state_false_count": str(4 - int(true_count)),
            "raw_state_null_count": "0",
            "confirmation_time_consistency": "passed",
        }
        for field in (
            "missing_key_count",
            "extra_key_count",
            "raw_state_mismatch_count",
            "confirmed_state_mismatch_count",
            "interval_mismatch_count",
            "upstream_profile_mismatch_count",
            "upstream_nested_mismatch_count",
        ):
            row[field] = "0"
        return row


if __name__ == "__main__":
    unittest.main()
