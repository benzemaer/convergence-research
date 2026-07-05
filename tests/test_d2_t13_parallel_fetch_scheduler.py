from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    build_endpoint_tasks,
    build_fetch_plan,
)


class D2T13ParallelFetchSchedulerTest(unittest.TestCase):
    def test_builds_endpoint_trade_date_tasks_without_security_date_tasks(self) -> None:
        plan = build_fetch_plan(
            [
                {
                    "security_id": "XSHE.000001",
                    "trading_date": "20260629",
                    "universe_id": "u",
                    "time_segment_id": "t",
                },
                {
                    "security_id": "XSHE.000001",
                    "trading_date": "20260630",
                    "universe_id": "u",
                    "time_segment_id": "t",
                },
            ],
            full=True,
            sample_securities=None,
            sample_dates_per_security=None,
        )
        tasks = build_endpoint_tasks(plan)
        task_ids = {task.task_id for task in tasks}
        self.assertIn("stock_basic:L", task_ids)
        self.assertIn("trade_cal:20260629:20260630", task_ids)
        self.assertIn("daily:20260629", task_ids)
        self.assertIn("adj_factor:20260630", task_ids)
        self.assertNotIn("pro_bar:20260630", task_ids)
        self.assertFalse(any("XSHE.000001" in task.task_id for task in tasks))


if __name__ == "__main__":
    unittest.main()
