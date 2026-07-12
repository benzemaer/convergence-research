from __future__ import annotations

# ruff: noqa: E501 -- SQL fixtures remain readable as complete statements.
import unittest

import duckdb

from src.r2.r2_t03_result_analysis import (
    _analysis_markdown,
    _analysis_metric_rows,
)


class R2T03ResultAnalysisTest(unittest.TestCase):
    def test_confirmed_coverage_is_not_replaced_by_retained_ratio(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE metric_results(candidate_cell_id VARCHAR,state_line VARCHAR,
            W INTEGER,d INTEGER,g INTEGER,qualified_event_count INTEGER,
            retained_confirmed_day_ratio DOUBLE,bridged_day_ratio DOUBLE)"""
        )
        con.execute(
            "CREATE TABLE dg_event_zone_profile(candidate_cell_id VARCHAR,confirmed_event_coverage DOUBLE)"
        )
        con.execute(
            """CREATE TABLE d_qualification_profile(candidate_cell_id VARCHAR,
            retrospective_qualified_confirmed_coverage DOUBLE,
            asof_qualified_confirmed_coverage DOUBLE)"""
        )
        con.execute("INSERT INTO metric_results VALUES ('c','S_PCT',120,3,1,4,.8,.1)")
        con.execute("INSERT INTO dg_event_zone_profile VALUES ('c',.4)")
        con.execute("INSERT INTO d_qualification_profile VALUES ('c',.7,.6)")
        row = _analysis_metric_rows(con)[0]
        self.assertEqual(row[5], 0.4)
        self.assertEqual(row[6], 0.8)
        self.assertNotEqual(row[5], row[6])

    def test_resolved_adapter_wording_and_scientific_failure_retention(self) -> None:
        text = _analysis_markdown(
            [("S_PCT", 120, 3, 1, 4, 0.4, 0.8, 0.7, 0.6, 0.1)],
            {"status": "passed", "failures": []},
            {"status": "passed"},
            [
                {
                    "candidate_cell_id": "c",
                    "check_id": "scientific",
                    "status": "failed",
                    "observed_value": "0",
                    "expected_rule": ">0",
                }
            ],
        )
        self.assertIn(
            "availability policy、expected-key adapter 与 interval adapter 已解决", text
        )
        self.assertIn("共有 1 个非工程阻断", text)
        self.assertIn("不用于选取或排除 cell", text)


if __name__ == "__main__":
    unittest.main()
