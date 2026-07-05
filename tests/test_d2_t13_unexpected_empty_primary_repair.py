from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    D2T13MaterializationError,
    _load_json,
    _read_jsonl,
    _write_json,
    _write_jsonl,
    repair_unexpected_empty_primary_partitions,
)


class FakeFrame:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []

    def to_dict(self, orient: str):
        if orient != "records":
            raise ValueError(orient)
        return self.rows


class RepairFakeClient:
    def __init__(self, empty_endpoints: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.empty_endpoints = empty_endpoints or set()
        self.pro_bar_called = False

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        if "daily" in self.empty_endpoints:
            return FakeFrame([])
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def pro_bar(self, **kwargs):
        self.pro_bar_called = True
        raise AssertionError("pro_bar must not be called")


class D2T13UnexpectedEmptyPrimaryRepairTest(unittest.TestCase):
    def _write_report(self, root: Path, entries: list[object]) -> None:
        _write_json(
            root / "tnskhdata_fetch_verification_report.json",
            {"unexpected_empty_primary_partitions": entries},
        )

    def test_path_list_entries_are_repaired_and_only_requested_tasks_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_partition = root / "partitions" / "daily" / "20190715.jsonl"
            _write_jsonl(old_partition, [])
            _write_jsonl(
                root / "partitions" / "stk_limit" / "20190716.jsonl",
                [{"old": True}],
            )
            self._write_report(
                root,
                [
                    str(old_partition),
                    str(root / "partitions" / "adj_factor" / "20190717.jsonl"),
                ],
            )
            client = RepairFakeClient()
            report = repair_unexpected_empty_primary_partitions(
                client,
                output_dir=root,
                checkpoint_dir=root / "checkpoints",
                retry_backoff_seconds=0,
            )
            self.assertEqual(
                client.calls,
                [
                    ("adj_factor", {"trade_date": "20190717"}),
                    ("daily", {"trade_date": "20190715"}),
                ],
            )
            self.assertFalse(client.pro_bar_called)
            self.assertEqual(report["attempted_repair_count"], 2)
            self.assertEqual(report["repaired_non_empty_count"], 2)
            self.assertEqual(_read_jsonl(old_partition)[0]["trade_date"], "20190715")
            untouched = _read_jsonl(
                root / "partitions" / "stk_limit" / "20190716.jsonl"
            )
            self.assertEqual(untouched, [{"old": True}])
            self.assertTrue(
                (
                    root / "tnskhdata_unexpected_empty_primary_repair_report.json"
                ).exists()
            )
            ledger = _read_jsonl(root / "checkpoints" / "fetch_ledger.jsonl")
            self.assertEqual(
                {row["task_id"] for row in ledger},
                {"daily:20190715", "adj_factor:20190717"},
            )
            partial_hashes = _load_json(
                root / "checkpoints" / "partial_hash_manifest.json"
            )
            self.assertEqual(
                set(partial_hashes), {"daily:20190715", "adj_factor:20190717"}
            )
            self.assertFalse(report["duckdb_written"])
            self.assertFalse(report["d3_rows_generated"])
            self.assertFalse(report["r0_state_generated"])

    def test_structured_entries_are_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_report(
                root,
                [
                    {
                        "endpoint": "stk_limit",
                        "trade_date": "20190715",
                        "partition_path": str(
                            root / "partitions" / "stk_limit" / "20190715.jsonl"
                        ),
                    }
                ],
            )
            client = RepairFakeClient()
            report = repair_unexpected_empty_primary_partitions(
                client,
                output_dir=root,
                checkpoint_dir=root / "checkpoints",
                retry_backoff_seconds=0,
            )
            self.assertEqual(client.calls, [("stk_limit", {"trade_date": "20190715"})])
            self.assertEqual(report["repaired_non_empty_count"], 1)

    def test_still_empty_after_repair_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_report(
                root,
                [str(root / "partitions" / "daily" / "20190715.jsonl")],
            )
            report = repair_unexpected_empty_primary_partitions(
                RepairFakeClient(empty_endpoints={"daily"}),
                output_dir=root,
                checkpoint_dir=root / "checkpoints",
                retry_backoff_seconds=0,
            )
            self.assertEqual(report["repaired_non_empty_count"], 0)
            self.assertEqual(report["repaired_still_empty_count"], 1)
            self.assertEqual(
                report["still_empty_partitions"][0]["repair_status"],
                "still_empty_after_repair",
            )

    def test_missing_report_and_malformed_path_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(D2T13MaterializationError):
                repair_unexpected_empty_primary_partitions(
                    RepairFakeClient(),
                    output_dir=root,
                    checkpoint_dir=root / "checkpoints",
                    retry_backoff_seconds=0,
                )
            self._write_report(root, ["bad/path.jsonl"])
            with self.assertRaises(D2T13MaterializationError):
                repair_unexpected_empty_primary_partitions(
                    RepairFakeClient(),
                    output_dir=root,
                    checkpoint_dir=root / "checkpoints",
                    retry_backoff_seconds=0,
                )

    def test_disallowed_endpoint_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_report(
                root,
                [str(root / "partitions" / "stock_st" / "20190715.jsonl")],
            )
            with self.assertRaises(D2T13MaterializationError):
                repair_unexpected_empty_primary_partitions(
                    RepairFakeClient(),
                    output_dir=root,
                    checkpoint_dir=root / "checkpoints",
                    retry_backoff_seconds=0,
                )


if __name__ == "__main__":
    unittest.main()
