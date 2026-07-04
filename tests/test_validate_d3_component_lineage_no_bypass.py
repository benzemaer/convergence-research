from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_d3_component_lineage_no_bypass import (
    is_forbidden_payload_path,
    main,
    validate_component_lineage_payload,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/component_lineage_no_bypass_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class ValidateD3ComponentLineageNoBypassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)

    def valid_payload(self) -> dict[str, object]:
        canonical = {
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
        }
        value = copy.deepcopy(canonical)
        value["canonical_observation_ref"] = (
            "synthetic_d3_v0|CSI800_STATIC_2026_06|XSHE.000001|2026-01-05|rev_001"
        )
        return {
            "canonical_observation": canonical,
            "value_observation": value,
            "r0_allowed_sources": [
                "d3.daily_market_observations",
                "d3.daily_market_observation_values",
            ],
        }

    def assert_has_error(self, payload: dict[str, object], pattern: str) -> None:
        errors = validate_component_lineage_payload(payload, self.contract)
        self.assertTrue(errors)
        self.assertIn(pattern, "\n".join(errors))

    def test_valid_synthetic_payload_passes(self) -> None:
        self.assertEqual(
            validate_component_lineage_payload(self.valid_payload(), self.contract),
            [],
        )

    def test_missing_required_component_ref_fails(self) -> None:
        for ref in ["raw_price_ref", "adjusted_price_ref", "run_ref"]:
            payload = self.valid_payload()
            del payload["canonical_observation"][ref]
            self.assert_has_error(payload, "missing component refs")

    def test_missing_canonical_observation_ref_fails(self) -> None:
        payload = self.valid_payload()
        del payload["value_observation"]["canonical_observation_ref"]
        self.assert_has_error(payload, "missing canonical_observation_ref")

    def test_primary_key_mismatch_fails(self) -> None:
        payload = self.valid_payload()
        payload["value_observation"]["security_id"] = "XSHG.600000"
        self.assert_has_error(payload, "primary key mismatch")

    def test_lineage_inheritance_mismatch_fails(self) -> None:
        for field in [
            "observed_at",
            "revision_policy",
            "history_revision_class",
            "research_use_tier",
        ]:
            payload = self.valid_payload()
            payload["value_observation"][field] = f"changed_{field}"
            self.assert_has_error(payload, f"lineage inheritance mismatch for {field}")

    def test_final_revised_history_point_in_time_claim_fails(self) -> None:
        payload = self.valid_payload()
        payload["canonical_observation"]["history_revision_class"] = (
            "final_revised_history"
        )
        payload["canonical_observation"]["observed_at_rule"] = "point_in_time"
        payload["value_observation"]["history_revision_class"] = "final_revised_history"
        payload["value_observation"]["observed_at_rule"] = "point_in_time"
        self.assert_has_error(payload, "final_revised_history cannot claim")

    def test_prohibited_research_outcome_fields_fail(self) -> None:
        for field in [
            "future_return",
            "label",
            "backtest_signal",
            "portfolio_return",
            "pcvt_value",
        ]:
            payload = self.valid_payload()
            payload["value_observation"][field] = 1
            self.assert_has_error(payload, "prohibited fields")

    def test_vendor_and_row_payload_fields_fail(self) -> None:
        for field in ["vendor_payload", "raw_rows", "qfq_rows", "hfq_rows"]:
            payload = self.valid_payload()
            payload["canonical_observation"][field] = []
            self.assert_has_error(payload, "prohibited fields")

    def test_d1_d2_sources_in_r0_allowed_sources_fail(self) -> None:
        for source in ["d1.raw_market_prices", "d2.adjusted_market_prices"]:
            payload = self.valid_payload()
            payload["r0_allowed_sources"].append(source)
            self.assert_has_error(payload, "non-D3 sources")

    def test_unknown_or_missing_research_use_tier_fails(self) -> None:
        payload = self.valid_payload()
        payload["canonical_observation"]["research_use_tier"] = "unknown"
        payload["value_observation"]["research_use_tier"] = "unknown"
        self.assert_has_error(payload, "research_use_tier missing or unknown")

        payload = self.valid_payload()
        del payload["canonical_observation"]["research_use_tier"]
        del payload["value_observation"]["research_use_tier"]
        self.assert_has_error(payload, "research_use_tier")

    def test_forbidden_real_data_paths_fail(self) -> None:
        for value in [
            "data/raw/vendor.day",
            "data/external/source.csv",
            "MarketDB/prices",
            "research.duckdb",
            "SH000001.day",
        ]:
            payload = self.valid_payload()
            payload["synthetic_payload_path"] = value
            self.assert_has_error(payload, "forbidden real data path")

    def test_cli_accepts_explicit_synthetic_payload_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "synthetic_payload.json"
            payload_path.write_text(
                json.dumps(self.valid_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            contract_path = Path(tmpdir) / "contract.json"
            contract_path.write_text(
                json.dumps(self.contract, ensure_ascii=False),
                encoding="utf-8",
            )
            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "validate_d3_component_lineage_no_bypass.py",
                    "--contract",
                    str(contract_path),
                    "--payload",
                    str(payload_path),
                ]
                self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv

    def test_cli_rejects_forbidden_payload_paths_before_opening(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            contract_path = Path(tmpdir) / "contract.json"
            contract_path.write_text(
                json.dumps(self.contract, ensure_ascii=False),
                encoding="utf-8",
            )
            forbidden_paths = [
                Path("data/raw/synthetic_payload.json"),
                Path("data/external/synthetic_payload.json"),
                Path("MarketDB/prices.json"),
                Path("research.duckdb"),
                Path("SH000001.day"),
            ]
            import sys

            old_argv = sys.argv
            try:
                for payload_path in forbidden_paths:
                    self.assertTrue(is_forbidden_payload_path(payload_path))
                    sys.argv = [
                        "validate_d3_component_lineage_no_bypass.py",
                        "--contract",
                        str(contract_path),
                        "--payload",
                        str(payload_path),
                    ]
                    self.assertEqual(main(), 1)
            finally:
                sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
