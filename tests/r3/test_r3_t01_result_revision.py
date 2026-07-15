import copy
import json
import unittest
from pathlib import Path

from src.r3.r3_t01_result_analysis import _metrics, _scan_pathologies
from src.r3.r3_t01_validator import validate_in_memory

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"


def _attempt(
    attempt_id: str,
    date: str,
    ordinal: int,
    *,
    state_version_id: str = "STATE",
    event_id: str = "EV1",
) -> dict[str, object]:
    return {
        "state_version_id": state_version_id,
        "event_id": event_id,
        "security_id": "SEC_A",
        "exit_attempt_id": attempt_id,
        "exit_attempt_date": date,
        "exit_attempt_ordinal": ordinal,
    }


class R3T01ResultRevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.report = validate_in_memory(cls.config, cls.fixture, root=ROOT)
        cls.s12 = next(
            item
            for item in cls.report.synthetic_case_results
            if item["case_id"] == "S12"
        )

    def _metrics_for(self, cases: list[dict[str, object]]) -> dict[str, object]:
        return _metrics(
            self.config,
            {"cases": cases},
            {"cases": cases},
            [
                {"status": "passed", "actual_error_codes": "M01"},
                {"status": "passed", "actual_error_codes": "M02"},
            ],
            {"anomaly_count": 0},
        )

    def _upstream(self) -> dict[str, object]:
        return {
            "reviewed_implementation_sha": "sha",
            "formal_execution_sha": "sha",
            "required_artifacts": [
                {
                    "path": item["path"],
                    "committed_byte_sha256": item["committed_byte_sha256"],
                }
                for item in self.config["upstream_binding"]["required_artifacts"]
            ],
        }

    def _pathology_codes(self, cases: list[dict[str, object]]) -> set[str]:
        findings = _scan_pathologies(
            self.config,
            {"cases": cases},
            {"cases": cases},
            [
                {"status": "passed", "actual_error_codes": "M01"},
                {"status": "passed", "actual_error_codes": "M02"},
            ],
            self._upstream(),
        )
        return {item["code"] for item in findings}

    def test_result_analyzer_scopes_id_uniqueness_by_case(self) -> None:
        cases = [
            {
                "case_id": "CASE_A",
                "actual_attempts": [_attempt("shared", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
            {
                "case_id": "CASE_B",
                "actual_attempts": [_attempt("shared", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
        ]
        metrics = self._metrics_for(cases)
        self.assertEqual(
            metrics["id_uniqueness_by_case"], {"CASE_A": True, "CASE_B": True}
        )
        self.assertTrue(metrics["id_uniqueness"])

    def test_cross_case_identity_reuse_is_not_duplicate(self) -> None:
        cases = [
            {
                "case_id": "CASE_A",
                "actual_attempts": [_attempt("shared", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
            {
                "case_id": "CASE_B",
                "actual_attempts": [_attempt("shared", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
        ]
        metrics = self._metrics_for(cases)
        self.assertEqual(metrics["cross_case_identity_reuse_count"], 1)
        self.assertNotIn("CASE_ATTEMPT_ID_NOT_UNIQUE", self._pathology_codes(cases))

    def test_result_analyzer_scopes_ordinal_conservation_by_case(self) -> None:
        cases = [
            {
                "case_id": "CASE_A",
                "actual_attempts": [_attempt("a", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
            {
                "case_id": "CASE_B",
                "actual_attempts": [_attempt("b", "2024-01-02", 1)],
                "case_execution": {"executed_assertion_count": 1},
            },
        ]
        metrics = self._metrics_for(cases)
        self.assertEqual(
            metrics["ordinal_conservation_by_case"],
            {"CASE_A": True, "CASE_B": True},
        )
        self.assertTrue(metrics["ordinal_conservation"])

    def test_case_local_duplicate_id_is_detected(self) -> None:
        cases = [
            {
                "case_id": "CASE_A",
                "actual_attempts": [
                    _attempt("duplicate", "2024-01-02", 1),
                    _attempt("duplicate", "2024-01-03", 2),
                ],
                "case_execution": {"executed_assertion_count": 1},
            }
        ]
        self.assertIn("CASE_ATTEMPT_ID_NOT_UNIQUE", self._pathology_codes(cases))

    def test_case_local_ordinal_gap_is_detected(self) -> None:
        cases = [
            {
                "case_id": "CASE_A",
                "actual_attempts": [
                    _attempt("a", "2024-01-02", 1),
                    _attempt("b", "2024-01-03", 3),
                ],
                "case_execution": {"executed_assertion_count": 1},
            }
        ]
        self.assertIn(
            "CASE_ATTEMPT_ORDINAL_NOT_CONSERVED", self._pathology_codes(cases)
        )

    def test_non_executable_synthetic_case_fails_closed(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        fixture["cases"].append(
            {
                "case_id": "TEXT_ONLY",
                "description": "description is not an executable assertion",
                "expected": {
                    "attempt_count": 0,
                    "attempts": [],
                    "rejection_codes": [],
                },
                "lifecycle_assertion": "text only",
            }
        )
        report = validate_in_memory(
            self.config, fixture, root=ROOT, check_upstream=False
        )
        self.assertIn(
            "SYNTHETIC_CASE_NOT_EXECUTABLE",
            {item["code"] for item in report.errors},
        )

    def test_text_only_assertion_does_not_count_as_execution(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        fixture["cases"].append(
            {
                "case_id": "TEXT_ONLY",
                "expected": {"attempt_count": 0, "attempts": []},
                "lifecycle_assertion": "must be checked",
            }
        )
        report = validate_in_memory(
            self.config, fixture, root=ROOT, check_upstream=False
        )
        result = next(
            item
            for item in report.synthetic_case_results
            if item["case_id"] == "TEXT_ONLY"
        )
        self.assertEqual(result["executed_assertion_count"], 0)
        self.assertFalse(result["lifecycle_checked"])
        self.assertEqual(result["case_status"], "not_executable")

    def test_horizon_positive_case_has_h5_h10_h20_h30(self) -> None:
        self.assertEqual(self.s12["actual_attempt_count"], 1)
        landmark = next(iter(self.s12["landmarks"].values()))
        self.assertTrue(
            all(landmark[key]["available"] for key in ("H5", "H10", "H20", "H30"))
        )

    def test_horizon_exact_dates_match_valid_trading_ordinals(self) -> None:
        landmark = next(iter(self.s12["landmarks"].values()))
        expected = {
            "T0": "2024-01-02",
            "T1": "2024-01-04",
            "T2": "2024-01-08",
            "H5": "2024-01-12",
            "H10": "2024-01-19",
            "H20": "2024-02-02",
            "H30": "2024-02-16",
        }
        self.assertEqual(
            {key: landmark[key]["trade_date"] for key in expected}, expected
        )

    def test_invalid_future_rows_do_not_count_toward_horizon(self) -> None:
        landmark = next(iter(self.s12["landmarks"].values()))
        self.assertEqual(landmark["T1"]["intervening_unobservable_row_count"], 1)
        self.assertEqual(landmark["T2"]["intervening_unobservable_row_count"], 2)
        self.assertEqual(landmark["H5"]["valid_expected_row_count"], 5)
        self.assertEqual(landmark["H30"]["valid_expected_row_count"], 30)

    def test_all_horizon_availability_zero_blocks_analysis(self) -> None:
        case = {
            "case_id": "NO_HORIZONS",
            "actual_attempts": [],
            "case_execution": {"executed_assertion_count": 1},
            "landmarks": {
                "attempt": {
                    "state_version_id": "STATE",
                    "security_id": "SEC_A",
                    "t0_date": "2024-01-02",
                    **{
                        key: {"available": False} for key in ("H5", "H10", "H20", "H30")
                    },
                }
            },
        }
        codes = self._pathology_codes([case])
        self.assertIn("ALL_HORIZON_AVAILABILITY_ZERO", codes)
        self.assertIn("HORIZON_AVAILABILITY_ZERO", codes)


if __name__ == "__main__":
    unittest.main()
