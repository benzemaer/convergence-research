from __future__ import annotations

# ruff: noqa: E501 -- SQL fixtures remain readable as complete statements.
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t03_result_analysis import (
    _analysis_markdown,
    _analysis_metric_rows,
    _anomaly_queries,
    _anomaly_scan,
    _query_dicts,
    _single_security_concentration_query,
)


class R2T03ResultAnalysisTest(unittest.TestCase):
    def test_single_security_concentration_query_uses_explicit_alias(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE event_zone(candidate_cell_id VARCHAR,security_id VARCHAR);
            INSERT INTO event_zone VALUES ('c','S1'),('c','S1'),('c','S1'),('c','S2');"""
        )
        cursor = con.execute(_single_security_concentration_query())
        self.assertEqual(
            [item[0] for item in cursor.description],
            [
                "candidate_cell_id",
                "security_event_share",
            ],
        )
        self.assertEqual(cursor.fetchone(), ("c", 0.75))
        self.assertEqual(
            con.execute(
                _anomaly_queries()["single_security_extreme_concentration"]
            ).fetchone()[0],
            1,
        )
        con.close()

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

    def test_scientific_anomaly_is_retained_without_engineering_pass(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE dg_event_zone_profile(candidate_cell_id VARCHAR,qualified_event_count INTEGER,confirmed_event_coverage DOUBLE);
            INSERT INTO dg_event_zone_profile VALUES ('c',2,.4);
            CREATE TABLE parameter_response_audit(status VARCHAR); INSERT INTO parameter_response_audit VALUES ('responsive');
            CREATE TABLE strict_core_window_comparison(subset_violation BOOLEAN); INSERT INTO strict_core_window_comparison VALUES (false);
            CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,trade_date DATE,
              membership_available_time TIMESTAMP,available_time TIMESTAMP,evaluation_time TIMESTAMP,
              qualified_event_risk_set_eligible BOOLEAN,state_risk_set_eligible BOOLEAN,event_zone_member BOOLEAN,
              component_qualified_as_of BOOLEAN,is_raw_false_bridge BOOLEAN,is_preconfirmation_gap BOOLEAN,zone_status_as_of VARCHAR);
            CREATE TABLE route_atomic_interval(upstream_source_interval_id VARCHAR); INSERT INTO route_atomic_interval VALUES ('source');
            CREATE TABLE event_zone(candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,first_component_id VARCHAR);
            CREATE TABLE qualified_component(candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,start_date DATE,end_date DATE,confirmed_day_count INTEGER);
            CREATE TABLE transition_entity_ledger(candidate_cell_id VARCHAR,security_id VARCHAR,entity_id VARCHAR,to_state VARCHAR);
            CREATE TABLE event_zone_diagnostic_profile(nonconfirmed_gap_ratio DOUBLE,bridged_day_ratio DOUBLE,
              mega_zone_concentration DOUBLE,max_zone_span INTEGER,top_zone_confirmed_day_share DOUBLE,duration_q95_ratio DOUBLE,
              right_censored_zone_count INTEGER,quality_break_zone_count INTEGER,qualified_event_count INTEGER,
              max_year_share DOUBLE,merge_ratio DOUBLE,confirmed_event_coverage DOUBLE);
            INSERT INTO event_zone_diagnostic_profile VALUES (.6,.1,.2,20,.2,1,0,0,2,.2,.1,.4);
            CREATE TABLE atomic_baseline_profile(candidate_cell_id VARCHAR,confirmed_state_days INTEGER);
            CREATE TABLE window_overlap_comparison(intersection_confirmed_days INTEGER,W120_own_eligible_days INTEGER,
              W250_own_eligible_days INTEGER,common_eligible_days INTEGER);
            CREATE TABLE window_diagnostic_profile(confirmed_day_jaccard DOUBLE);
            INSERT INTO window_diagnostic_profile VALUES (.5);
            CREATE TABLE strict_core_diagnostic_profile(strict_core_subset_status VARCHAR,
              strict_core_confirmed_day_share DOUBLE,strict_core_event_share DOUBLE,
              strict_core_qualified_component_share DOUBLE);
            INSERT INTO strict_core_diagnostic_profile VALUES ('passed',.5,.5,.5);"""
        )
        result = _anomaly_scan(con)
        self.assertIn("bridge_gap_domination", result["scientific_investigation_items"])
        self.assertEqual(result["blocking_engineering_anomalies"], [])
        self.assertFalse(result["downstream_progression_blocked"])
        self.assertEqual(set(result["checks"]), set(_anomaly_queries()))
        json.dumps(result)
        con.close()

    def test_analysis_sql_has_no_bare_share_alias(self) -> None:
        source = Path(__file__).parents[2] / "src/r2/r2_t03_result_analysis.py"
        text = source.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bAS\s+share\b", text, re.IGNORECASE))
        self.assertIn("max_year_share", text)
        self.assertIn("strict_core_event_share", text)

    def test_query_mapping_normalizes_duckdb_date_for_canonical_json(self) -> None:
        con = duckdb.connect(":memory:")
        rows = _query_dicts(
            con, "SELECT DATE '2026-07-13' observed_date,1.25::DECIMAL observed_value"
        )
        self.assertEqual(
            rows, [{"observed_date": "2026-07-13", "observed_value": 1.25}]
        )
        json.dumps(rows)
        con.close()

    def test_read_only_analysis_query_preserves_database_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.duckdb"
            con = duckdb.connect(str(path))
            con.execute(
                """CREATE TABLE event_zone(candidate_cell_id VARCHAR,security_id VARCHAR);
                INSERT INTO event_zone VALUES ('c','S1'),('c','S2');"""
            )
            con.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            con = duckdb.connect(str(path), read_only=True)
            self.assertEqual(
                con.execute(_single_security_concentration_query()).fetchone(),
                ("c", 0.5),
            )
            con.close()
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
