from __future__ import annotations

import csv
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

import duckdb

from src.r2.r2_t03_event_zone_scan import (
    _build_postscan_profiles_transactionally,
    _write_cell_execution_registry,
)
from src.r2.r2_t03_independent_validator import (
    R2T03IndependentValidationError,
    _assert_oracle_execution_counts,
    independent_strict_core_oracle,
    independent_window_oracle,
)
from src.r2.r2_t03_metrics import (
    WINDOW_CORE_OUTPUT_FIELDS,
    WINDOW_SUPPLEMENTAL_OUTPUT_FIELDS,
    _contract_values,
    _create_window_profile,
    deterministic_window_comparison,
)


def span(security: str, *dates: str) -> set[tuple[str, str]]:
    return {(security, date) for date in dates}


class R2T03WindowComponentIdentityTest(unittest.TestCase):
    def test_same_local_component_id_is_scoped_by_security(self) -> None:
        value = deterministic_window_comparison(
            set(),
            set(),
            primary_eligible=set(),
            comparison_eligible=set(),
            primary_events={},
            comparison_events={},
            primary_components={
                ("S1", "component_001"): span("S1", "2026-01-01"),
                ("S2", "component_001"): span("S2", "2026-01-01"),
            },
            comparison_components={("S1", "component_001"): span("S1", "2026-01-01")},
        )
        self.assertEqual(value["component_overlap_count"], 1)
        self.assertEqual(value["W120_only_component_count"], 1)

    def test_component_overlap_requires_same_security_and_closed_intersection(
        self,
    ) -> None:
        cross_security = deterministic_window_comparison(
            set(),
            set(),
            primary_eligible=set(),
            comparison_eligible=set(),
            primary_events={},
            comparison_events={},
            primary_components={"p": span("S1", "2026-01-01")},
            comparison_components={"c": span("S2", "2026-01-01")},
        )
        same_security = deterministic_window_comparison(
            set(),
            set(),
            primary_eligible=set(),
            comparison_eligible=set(),
            primary_events={},
            comparison_events={},
            primary_components={"p": span("S1", "2026-01-01", "2026-01-03")},
            comparison_components={"c": span("S1", "2026-01-03", "2026-01-04")},
        )
        self.assertEqual(cross_security["component_overlap_count"], 0)
        self.assertEqual(same_security["component_overlap_count"], 1)

    def test_event_matching_and_strict_core_never_cross_security(self) -> None:
        window = independent_window_oracle(
            set(),
            set(),
            set(),
            set(),
            {("S1", "event_001"): span("S1", "2026-01-01")},
            {("S2", "event_001"): span("S2", "2026-01-01")},
        )
        strict = independent_strict_core_oracle(
            {("S1", "event_001"): span("S1", "2026-01-01")},
            {("S2", "event_001"): span("S2", "2026-01-01")},
            span("S1", "2026-01-01"),
            span("S2", "2026-01-01"),
        )
        self.assertEqual(window["matched_event_count"], 0)
        self.assertEqual(strict["strict_core_event_count"], 0)

    def test_full_window_profile_handles_component_001_on_two_securities(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                """CREATE TABLE atomic_confirmed_daily(candidate_cell_id VARCHAR,
                security_id VARCHAR,trade_date DATE,confirmed_state BOOLEAN,
                eligible BOOLEAN,quality_state VARCHAR);
                INSERT INTO atomic_confirmed_daily VALUES
                ('p','S1','2026-01-01',true,true,'valid'),
                ('p','S2','2026-01-01',true,true,'valid'),
                ('w','S1','2026-01-01',true,true,'valid');
                CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR,
                scan_event_id VARCHAR,security_id VARCHAR,trade_date DATE,
                event_zone_member BOOLEAN,confirmed_state BOOLEAN,
                retrospective_component_member BOOLEAN);
                INSERT INTO event_zone_membership_daily VALUES
                ('p','event_001','S1','2026-01-01',true,true,true),
                ('p','event_001','S2','2026-01-01',true,true,true),
                ('w','event_001','S1','2026-01-01',true,true,true);
                CREATE TABLE qualified_component(candidate_cell_id VARCHAR,
                security_id VARCHAR,component_id VARCHAR,start_date DATE,end_date DATE,
                confirmed_day_count INTEGER,qualified BOOLEAN);
                INSERT INTO qualified_component VALUES
                ('p','S1','component_001','2026-01-01','2026-01-01',1,true),
                ('p','S2','component_001','2026-01-01','2026-01-01',1,true),
                ('w','S1','component_001','2026-01-01','2026-01-01',1,true);
                CREATE VIEW window_pairs AS SELECT 'p' primary_candidate_cell_id,
                'w' comparison_candidate_cell_id;"""
            )
            _create_window_profile(con)
            self.assertEqual(
                con.execute(
                    "SELECT component_overlap_count,W120_only_component_count,"
                    "W250_only_component_count FROM window_supplemental_source"
                ).fetchone(),
                (1, 1, 0),
            )
        finally:
            con.close()

    def test_explicit_field_contract_ignores_dict_insertion_order(self) -> None:
        fields = WINDOW_CORE_OUTPUT_FIELDS + WINDOW_SUPPLEMENTAL_OUTPUT_FIELDS
        shuffled = OrderedDict(
            (field, index) for index, field in reversed(list(enumerate(fields)))
        )
        self.assertEqual(
            _contract_values(shuffled, fields, "window"), list(range(len(fields)))
        )
        with self.assertRaisesRegex(ValueError, "field_contract_failed"):
            _contract_values({**shuffled, "unexpected": 1}, fields, "window")

    def test_oracle_execution_counts_fail_closed(self) -> None:
        _assert_oracle_execution_counts(16, 144, 16, 144)
        with self.assertRaisesRegex(
            R2T03IndependentValidationError, "base_k3_replay_count_mismatch"
        ):
            _assert_oracle_execution_counts(144, 144, 16, 144)

    def test_comparison_work_is_bucketed_by_security(self) -> None:
        primary = {
            (f"S{i:04d}", "e1"): span(f"S{i:04d}", "2026-01-01") for i in range(200)
        }
        comparison = {
            (f"S{i:04d}", "e1"): span(f"S{i:04d}", "2026-01-01") for i in range(200)
        }
        with patch(
            "src.r2.r2_t03_metrics._date_spans_overlap", wraps=lambda a, b: True
        ) as overlap:
            value = deterministic_window_comparison(
                set(),
                set(),
                primary_eligible=set(),
                comparison_eligible=set(),
                primary_events=primary,
                comparison_events=comparison,
            )
        self.assertEqual(value["matched_event_count"], 200)
        self.assertEqual(overlap.call_count, 200)

    def test_registry_survives_profile_transaction_rollback(self) -> None:
        rows = [
            {
                "candidate_cell_id": f"cell_{index:02d}",
                "route_id": "route",
                "d": 1,
                "g": 0,
                "status": "completed",
                "security_count": 2,
                "component_count": 3,
                "event_count": 1,
                "error": "",
            }
            for index in range(72)
        ]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            _write_cell_execution_registry(output, rows)
            con = duckdb.connect(":memory:")
            con.execute(
                "CREATE TABLE scan_fact(value INTEGER); "
                "INSERT INTO scan_fact VALUES (1)"
            )

            def fail_profile(connection: duckdb.DuckDBPyConnection) -> None:
                connection.execute("CREATE TABLE partial_profile(value INTEGER)")
                raise RuntimeError("profile_failure")

            try:
                with (
                    patch(
                        "src.r2.r2_t03_event_zone_scan._assert_postscan_interface_integrity"
                    ),
                    patch(
                        "src.r2.r2_t03_event_zone_scan._create_profiles_and_comparisons",
                        side_effect=fail_profile,
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "profile_failure"):
                        _build_postscan_profiles_transactionally(con)
                self.assertEqual(
                    con.execute("SELECT count(*) FROM scan_fact").fetchone()[0], 1
                )
                self.assertEqual(
                    con.execute(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_name='partial_profile'"
                    ).fetchone()[0],
                    0,
                )
            finally:
                con.close()
            with (output / "r2_t03_cell_execution_registry.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual(len(saved), 72)
            self.assertTrue(all(row["status"] == "completed" for row in saved))


if __name__ == "__main__":
    unittest.main()
