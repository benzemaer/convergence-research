# ruff: noqa: E501
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t03_event_zone_scan import (
    R2T03Error,
    adapter_contract_status,
    build_expected_security_dates,
    reconcile_atomic_interval_rows,
    validate_source_readiness,
)


class R2T03ReconciliationAdapterTest(unittest.TestCase):
    def test_expected_keys_use_authoritative_calendar_and_applicability(self) -> None:
        actual = build_expected_security_dates(
            ["S1", "S2"],
            ["2026-01-01", "2026-01-02"],
            [("S1", "2026-01-01"), ("S1", "2026-01-02"), ("S2", "2026-01-02")],
        )
        self.assertEqual(actual["S1"], ["2026-01-01", "2026-01-02"])
        self.assertEqual(actual["S2"], ["2026-01-02"])
        with self.assertRaisesRegex(R2T03Error, "outside_authoritative_domain"):
            build_expected_security_dates(
                ["S1"], ["2026-01-01"], [("S2", "2026-01-01")]
            )

    def test_interval_reconciliation_is_row_level_and_exact(self) -> None:
        row = {
            "route_id": "r1",
            "security_id": "S1",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "confirmed_day_count": 3,
            "termination_reason": "natural_state_exit",
        }
        self.assertEqual(
            reconcile_atomic_interval_rows([row], [dict(row)])["status"], "passed"
        )
        mutated = {**row, "termination_reason": "quality_interruption"}
        failed = reconcile_atomic_interval_rows([row], [mutated])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["rebuilt_row_count"], 1)
        self.assertEqual(failed["upstream_row_count"], 1)

    def test_interval_reconciliation_missing_field_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            R2T03Error, "interval_reconciliation_missing_field"
        ):
            reconcile_atomic_interval_rows([{"route_id": "r1"}], [])

    def test_current_adapters_are_explicitly_unresolved(self) -> None:
        config = {
            "inputs": {},
            "semantics": {
                "availability_adapter_status": "unresolved_upstream_contract",
                "availability_upstream_contract_path": "",
                "expected_key_adapter_status": "unresolved_upstream_contract",
                "expected_key_upstream_contract_path": "",
                "interval_reconciliation_adapter_status": "unresolved_upstream_contract",
                "interval_reconciliation_upstream_contract_path": "",
            },
        }
        actual = adapter_contract_status(config)
        self.assertEqual(
            actual["availability_adapter_status"], "unresolved_upstream_contract"
        )
        self.assertEqual(
            actual["expected_key_adapter_status"], "unresolved_upstream_contract"
        )
        self.assertEqual(
            actual["interval_reconciliation_adapter_status"],
            "unresolved_upstream_contract",
        )
        with self.assertRaisesRegex(
            R2T03Error, "availability_adapter_status:unresolved_upstream_contract"
        ):
            validate_source_readiness(config, [], root=Path("."))

    def test_config_claim_without_contract_file_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "inputs": {"expected_key_source": {"path": "x"}},
                "semantics": {
                    "availability_adapter_status": "resolved_upstream_contract",
                    "availability_upstream_contract_path": "missing.json",
                    "expected_key_adapter_status": "resolved_upstream_contract",
                    "expected_key_upstream_contract_path": "missing.json",
                    "interval_reconciliation_adapter_status": "resolved_upstream_contract",
                    "interval_reconciliation_upstream_contract_path": "missing.json",
                },
            }
            actual = adapter_contract_status(config, root=root)
            self.assertEqual(
                actual["availability_adapter_status"], "unresolved_upstream_contract"
            )
            self.assertEqual(
                actual["expected_key_adapter_status"], "unresolved_upstream_contract"
            )


if __name__ == "__main__":
    unittest.main()
