# ruff: noqa: E501
from __future__ import annotations

import unittest

import duckdb

from src.r2.r2_t03_metrics import (
    _DIAGNOSTIC_PROFILE_SQL,
    METRIC_BINDINGS,
    create_metric_tables,
    nearest_order_statistic,
    reference_hard_gate_metrics,
)


class R2T03MetricCorrectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events = [
            {
                "scan_event_id": "e1",
                "security_id": "S1",
                "start_date": "2020-01-01",
                "zone_span_days": 2,
                "raw_false_bridged_day_count": 0,
                "component_count": 1,
                "bridge_count": 0,
                "status": "FINALIZED",
            },
            {
                "scan_event_id": "e2",
                "security_id": "S2",
                "start_date": "2021-01-01",
                "zone_span_days": 4,
                "raw_false_bridged_day_count": 2,
                "component_count": 3,
                "bridge_count": 5,
                "status": "RIGHT_CENSORED",
            },
            {
                "scan_event_id": "e3",
                "security_id": "S2",
                "start_date": "2021-02-01",
                "zone_span_days": 3,
                "raw_false_bridged_day_count": 1,
                "component_count": 1,
                "bridge_count": 0,
                "status": "FINALIZED",
            },
        ]
        self.components = [
            _component(1, True, "natural_state_exit", True, "not_censored"),
            _component(3, True, "natural_state_exit", True, "not_censored"),
            _component(1, False, "sample_end_censoring", False, "right_censored"),
            _component(1, False, "quality_interruption", False, "quality_break"),
        ]

    def metrics(self):
        return reference_hard_gate_metrics(
            events=self.events,
            components=self.components,
            eligible_valid_daily_count=10,
            confirmed_state_days=5,
            qualified_confirmed_keys=[
                ("S1", "01"),
                ("S1", "02"),
                ("S2", "01"),
                ("S2", "02"),
                ("S2", "02"),
            ],
            retrospective_qualified_confirmed_keys={
                ("S1", "01"),
                ("S1", "02"),
                ("S2", "01"),
                ("S2", "02"),
            },
            asof_qualified_confirmed_keys={("S1", "02"), ("S2", "02")},
            upstream_atomic_durations=[1, 2],
            d=2,
        )

    def test_nearest_order_statistic_fixes_odd_even_small_and_duplicates(self) -> None:
        self.assertEqual(nearest_order_statistic([3], 0.95), 3)
        self.assertEqual(nearest_order_statistic([1, 9], 0.50), 1)
        self.assertEqual(nearest_order_statistic([1, 4, 9], 0.50), 4)
        self.assertEqual(nearest_order_statistic([1, 2, 2, 9], 0.95), 9)
        self.assertIsNone(nearest_order_statistic([], 0.95))
        with self.assertRaisesRegex(ValueError, "nearest_order_q_out_of_range"):
            nearest_order_statistic([1], 0)

    def test_reference_hard_gate_metrics_are_exact(self) -> None:
        actual = self.metrics()
        self.assertEqual(actual["qualified_event_count"], 3)
        self.assertEqual(actual["unique_securities"], 2)
        self.assertEqual(actual["retained_confirmed_day_ratio"], 0.8)
        self.assertEqual(actual["confirmed_event_coverage"], 0.4)
        self.assertEqual(actual["retrospective_qualified_confirmed_coverage"], 0.4)
        self.assertEqual(actual["asof_qualified_confirmed_coverage"], 0.2)
        self.assertEqual(actual["bridged_day_ratio"], 1 / 3)
        self.assertEqual(actual["merge_ratio"], 1 / 3)
        self.assertEqual(actual["open_event_ratio"], 1 / 3)
        self.assertEqual(actual["nonzero_years"], 2)
        self.assertEqual(actual["max_year_share"], 2 / 3)
        self.assertEqual(actual["duration_q95_ratio"], 2.0)
        self.assertEqual(actual["short_interval_drop_rate"], 0.5)

    def test_zero_denominators_return_null(self) -> None:
        actual = reference_hard_gate_metrics(
            events=[],
            components=[],
            eligible_valid_daily_count=0,
            confirmed_state_days=0,
            qualified_confirmed_keys=set(),
            retrospective_qualified_confirmed_keys=set(),
            asof_qualified_confirmed_keys=set(),
            upstream_atomic_durations=[],
            d=3,
        )
        for metric in (
            "retained_confirmed_day_ratio",
            "confirmed_event_coverage",
            "merge_ratio",
            "duration_q95_ratio",
            "short_interval_drop_rate",
        ):
            self.assertIsNone(actual[metric])

    def test_mutation_formulas_do_not_match_frozen_values(self) -> None:
        actual = self.metrics()
        self.assertNotEqual(actual["confirmed_event_coverage"], 4 / 5)
        self.assertNotEqual(actual["duration_q95_ratio"], 4 / 3)
        self.assertNotEqual(actual["merge_ratio"], 5 / 3)
        self.assertNotEqual(actual["short_interval_drop_rate"], 3 / 4)

    def test_corrected_metrics_bind_frozen_evaluators_and_populations(self) -> None:
        self.assertEqual(
            METRIC_BINDINGS["merge_ratio"]["evaluator_id"],
            "r2_t02_metric_eval__merge_ratio",
        )
        self.assertIn(
            "natural_state_exit",
            METRIC_BINDINGS["short_interval_drop_rate"]["population"],
        )
        self.assertIn(
            "eligible valid", METRIC_BINDINGS["confirmed_event_coverage"]["denominator"]
        )

    def test_production_sql_matches_hand_calculated_fixture(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(_FIXTURE_SQL)
            create_metric_tables(con)
            dg = con.execute(
                "SELECT qualified_event_count,confirmed_event_coverage,unqualified_reentry_count FROM dg_event_zone_profile"
            ).fetchone()
            self.assertEqual(dg, (2, 0.4, 1))
            d_profile = con.execute(
                "SELECT retained_confirmed_day_ratio,retrospective_qualified_confirmed_coverage,asof_qualified_confirmed_coverage FROM d_qualification_profile"
            ).fetchone()
            self.assertEqual(d_profile, (0.8, 0.4, 0.3))
            metric = con.execute(
                """SELECT qualified_event_count,unique_securities,retained_confirmed_day_ratio,
                short_interval_drop_rate,bridged_day_ratio,merge_ratio,open_event_ratio,
                nonzero_years,max_year_share,duration_q95_ratio FROM metric_results"""
            ).fetchone()
            self.assertEqual(metric, (2, 1, 0.8, 0.5, 0.2, 0.5, 0.5, 2, 0.5, 0.6))
            atomic = con.execute(
                """SELECT atomic_singleton_count,atomic_confirmed_interval_count,
                atomic_fragment_rate FROM atomic_interval_diagnostic_profile"""
            ).fetchone()
            self.assertEqual(atomic, (1, 3, 1 / 3))
            component = con.execute(
                """SELECT qualification_delay_observations_mean,
                qualification_delay_observations_median,
                qualification_delay_observations_q90,
                qualification_delay_observations_q95
                FROM component_diagnostic_profile"""
            ).fetchone()
            self.assertEqual(component, (1.0, 1.0, 1, 1))
            event = con.execute(
                """SELECT component_count_q90,component_count_q95,
                bridge_count_q90,bridge_count_q95,max_single_gap
                FROM event_zone_diagnostic_profile"""
            ).fetchone()
            self.assertEqual(event, (2, 2, 4, 4, 1))
        finally:
            con.close()

    def test_complete_parameter_invariant_surface_executes(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE cell_registry(candidate_cell_id VARCHAR,route_id VARCHAR,d INTEGER,g INTEGER);
            CREATE TABLE dg_event_zone_profile(candidate_cell_id VARCHAR,qualified_event_count INTEGER);
            CREATE TABLE event_zone_diagnostic_profile(candidate_cell_id VARCHAR,bridged_gap_count INTEGER,
              bridged_day_count INTEGER,zone_span_days_sum INTEGER);
            CREATE TABLE atomic_baseline_profile(candidate_cell_id VARCHAR,confirmed_state_days INTEGER);
            CREATE TABLE component_diagnostic_profile(candidate_cell_id VARCHAR,
              retrospective_qualified_confirmed_day_count INTEGER,
              asof_qualified_confirmed_day_count INTEGER,
              qualification_delay_observations_mean DOUBLE);
            CREATE TABLE d_qualification_profile(candidate_cell_id VARCHAR,qualified_component_count INTEGER);"""
        )
        for d in (1, 2, 3):
            for g in (0, 1, 2):
                cell = f"c_{d}_{g}"
                con.execute(
                    "INSERT INTO cell_registry VALUES (?,'r',?,?)", [cell, d, g]
                )
                con.execute(
                    "INSERT INTO dg_event_zone_profile VALUES (?,?)",
                    [cell, 20 - d - g],
                )
                con.execute(
                    "INSERT INTO event_zone_diagnostic_profile VALUES (?,?,?,?)",
                    [cell, g, g, 100 + g],
                )
                con.execute(
                    "INSERT INTO atomic_baseline_profile VALUES (?,100)", [cell]
                )
                con.execute(
                    "INSERT INTO component_diagnostic_profile VALUES (?,?,?,?)",
                    [cell, 50 - d, 40 - d, float(d - 1)],
                )
                con.execute(
                    "INSERT INTO d_qualification_profile VALUES (?,?)",
                    [cell, 20 - d],
                )
        parameter_sql = (
            "CREATE TABLE parameter_invariant_profile AS"
            + _DIAGNOSTIC_PROFILE_SQL.split(
                "CREATE TABLE parameter_invariant_profile AS", 1
            )[1]
        )
        con.execute(parameter_sql)
        rows = con.execute(
            "SELECT DISTINCT check_id FROM parameter_invariant_profile ORDER BY 1"
        ).fetchall()
        self.assertEqual(len(rows), 12)
        self.assertEqual(
            con.execute(
                "SELECT sum(observed_violations) FROM parameter_invariant_profile"
            ).fetchone()[0],
            0,
        )

    def test_component_diagnostic_uses_frozen_censor_populations(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(_FIXTURE_SQL)
            create_metric_tables(con)
            actual = con.execute(
                """SELECT qualified_component_count,unqualified_component_count,
                component_qualification_rate,prequalification_right_censored_count
                FROM component_diagnostic_profile"""
            ).fetchone()
            self.assertEqual(actual, (2, 1, 2 / 3, 0))
        finally:
            con.close()

    def test_mega_zone_concentration_uses_top_one_percent_zones(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(_FIXTURE_SQL)
            for index in range(3, 102):
                con.execute(
                    """INSERT INTO event_zone VALUES
                    ('c','S1',?,'q2',1,0,0,0,0,0,0,1,1,'FINALIZED')""",
                    [f"e{index}"],
                )
            create_metric_tables(con)
            actual = con.execute(
                "SELECT mega_zone_concentration FROM event_zone_diagnostic_profile"
            ).fetchone()[0]
            self.assertEqual(actual, 5 / 104)
            self.assertNotEqual(actual, 3 / 104)
        finally:
            con.close()


def _component(count, qualified, reason, normally_ended, censor_status):
    return {
        "confirmed_day_count": count,
        "qualified": qualified,
        "termination_reason": reason,
        "normally_ended": normally_ended,
        "censor_status": censor_status,
    }


_FIXTURE_SQL = """
CREATE TABLE cell_registry(candidate_cell_id VARCHAR,route_id VARCHAR,candidate_role VARCHAR,state_line VARCHAR,W INTEGER,d INTEGER,g INTEGER);
INSERT INTO cell_registry VALUES ('c','r','primary','S_PCT',120,2,1);
CREATE TABLE route_daily(route_id VARCHAR,security_id VARCHAR,trade_date DATE,eligible BOOLEAN,quality_state VARCHAR,confirmed_state BOOLEAN);
INSERT INTO route_daily VALUES
 ('r','S1','2020-01-01',true,'valid',true),('r','S1','2020-01-02',true,'valid',true),
 ('r','S1','2020-01-03',true,'valid',true),('r','S1','2020-01-04',true,'valid',true),
 ('r','S1','2020-01-05',true,'valid',true),('r','S1','2020-01-06',true,'valid',false),
 ('r','S1','2020-01-07',true,'valid',false),('r','S1','2020-01-08',true,'valid',false),
 ('r','S1','2020-01-09',true,'valid',false),('r','S1','2020-01-10',true,'valid',false);
CREATE TABLE atomic_confirmed_daily AS SELECT 'c' candidate_cell_id,security_id,trade_date,eligible,quality_state,confirmed_state FROM route_daily;
CREATE TABLE route_atomic_interval(route_id VARCHAR,security_id VARCHAR,interval_id VARCHAR,start_date DATE,end_date DATE,confirmed_day_count INTEGER,termination_reason VARCHAR);
INSERT INTO route_atomic_interval VALUES ('r','S1','i1','2020-01-01','2020-01-01',1,'natural_state_exit'),('r','S1','i2','2020-01-02','2020-01-03',2,'natural_state_exit'),('r','S1','i3','2020-01-04','2020-01-08',5,'sample_end_censoring');
CREATE TABLE qualified_component(candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,start_date DATE,end_date DATE,confirmed_day_count INTEGER,qualified BOOLEAN,event_qualification_time TIMESTAMPTZ);
INSERT INTO qualified_component VALUES ('c','S1','q1','2020-01-01','2020-01-01',1,false,NULL),('c','S1','q2','2020-01-02','2020-01-03',2,true,NULL),('c','S1','q3','2021-01-04','2021-01-05',2,true,NULL),('c','S1','q4','2021-01-06','2021-01-06',1,false,NULL);
CREATE TABLE component_source_lineage(candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,source_atomic_interval_id VARCHAR,termination_reason VARCHAR,censor_status VARCHAR,normally_ended BOOLEAN);
INSERT INTO component_source_lineage VALUES ('c','S1','q1','i1','natural_state_exit','not_censored',true),('c','S1','q2','i2','natural_state_exit','not_censored',true),('c','S1','q3','i3','sample_end_censoring','right_censored',false),('c','S1','q4','i4','quality_interruption','quality_break',false);
CREATE TABLE event_zone(candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,first_component_id VARCHAR,component_count INTEGER,bridge_count INTEGER,raw_false_bridged_day_count INTEGER,preconfirmation_gap_day_count INTEGER,total_nonconfirmed_gap_day_count INTEGER,max_raw_false_gap_days INTEGER,max_total_gap_span_days INTEGER,confirmed_day_count INTEGER,zone_span_days INTEGER,status VARCHAR);
INSERT INTO event_zone VALUES ('c','S1','e1','q2',1,0,0,0,0,0,0,2,2,'FINALIZED'),('c','S1','e2','q3',2,4,1,0,1,1,1,2,3,'RIGHT_CENSORED');
CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR,security_id VARCHAR,trade_date DATE,eligible BOOLEAN,quality_state VARCHAR,confirmed_state BOOLEAN,retrospective_component_member BOOLEAN,event_zone_member BOOLEAN,component_qualified_as_of BOOLEAN);
INSERT INTO event_zone_membership_daily VALUES
 ('c','S1','2020-01-01',true,'valid',true,true,true,false),
 ('c','S1','2020-01-02',true,'valid',true,true,true,true),
 ('c','S1','2020-01-03',true,'valid',true,true,true,true),
 ('c','S1','2020-01-04',true,'valid',true,true,true,true);
CREATE TABLE reentry_attempt(candidate_cell_id VARCHAR,reentry_attempt_id VARCHAR,outcome VARCHAR);
INSERT INTO reentry_attempt VALUES ('c','a1','unqualified_reentry'),('c','a1','unqualified_reentry');
CREATE TABLE transition_profile(candidate_cell_id VARCHAR,from_state VARCHAR,to_state VARCHAR,reason_code VARCHAR);
"""


if __name__ == "__main__":
    unittest.main()
