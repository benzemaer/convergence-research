# ruff: noqa: E501

from __future__ import annotations

import unittest

import duckdb

from src.r2.r2_t03_metrics import (
    _DIAGNOSTIC_PROFILE_SQL,
    _create_strict_core_profile,
    _create_window_profile,
    deterministic_window_comparison,
    strict_core_comparison,
)


def keys(security: str, *dates: str):
    return {(security, date) for date in dates}


class R2T03StrictCoreComparisonTest(unittest.TestCase):
    def test_one_to_one_and_partial_strict_core(self) -> None:
        primary = {"p1": keys("S1", "01", "02"), "p2": keys("S1", "04")}
        strict = {"s1": keys("S1", "02")}
        actual = strict_core_comparison(
            primary,
            strict,
            primary_confirmed_keys=keys("S1", "01", "02", "04"),
            strict_confirmed_keys=keys("S1", "02"),
        )
        self.assertEqual(actual["strict_core_confirmed_day_count"], 1)
        self.assertEqual(actual["strict_core_event_count"], 1)
        self.assertEqual(actual["strict_core_event_share"], 0.5)
        self.assertEqual(actual["shell_only_event_count"], 1)
        self.assertEqual(actual["shell_only_confirmed_day_count"], 2)
        self.assertEqual(actual["strict_core_subset_status"], "passed")

    def test_multiple_strict_events_inside_one_primary_count_once(self) -> None:
        actual = strict_core_comparison(
            {"p1": keys("S1", "01", "02", "03")},
            {"s1": keys("S1", "01"), "s2": keys("S1", "03")},
            primary_confirmed_keys=keys("S1", "01", "02", "03"),
            strict_confirmed_keys=keys("S1", "01", "03"),
        )
        self.assertEqual(actual["strict_core_event_count"], 1)
        self.assertEqual(actual["strict_core_event_share"], 1.0)

    def test_strict_event_crossing_primary_boundaries_fails_closed(self) -> None:
        actual = strict_core_comparison(
            {"p1": keys("S1", "01"), "p2": keys("S1", "03")},
            {"s1": keys("S1", "01", "03")},
            primary_confirmed_keys=keys("S1", "01", "03"),
            strict_confirmed_keys=keys("S1", "01", "03"),
        )
        self.assertEqual(actual["strict_core_subset_status"], "failed")

    def test_shell_and_event_count_ratio_mutation_differ(self) -> None:
        actual = strict_core_comparison(
            {"p1": keys("S1", "01", "02"), "p2": keys("S1", "04")},
            {"s1": keys("S1", "01"), "s2": keys("S1", "02")},
            primary_confirmed_keys=keys("S1", "01", "02", "04"),
            strict_confirmed_keys=keys("S1", "01", "02"),
        )
        self.assertEqual(actual["strict_core_event_share"], 0.5)
        self.assertNotEqual(actual["strict_core_event_share"], 2 / 2)
        self.assertEqual(actual["shell_only_event_count"], 1)

    def test_unqualified_strict_day_does_not_create_component_containment(self) -> None:
        actual = strict_core_comparison(
            {"p1": keys("S1", "01")},
            {},
            primary_confirmed_keys=keys("S1", "01"),
            strict_confirmed_keys=keys("S1", "01"),
        )
        self.assertEqual(actual["strict_core_confirmed_day_count"], 1)
        self.assertEqual(actual["strict_core_event_count"], 0)
        self.assertEqual(actual["shell_only_event_count"], 1)


class R2T03WindowComparisonTest(unittest.TestCase):
    def compare(self, primary_events, comparison_events):
        primary_days = (
            set().union(*primary_events.values()) if primary_events else set()
        )
        comparison_days = (
            set().union(*comparison_events.values()) if comparison_events else set()
        )
        return deterministic_window_comparison(
            primary_days,
            comparison_days,
            primary_eligible=primary_days | keys("S1", "99"),
            comparison_eligible=comparison_days | keys("S1", "98"),
            primary_events=primary_events,
            comparison_events=comparison_events,
        )

    def test_identical_and_partial_overlap(self) -> None:
        identical = self.compare(
            {"p": keys("S1", "01", "02")}, {"c": keys("S1", "01", "02")}
        )
        self.assertEqual(identical["confirmed_day_jaccard"], 1.0)
        self.assertEqual(identical["matched_event_count"], 1)
        partial = self.compare(
            {"p": keys("S1", "01", "02")}, {"c": keys("S1", "02", "03")}
        )
        self.assertEqual(partial["intersection_confirmed_days"], 1)
        self.assertEqual(partial["W120_only_confirmed_days"], 1)
        self.assertEqual(partial["W250_only_confirmed_days"], 1)
        self.assertEqual(partial["union_confirmed_days"], 3)
        self.assertEqual(partial["matched_event_count"], 1)

    def test_one_to_many_and_many_to_one_are_greedy_one_to_one(self) -> None:
        one_many = self.compare(
            {"p": keys("S1", "01", "02")},
            {"c1": keys("S1", "01"), "c2": keys("S1", "02")},
        )
        self.assertEqual(one_many["matched_event_count"], 1)
        self.assertEqual(one_many["overlapping_event_count"], 1)
        many_one = self.compare(
            {"p1": keys("S1", "01"), "p2": keys("S1", "02")},
            {"c": keys("S1", "01", "02")},
        )
        self.assertEqual(many_one["matched_event_count"], 1)
        self.assertEqual(many_one["overlapping_event_count"], 2)

    def test_no_overlap_same_day_boundary_and_different_security(self) -> None:
        none = self.compare({"p": keys("S1", "01")}, {"c": keys("S1", "02")})
        self.assertEqual(none["matched_event_count"], 0)
        boundary = self.compare({"p": keys("S1", "01", "02")}, {"c": keys("S1", "02")})
        self.assertEqual(boundary["matched_event_count"], 1)
        different = self.compare({"p": keys("S1", "01")}, {"c": keys("S2", "01")})
        self.assertEqual(different["matched_event_count"], 0)

    def test_sort_ties_are_stable_and_exact_bounds_mutation_fails(self) -> None:
        actual = self.compare(
            {"p2": keys("S1", "01", "02"), "p1": keys("S1", "01")},
            {"c2": keys("S1", "01", "03"), "c1": keys("S1", "01")},
        )
        self.assertEqual(actual["matched_event_count"], 2)
        partial = self.compare(
            {"p": keys("S1", "01", "02")}, {"c": keys("S1", "02", "03")}
        )
        old_exact_start_end_match = 0
        self.assertNotEqual(partial["matched_event_count"], old_exact_start_end_match)

    def test_own_and_common_eligible_denominators_are_separate(self) -> None:
        actual = deterministic_window_comparison(
            keys("S1", "01"),
            keys("S1", "01"),
            primary_eligible=keys("S1", "01", "02"),
            comparison_eligible=keys("S1", "01", "03", "04"),
            primary_events={"p": keys("S1", "01")},
            comparison_events={"c": keys("S1", "01")},
        )
        self.assertEqual(actual["W120_own_eligible_days"], 2)
        self.assertEqual(actual["W250_own_eligible_days"], 3)
        self.assertEqual(actual["common_eligible_days"], 1)

    def test_overlapping_event_count_uses_zone_spans_not_pair_count(self) -> None:
        actual = deterministic_window_comparison(
            keys("S1", "01"),
            keys("S1", "03"),
            primary_eligible=keys("S1", "01", "02", "03"),
            comparison_eligible=keys("S1", "01", "02", "03"),
            primary_events={"p": keys("S1", "01")},
            comparison_events={"c": keys("S1", "03")},
            primary_event_spans={"p": keys("S1", "01", "02")},
            comparison_event_spans={"c": keys("S1", "02", "03")},
        )
        self.assertEqual(actual["matched_event_count"], 0)
        self.assertEqual(actual["overlapping_event_count"], 1)

    def test_production_comparison_tables_match_exact_key_fixture(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                """CREATE TABLE atomic_confirmed_daily(
                candidate_cell_id VARCHAR,security_id VARCHAR,trade_date DATE,
                confirmed_state BOOLEAN,eligible BOOLEAN,quality_state VARCHAR);
                INSERT INTO atomic_confirmed_daily VALUES
                ('p','S1','2026-01-01',true,true,'valid'),
                ('p','S1','2026-01-02',true,true,'valid'),
                ('s','S1','2026-01-01',false,true,'valid'),
                ('s','S1','2026-01-02',true,true,'valid'),
                ('w','S1','2026-01-02',true,true,'valid'),
                ('w','S1','2026-01-03',true,true,'valid');
                CREATE TABLE event_zone_membership_daily(
                candidate_cell_id VARCHAR,scan_event_id VARCHAR,security_id VARCHAR,
                trade_date DATE,event_zone_member BOOLEAN,confirmed_state BOOLEAN,
                retrospective_component_member BOOLEAN);
                INSERT INTO event_zone_membership_daily VALUES
                ('p','p1','S1','2026-01-01',true,true,true),
                ('p','p1','S1','2026-01-02',true,true,true),
                ('s','s1','S1','2026-01-02',true,true,true),
                ('w','w1','S1','2026-01-02',true,true,true),
                ('w','w1','S1','2026-01-03',true,true,true);
                CREATE TABLE qualified_component(candidate_cell_id VARCHAR,security_id VARCHAR,
                component_id VARCHAR,start_date DATE,end_date DATE,qualified BOOLEAN);
                INSERT INTO qualified_component VALUES
                ('p','S1','pc1','2026-01-01','2026-01-02',true),
                ('s','S1','sc1','2026-01-02','2026-01-02',true),
                ('w','S1','wc1','2026-01-02','2026-01-03',true);
                CREATE TABLE event_zone(candidate_cell_id VARCHAR,zone_span_days INTEGER);
                INSERT INTO event_zone VALUES ('p',2),('s',1),('w',2);
                CREATE VIEW strict_pairs AS SELECT 'p' primary_candidate_cell_id,'s' sidecar_candidate_cell_id;
                CREATE VIEW window_pairs AS SELECT 'p' primary_candidate_cell_id,'w' comparison_candidate_cell_id;"""
            )
            _create_strict_core_profile(con)
            _create_window_profile(con)
            strict = con.execute(
                """SELECT strict_core_confirmed_day_count,strict_core_event_count,
                shell_only_event_count,strict_core_subset_status
                FROM strict_core_shell_profile"""
            ).fetchone()
            self.assertEqual(strict, (1, 1, 0, "passed"))
            strict_diagnostic_sql = (
                "CREATE TABLE strict_core_diagnostic_profile AS"
                + _DIAGNOSTIC_PROFILE_SQL.split(
                    "CREATE TABLE strict_core_diagnostic_profile AS", 1
                )[1].split("CREATE TABLE window_diagnostic_profile AS", 1)[0]
            )
            con.execute(strict_diagnostic_sql)
            strict_extra = con.execute(
                """SELECT strict_core_qualified_component_count,
                strict_core_qualified_component_share,
                shell_only_qualified_component_count,strict_core_confirmed_density
                FROM strict_core_diagnostic_profile"""
            ).fetchone()
            self.assertEqual(strict_extra, (1, 1.0, 0, 1.0))
            window = con.execute(
                """SELECT intersection_confirmed_days,W120_only_confirmed_days,
                W250_only_confirmed_days,union_confirmed_days,confirmed_day_jaccard,
                matched_event_count,overlapping_event_count
                FROM window_overlap_comparison"""
            ).fetchone()
            self.assertEqual(window, (1, 1, 1, 3, 1 / 3, 1, 1))
            window_components = con.execute(
                """SELECT W120_only_event_count,W250_only_event_count,
                component_overlap_count,W120_only_component_count,
                W250_only_component_count FROM window_supplemental_source"""
            ).fetchone()
            self.assertEqual(window_components, (0, 0, 1, 0, 0))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
