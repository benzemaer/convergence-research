from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.validate_d3_release_gate import main, validate_d3_release_gate_payload

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/data_version_quality_manifest_gate_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class ValidateD3ReleaseGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)

    def valid_payload(self) -> dict[str, object]:
        gates = {
            gate["gate_id"]: "passed"
            for gate in self.contract["release_gates"]
            if gate["required_for_formal_release"]
        }
        gates.update(self.contract["current_blocking_gates"])
        data_version = {
            "data_version": "D3_SYNTHETIC_CSI800_20260105_rev001",
            "data_version_status": "candidate",
            "data_version_created_at": "2026-01-05T16:30:00Z",
            "data_version_created_by": "synthetic_d3_t06_test",
            "universe_id": "CSI800_STATIC_2026_06",
            "time_segment_id": "G0_T01",
            "observation_revision": "rev_001",
            "history_revision_class": "point_in_time_history",
            "research_use_tier": "formal",
            "source_snapshot_id": "synthetic_snapshot",
            "run_id": "synthetic_run",
            "candidate_manifest_ref": "manifest_ref",
            "quality_report_ref": "quality_report_ref",
            "row_count": 1,
            "security_count": 1,
            "trading_date_min": "2026-01-05",
            "trading_date_max": "2026-01-05",
            "sha256": "0" * 64,
        }
        manifest = {
            "manifest_id": "manifest_ref",
            "manifest_type": "d3_candidate_dataset_manifest",
            "manifest_version": "1.0.0",
            "manifest_created_at": "2026-01-05T16:31:00Z",
            "data_version": data_version["data_version"],
            "dataset_name": "d3.daily_market_observations.synthetic",
            "dataset_layer": "D3",
            "canonical_table": "d3.daily_market_observations",
            "value_layer_object": "d3.daily_market_observation_values",
            "universe_id": data_version["universe_id"],
            "time_segment_id": data_version["time_segment_id"],
            "row_count": 1,
            "security_count": 1,
            "trading_date_min": "2026-01-05",
            "trading_date_max": "2026-01-05",
            "observation_revision": "rev_001",
            "source_snapshot_refs": ["synthetic_snapshot"],
            "run_refs": ["synthetic_run"],
            "contract_refs": self.contract["depends_on"],
            "quality_report_ref": "quality_report_ref",
            "sha256": "1" * 64,
        }
        quality_report = {
            "quality_report_id": "quality_report_ref",
            "quality_report_version": "1.0.0",
            "data_version": data_version["data_version"],
            "quality_report_created_at": "2026-01-05T16:32:00Z",
            "quality_summary": {"release_gate_status": "blocked"},
            "quality_domain_summaries": {
                domain: {"status": "passed"}
                for domain in self.contract["quality_domains_required"]
            },
            "pcvt_input_readiness_summary": {
                indicator: {"status": "ready"}
                for indicator in self.contract["pcvt_readiness_indicators_required"]
            },
            "blocking_reasons": ["D2 formal materialization remains blocked"],
            "warning_reasons": [],
            "row_count": 1,
            "security_count": 1,
            "trading_date_min": "2026-01-05",
            "trading_date_max": "2026-01-05",
            "quality_blocking_row_count": 0,
            "quality_warning_row_count": 0,
            "unknown_status_count": 0,
            "diagnostic_required_count": 0,
            "release_gate_status": "blocked",
        }
        return {
            "data_version_candidate": data_version,
            "manifest_candidate": manifest,
            "quality_report_candidate": quality_report,
            "release_gate_results": gates,
            "release_decision": "formal_release_blocked",
        }

    def errors(self, payload: dict[str, object]) -> str:
        return "\n".join(validate_d3_release_gate_payload(payload, self.contract))

    def test_valid_synthetic_candidate_is_formal_release_blocked(self) -> None:
        self.assertEqual(
            validate_d3_release_gate_payload(self.valid_payload(), self.contract),
            [],
        )

    def test_required_sections_are_required(self) -> None:
        for section in [
            "data_version_candidate",
            "manifest_candidate",
            "quality_report_candidate",
            "release_gate_results",
        ]:
            payload = self.valid_payload()
            del payload[section]
            self.assertIn(section, self.errors(payload))

    def test_count_and_date_mismatch_fails(self) -> None:
        for field, bad_value in [
            ("row_count", 2),
            ("security_count", 2),
            ("trading_date_min", "2026-01-06"),
            ("trading_date_max", "2026-01-06"),
        ]:
            payload = self.valid_payload()
            payload["manifest_candidate"][field] = bad_value
            self.assertIn(f"{field} mismatch", self.errors(payload))

    def test_sha256_missing_or_empty_fails(self) -> None:
        for section in ["data_version_candidate", "manifest_candidate"]:
            payload = self.valid_payload()
            payload[section]["sha256"] = ""
            self.assertIn("missing sha256", self.errors(payload))

    def test_required_gate_missing_fails(self) -> None:
        payload = self.valid_payload()
        del payload["release_gate_results"]["hash_integrity_gate"]
        self.assertIn("missing gates", self.errors(payload))

    def test_release_allowed_fails_under_current_blocks(self) -> None:
        payload = self.valid_payload()
        payload["release_decision"] = "release_allowed"
        errors = self.errors(payload)
        self.assertIn("release_allowed is invalid", errors)
        self.assertIn("D3-T06 cannot allow formal release", errors)

    def test_current_hard_blocking_gates_cannot_pass(self) -> None:
        for gate in self.contract["current_blocking_gates"]:
            payload = self.valid_payload()
            payload["release_gate_results"][gate] = "passed"
            self.assertIn(f"{gate} must not be passed", self.errors(payload))

    def test_prohibited_fields_fail_at_any_depth(self) -> None:
        for field in [
            "pcvt_value",
            "future_return",
            "label",
            "backtest_signal",
            "portfolio_return",
            "vendor_payload",
            "raw_rows",
            "qfq_rows",
            "hfq_rows",
        ]:
            payload = self.valid_payload()
            payload["quality_report_candidate"]["quality_summary"][field] = 1
            self.assertIn("prohibited fields", self.errors(payload))

    def test_forbidden_content_paths_fail(self) -> None:
        for value in [
            "data/raw/synthetic.json",
            "data/external/synthetic.json",
            "MarketDB/prices.json",
            "research.duckdb",
            "SH000001.day",
        ]:
            payload = self.valid_payload()
            payload["manifest_candidate"]["source_snapshot_refs"] = [value]
            self.assertIn("forbidden path", self.errors(payload))

    def test_cli_accepts_valid_synthetic_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "synthetic_release_candidate.json"
            payload_path.write_text(
                json.dumps(self.valid_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            old_argv = sys.argv
            try:
                sys.argv = [
                    "validate_d3_release_gate.py",
                    "--contract",
                    str(CONTRACT_PATH),
                    "--payload",
                    str(payload_path),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv
            self.assertFalse((ROOT / "research.duckdb").exists())
            self.assertFalse((ROOT / "manifests/d3_release_gate.json").exists())

    def test_cli_rejects_forbidden_payload_path_before_opening(self) -> None:
        old_argv = sys.argv
        try:
            for forbidden_path in [
                "data/raw/synthetic_release_candidate.json",
                "data/external/synthetic_release_candidate.json",
                "MarketDB/release.json",
                "research.duckdb",
                "SH000001.day",
            ]:
                sys.argv = [
                    "validate_d3_release_gate.py",
                    "--contract",
                    str(CONTRACT_PATH),
                    "--payload",
                    forbidden_path,
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 1)
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
