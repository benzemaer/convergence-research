from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchTask,
    PartitionedJsonlStagingWriter,
)


class D2T13StagingWriterTest(unittest.TestCase):
    def test_partitioned_jsonl_writer_is_local_staging_not_formal_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            writer = PartitionedJsonlStagingWriter(root)
            task = FetchTask(
                task_id="daily:20260630",
                endpoint="daily",
                params={"trade_date": "20260630"},
                trade_date="20260630",
            )
            path, digest = writer.write(
                task, [{"ts_code": "000001.SZ", "trade_date": "20260630"}]
            )
            self.assertTrue(Path(path).exists())
            self.assertIn("partitions", path)
            self.assertTrue(digest)
            self.assertEqual(len(writer.load_endpoint("daily")), 1)
            self.assertFalse((root / "formal.duckdb").exists())


if __name__ == "__main__":
    unittest.main()
