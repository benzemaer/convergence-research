from __future__ import annotations

import unittest
from pathlib import Path

from scripts.validate_d2_acceptance_d3_handoff import (
    D2AcceptanceD3HandoffValidationError,
    validate_d2_acceptance_d3_handoff,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/validate_d2_acceptance_d3_handoff.py"
FULL_WINDOW_READY = "exploration_ready_after_full_window_pull"
C2_READY = "partial_pending_amount_volume_unit_validation_and_adjusted_vwap_policy"
V1_READY = "partial_pending_volume_unit_validation_and_adjusted_volume_policy"
V2_READY = "ready_after_amount_unit_validation_and_history_window_pull"


def synthetic_payload() -> dict[str, object]:
    return {
        "component_refs": [
            "raw_price_ref",
            "adjusted_price_ref",
            "trading_constraint_ref",
            "market_price_quality_ref",
            "mechanical_gap_ref",
            "pcvt_input_readiness_ref",
            "membership_ref",
            "calendar_ref",
            "source_snapshot_ref",
            "run_ref",
        ],
        "fact_groups": [
            "identity",
            "raw_trading_facts",
            "continuous_research_prices",
            "trading_constraints",
            "market_quality_flags",
            "mechanical_gap_attribution",
            "pcvt_input_readiness",
            "membership_alignment",
            "calendar_alignment",
            "source_lineage",
            "observed_at_revision",
        ],
        "source_snapshot_id": "synthetic_snapshot_ref",
        "observed_at": "2026-07-04T00:00:00Z",
        "history_revision_class": "final_revised_history",
        "formal_point_in_time_supported": False,
        "factor_as_of_time_coverage": "fail",
        "formal_continuous_price_ready": False,
        "revision_timestamp_coverage": "fail",
        "revision_aware_ready": False,
        "r0_allowed_sources": ["d3.daily_market_observations"],
        "pcvt_candidate_set_status": "proposed_not_r0_finalized",
        "pcvt_values_generated": False,
        "r0_thresholds_defined": False,
        "formal_ingestion_authorized": False,
        "d3_generated": False,
        "r0_generated": False,
        "pcvt_readiness": {
            "P1_NATR14": FULL_WINDOW_READY,
            "P2_LogRange20": FULL_WINDOW_READY,
            "C1_LogMASpread_5_60": FULL_WINDOW_READY,
            "C2_AdjVWAPSpread_5_60": C2_READY,
            "T1_ER20": FULL_WINDOW_READY,
            "T2_AbsTrendT20": FULL_WINDOW_READY,
            "V1_VolShrink20_60": V1_READY,
            "V2_AmountLevel20Pct": V2_READY,
        },
    }


class ValidateD2AcceptanceD3HandoffTest(unittest.TestCase):
    def test_validator_accepts_synthetic_refs_only_payload(self) -> None:
        validate_d2_acceptance_d3_handoff(synthetic_payload())

    def test_validator_allows_final_revised_exploration_only_payload(self) -> None:
        payload = synthetic_payload() | {
            "history_revision_class": "final_revised_history",
            "formal_point_in_time_supported": False,
        }
        validate_d2_acceptance_d3_handoff(payload)

    def test_validator_allows_c2_v1_partial_readiness(self) -> None:
        validate_d2_acceptance_d3_handoff(synthetic_payload())

    def test_validator_rejects_embedded_rows_or_vendor_payload(self) -> None:
        for field in ["raw_rows", "qfq_rows", "hfq_rows", "vendor_payload"]:
            with self.subTest(field=field):
                payload = synthetic_payload() | {field: []}
                with self.assertRaises(D2AcceptanceD3HandoffValidationError):
                    validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_missing_observed_at_or_snapshot(self) -> None:
        for field in ["observed_at", "source_snapshot_id"]:
            with self.subTest(field=field):
                payload = synthetic_payload()
                del payload[field]
                with self.assertRaises(D2AcceptanceD3HandoffValidationError):
                    validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_point_in_time_claim_for_final_revised_history(
        self,
    ) -> None:
        payload = synthetic_payload() | {"formal_point_in_time_supported": True}
        with self.assertRaises(D2AcceptanceD3HandoffValidationError):
            validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_formal_readiness_when_factor_as_of_fails(self) -> None:
        payload = synthetic_payload() | {"formal_continuous_price_ready": True}
        with self.assertRaises(D2AcceptanceD3HandoffValidationError):
            validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_revision_ready_when_timestamp_fails(self) -> None:
        payload = synthetic_payload() | {"revision_aware_ready": True}
        with self.assertRaises(D2AcceptanceD3HandoffValidationError):
            validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_d1_d2_bypass_for_r0_sources(self) -> None:
        for source in ["d1.raw_market_prices", "d2.adjusted_market_prices"]:
            payload = synthetic_payload() | {"r0_allowed_sources": [source]}
            with self.subTest(source=source):
                with self.assertRaises(D2AcceptanceD3HandoffValidationError):
                    validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_future_outcome_fields(self) -> None:
        for field in [
            "future_return",
            "label",
            "breakout_direction",
            "outcome",
            "target",
        ]:
            payload = synthetic_payload() | {field: 1}
            with self.subTest(field=field):
                with self.assertRaises(D2AcceptanceD3HandoffValidationError):
                    validate_d2_acceptance_d3_handoff(payload)

    def test_validator_rejects_generation_markers(self) -> None:
        for field in [
            "formal_ingestion_authorized",
            "d3_generated",
            "r0_generated",
            "pcvt_values_generated",
            "r0_thresholds_defined",
        ]:
            payload = synthetic_payload() | {field: True}
            with self.subTest(field=field):
                with self.assertRaises(D2AcceptanceD3HandoffValidationError):
                    validate_d2_acceptance_d3_handoff(payload)

    def test_validator_source_has_no_external_or_storage_access(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        for token in [
            "baostock",
            "requests",
            "urllib",
            "duckdb",
            "data/raw",
            "data/external",
        ]:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
