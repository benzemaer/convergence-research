from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_d3_synthetic_daily_observation import (
    SyntheticBuildError,
    build_synthetic_daily_observation,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
BUILD_CONTRACT_PATH = (
    ROOT / "configs/d3/synthetic_daily_observation_build_contract.v1.json"
)
LINEAGE_CONTRACT_PATH = ROOT / "configs/d3/component_lineage_no_bypass_contract.v1.json"
QUALITY_CONTRACT_PATH = ROOT / "configs/d3/quality_readiness_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class BuildD3SyntheticDailyObservationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = {
            "build_contract": load_json(BUILD_CONTRACT_PATH),
            "lineage_contract": load_json(LINEAGE_CONTRACT_PATH),
            "quality_contract": load_json(QUALITY_CONTRACT_PATH),
        }

    def valid_payload(self) -> dict[str, object]:
        return {
            "data_version": "synthetic_d3_v0",
            "universe_id": "CSI800_STATIC_2026_06",
            "time_segment_id": "G0_T01",
            "security_id": "XSHE.000001",
            "trading_date": "2026-01-05",
            "observation_revision": "rev_001",
            "observed_at": "2026-01-05T16:00:00Z",
            "observed_at_rule": "source_observed_at",
            "revision_policy": "point_in_time_available",
            "history_revision_class": "point_in_time_history",
            "research_use_tier": "formal",
            "source_registry_id": "synthetic_source",
            "source_snapshot_id": "synthetic_snapshot",
            "run_id": "synthetic_run",
            "raw_price_ref": "raw_ref",
            "adjusted_price_ref": "adjusted_ref",
            "trading_constraint_ref": "constraint_ref",
            "market_price_quality_ref": "quality_ref",
            "mechanical_gap_ref": "gap_ref",
            "pcvt_input_readiness_ref": "readiness_ref",
            "membership_ref": "membership_ref",
            "calendar_ref": "calendar_ref",
            "source_snapshot_ref": "snapshot_ref",
            "run_ref": "run_ref",
            "raw_open": 10.0,
            "raw_high": 10.8,
            "raw_low": 9.9,
            "raw_close": 10.5,
            "volume": 1000000,
            "amount": 10300000.0,
            "daily_vwap": 10.3,
            "adj_open": 10.0,
            "adj_high": 10.8,
            "adj_low": 9.9,
            "adj_close": 10.5,
            "adjustment_factor": 1.0,
            "adjustment_method": "identity_no_adjustment",
            "factor_as_of_time": "2026-01-05T16:00:00Z",
            "corporate_action_flag": "none",
            "adjustment_revision": "rev_001",
            "amount_unit": "yuan",
            "volume_unit": "share",
            "trading_status": "normal_trading",
            "price_limit_status": "none",
            "tradable_flag": True,
            "is_suspended": False,
            "is_st": False,
            "limit_up_price": 11.0,
            "limit_down_price": 9.0,
            "raw_ohlcv_integrity_status": "pass",
            "continuous_ohlc_integrity_status": "pass",
            "raw_vs_continuous_reconciliation_status": "pass",
            "amount_volume_unit_status": "pass",
            "daily_vwap_range_status": "pass",
            "trading_constraint_status": "pass",
            "mechanical_gap_attribution": "none",
            "window_validity_status": "pass",
            "quality_severity_max": "none",
            "quality_blocking_flag": False,
            "quality_blocking_reasons": [],
            "pcvt_input_readiness_status": "ready",
            "p_layer_input_ready": "ready",
            "c_layer_input_ready": "ready",
            "t_layer_input_ready": "ready",
            "v_layer_input_ready": "ready",
            "pcvt_blocking_reasons": [],
        }

    def build(self, payload: dict[str, object]) -> dict[str, object]:
        return build_synthetic_daily_observation(payload, self.contracts)

    def test_valid_synthetic_payload_builds_minimal_integrated_output(self) -> None:
        output = self.build(self.valid_payload())
        self.assertIn("canonical_observation", output)
        self.assertIn("value_observation", output)
        self.assertIn("quality_readiness_summary", output)
        self.assertEqual(output["lineage_validation_errors"], [])

    def test_canonical_observation_is_refs_only(self) -> None:
        output = self.build(self.valid_payload())
        canonical = output["canonical_observation"]
        for field in [
            "raw_open",
            "adj_close",
            "volume",
            "pcvt_value",
            "future_return",
            "label",
            "backtest_signal",
            "vendor_payload",
        ]:
            self.assertNotIn(field, canonical)

    def test_value_observation_has_canonical_ref_and_aligned_primary_key(self) -> None:
        output = self.build(self.valid_payload())
        canonical = output["canonical_observation"]
        value = output["value_observation"]
        self.assertEqual(
            value["canonical_observation_ref"],
            "synthetic_d3_v0|CSI800_STATIC_2026_06|XSHE.000001|2026-01-05|rev_001",
        )
        for field in [
            "data_version",
            "universe_id",
            "security_id",
            "trading_date",
            "observation_revision",
        ]:
            self.assertEqual(value[field], canonical[field])

    def test_value_observation_inherits_lineage_fields(self) -> None:
        output = self.build(self.valid_payload())
        canonical = output["canonical_observation"]
        value = output["value_observation"]
        for field in [
            "observed_at",
            "observed_at_rule",
            "revision_policy",
            "history_revision_class",
            "research_use_tier",
            "source_registry_id",
            "source_snapshot_id",
            "run_id",
        ]:
            self.assertEqual(value[field], canonical[field])

    def test_quality_readiness_summary_uses_d3_t04_vocabularies(self) -> None:
        summary = self.build(self.valid_payload())["quality_readiness_summary"]
        self.assertEqual(summary["raw_ohlcv_integrity_status"], "pass")
        self.assertEqual(summary["quality_severity_max"], "none")
        self.assertEqual(summary["pcvt_input_readiness_status"], "ready")
        for field in [
            "pcvt_value",
            "pcvt_score",
            "pcvt_state",
            "state",
            "q_threshold",
        ]:
            self.assertNotIn(field, summary)

    def test_missing_required_component_ref_fails(self) -> None:
        payload = self.valid_payload()
        del payload["raw_price_ref"]
        with self.assertRaisesRegex(SyntheticBuildError, "missing component refs"):
            self.build(payload)

    def test_missing_or_unknown_observed_at_fails(self) -> None:
        for value in [None, "", "unknown"]:
            payload = self.valid_payload()
            payload["observed_at"] = value
            with self.assertRaisesRegex(SyntheticBuildError, "observed_at"):
                self.build(payload)

    def test_missing_or_unknown_research_use_tier_fails(self) -> None:
        for value in [None, "", "unknown"]:
            payload = self.valid_payload()
            payload["research_use_tier"] = value
            with self.assertRaisesRegex(SyntheticBuildError, "research_use_tier"):
                self.build(payload)

    def test_prohibited_payload_fields_fail(self) -> None:
        for field in [
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
            payload[field] = 1
            with self.assertRaisesRegex(SyntheticBuildError, "prohibited fields"):
                self.build(payload)

    def test_forbidden_content_paths_fail(self) -> None:
        for value in [
            "data/raw/synthetic.json",
            "data/external/synthetic.json",
            "MarketDB/prices.json",
            "research.duckdb",
            "SH000001.day",
        ]:
            payload = self.valid_payload()
            payload["synthetic_source_path"] = value
            with self.assertRaisesRegex(SyntheticBuildError, "forbidden"):
                self.build(payload)

    def test_cli_accepts_valid_synthetic_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "synthetic_payload.json"
            payload_path.write_text(
                json.dumps(self.valid_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            old_argv = sys.argv
            stdout = io.StringIO()
            try:
                sys.argv = [
                    "build_d3_synthetic_daily_observation.py",
                    "--build-contract",
                    str(BUILD_CONTRACT_PATH),
                    "--lineage-contract",
                    str(LINEAGE_CONTRACT_PATH),
                    "--quality-contract",
                    str(QUALITY_CONTRACT_PATH),
                    "--payload",
                    str(payload_path),
                ]
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv
            output = json.loads(stdout.getvalue())
            self.assertEqual(output["lineage_validation_errors"], [])
            self.assertFalse((ROOT / "research.duckdb").exists())
            self.assertFalse((ROOT / "manifests/d3_synthetic.json").exists())

    def test_script_entrypoint_accepts_valid_synthetic_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "synthetic_payload.json"
            payload_path.write_text(
                json.dumps(self.valid_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_d3_synthetic_daily_observation.py",
                    "--build-contract",
                    str(BUILD_CONTRACT_PATH),
                    "--lineage-contract",
                    str(LINEAGE_CONTRACT_PATH),
                    "--quality-contract",
                    str(QUALITY_CONTRACT_PATH),
                    "--payload",
                    str(payload_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["lineage_validation_errors"], [])

    def test_cli_rejects_forbidden_payload_path_before_opening(self) -> None:
        old_argv = sys.argv
        try:
            for forbidden_path in [
                "data/raw/synthetic_payload.json",
                "data/external/synthetic_payload.json",
                "MarketDB/prices.json",
                "research.duckdb",
                "SH000001.day",
            ]:
                sys.argv = [
                    "build_d3_synthetic_daily_observation.py",
                    "--build-contract",
                    str(BUILD_CONTRACT_PATH),
                    "--lineage-contract",
                    str(LINEAGE_CONTRACT_PATH),
                    "--quality-contract",
                    str(QUALITY_CONTRACT_PATH),
                    "--payload",
                    forbidden_path,
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 1)
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
