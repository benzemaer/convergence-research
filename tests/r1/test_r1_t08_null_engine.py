from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from src.r1.r1_t08_global_nested_null_models import _write_csv
from src.r1.r1_t08_null_engine import (
    BLOCKED,
    RAW_FALSE,
    RAW_NULL,
    RAW_TRUE,
    UNKNOWN,
    VALID,
    derive_continuous_blocks,
    derived_seed,
    deterministic_offsets,
    nested_retention_metrics,
    ordered_and,
    shifted_source_indices,
    sparse_confirmed_metrics,
)


class R1T08NullEngineTest(unittest.TestCase):
    def test_ordered_and_short_circuits_false_and_propagates_null(self) -> None:
        p = np.array([RAW_FALSE, RAW_TRUE, RAW_TRUE, RAW_NULL], dtype=np.int8)
        c = np.array([RAW_NULL, RAW_FALSE, RAW_NULL, RAW_TRUE], dtype=np.int8)
        ps = np.array([VALID, VALID, VALID, UNKNOWN], dtype=np.int8)
        cs = np.array([BLOCKED, VALID, BLOCKED, VALID], dtype=np.int8)
        raw, status = ordered_and((p, c), (ps, cs))
        np.testing.assert_array_equal(raw, [RAW_FALSE, RAW_FALSE, RAW_NULL, RAW_NULL])
        np.testing.assert_array_equal(status, [VALID, VALID, BLOCKED, UNKNOWN])

    def test_blocks_split_on_security_year_and_calendar_gap(self) -> None:
        sec = np.array([0, 0, 0, 0, 1, 1])
        year = np.array([2020, 2020, 2020, 2021, 2020, 2020])
        ordinal = np.array([1, 2, 4, 5, 1, 2])
        starts, lengths, block_id, within = derive_continuous_blocks(sec, year, ordinal)
        np.testing.assert_array_equal(starts, [0, 2, 3, 4])
        np.testing.assert_array_equal(lengths, [2, 1, 1, 2])
        np.testing.assert_array_equal(block_id, [0, 0, 1, 2, 3, 3])
        np.testing.assert_array_equal(within, [0, 1, 0, 0, 0, 1])

    def test_seed_and_offsets_are_reproducible_and_nonzero(self) -> None:
        lengths = np.array([1, 2, 5, 20], dtype=np.int64)
        seed = derived_seed(7, "candidate", "global", 1, "C")
        first = deterministic_offsets(lengths, seed)
        second = deterministic_offsets(lengths, seed)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first[0], 0)
        self.assertTrue(np.all(first[1:] > 0))
        self.assertTrue(np.all(first[1:] < lengths[1:]))

    def test_shift_does_not_cross_blocks(self) -> None:
        starts = np.array([0, 3], dtype=np.int64)
        lengths = np.array([3, 2], dtype=np.int64)
        block_id = np.array([0, 0, 0, 1, 1], dtype=np.int64)
        within = np.array([0, 1, 2, 0, 1], dtype=np.int64)
        offsets = np.array([1, 1], dtype=np.int64)
        targets = np.arange(5)
        source = shifted_source_indices(
            targets, starts, lengths, block_id, within, offsets
        )
        np.testing.assert_array_equal(source, [2, 0, 1, 4, 3])
        np.testing.assert_array_equal(block_id[source], block_id[targets])

    def test_sparse_confirmation_matches_k3_interval_semantics(self) -> None:
        sec = np.array([0] * 10 + [1] * 4)
        true = np.array([0, 1, 2, 4, 5, 6, 7, 10, 11, 12])
        metrics = sparse_confirmed_metrics(
            true, sec, eligible_count=14, confirmation_k=3
        )
        self.assertEqual(metrics["confirmed_day_count"], 4)
        self.assertEqual(metrics["interval_count"], 3)
        self.assertEqual(metrics["duration_median"], 1.0)
        self.assertEqual(metrics["fragment_count"], 2)

    def test_nested_retention_keeps_unknown_and_blocked_out_of_denominator(
        self,
    ) -> None:
        parent = np.arange(5)
        raw = np.array([RAW_TRUE, RAW_FALSE, RAW_NULL, RAW_NULL, RAW_TRUE])
        status = np.array([VALID, VALID, UNKNOWN, BLOCKED, VALID])
        metrics = nested_retention_metrics(parent, raw, status)
        self.assertEqual(metrics["parent_eligible_count"], 3)
        self.assertEqual(metrics["child_true_count"], 2)
        self.assertEqual(metrics["child_unknown_count"], 1)
        self.assertEqual(metrics["child_blocked_count"], 1)
        self.assertAlmostEqual(metrics["nested_retention"], 2 / 3)

    def test_csv_writer_uses_union_schema_for_global_and_nested_rows(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "replicates.csv"
            _write_csv(path, [{"global": 1}, {"global": 2, "nested": 3}])
            text = path.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "global,nested")
        self.assertEqual(text.splitlines()[2], "2,3")


if __name__ == "__main__":
    unittest.main()
