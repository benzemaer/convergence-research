from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t04_state_line_profiles import (
    COMPARISONS,
    _comparison_status,
    _overlap_rows,
    _parent_child_rows,
    _quantile_ordered,
)


class R1T04StateLineProfilesTest(unittest.TestCase):
    def test_registry_is_exact_and_q_is_fixed(self) -> None:
        config = json.loads(
            Path("configs/r1/r1_t04_state_line_profiles.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["q"], 0.2)
        self.assertEqual(len(config["profiles"]), 7)
        self.assertEqual(
            len(
                {
                    (row["state_line"], row["candidate_config_id"])
                    for row in config["profiles"]
                }
            ),
            7,
        )

    def test_description_status_never_selects_a_winner(self) -> None:
        self.assertEqual(
            _comparison_status("reference_vs_fast_challenger", 0.1, 0.2, 0.8),
            "sensitivity_coherence_tradeoff",
        )
        self.assertNotIn(
            "best", _comparison_status("reference_vs_long_window", -0.1, -0.1, 1.2)
        )

    def test_duration_quantile_order(self) -> None:
        self.assertTrue(
            _quantile_ordered(
                {
                    "min": 1,
                    "q10": 1,
                    "q25": 2,
                    "q50": 3,
                    "q75": 3,
                    "q90": 4,
                    "q95": 4,
                    "q99": 5,
                    "max": 6,
                }
            )
        )
        self.assertFalse(
            _quantile_ordered(
                {
                    "min": 2,
                    "q10": 1,
                    "q25": 2,
                    "q50": 3,
                    "q75": 3,
                    "q90": 4,
                    "q95": 4,
                    "q99": 5,
                    "max": 6,
                }
            )
        )

    def test_onset_overlap_and_parent_child_geometry_are_materialized(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {}
            config_ids = {
                config_id
                for _, _, reference, challenger, _ in COMPARISONS
                for config_id in (reference, challenger)
            }
            for config_id in config_ids:
                daily = root / f"{config_id}_daily.parquet"
                interval = root / f"{config_id}_interval.parquet"
                con = duckdb.connect()
                con.execute(
                    """
                    CREATE TABLE daily(
                      security_id VARCHAR, trading_date VARCHAR, state_name VARCHAR,
                      raw_state BOOLEAN, confirmed_state BOOLEAN,
                      validity_status VARCHAR
                    )
                    """
                )
                for state in ("S_PCT", "S_PCVT"):
                    for date, raw, confirmed in (
                        ("20200101", False, False),
                        ("20200102", True, False),
                        ("20200103", True, True),
                        ("20200104", False, False),
                    ):
                        con.execute(
                            "INSERT INTO daily VALUES ('A', ?, ?, ?, ?, 'valid')",
                            [date, state, raw, confirmed],
                        )
                con.execute(
                    """
                    CREATE TABLE intervals(
                      security_id VARCHAR, state_level VARCHAR, raw_start_date VARCHAR,
                      confirmation_time VARCHAR, confirmed_start_date VARCHAR,
                      interval_end_date VARCHAR, confirmed_length INTEGER
                    )
                    """
                )
                for state in ("S_PCT", "S_PCVT"):
                    con.execute(
                        "INSERT INTO intervals VALUES "
                        "('A', ?, '20200102', '20200103', '20200103', '20200103', 1)",
                        [state],
                    )
                con.execute(f"COPY daily TO '{daily.as_posix()}' (FORMAT PARQUET)")
                con.execute(
                    f"COPY intervals TO '{interval.as_posix()}' (FORMAT PARQUET)"
                )
                con.close()
                sources[config_id] = (
                    f"read_parquet('{daily.as_posix()}')",
                    f"read_parquet('{interval.as_posix()}')",
                )
            overlap = _overlap_rows(sources, "fixture", "a" * 40)
            self.assertTrue(all(row["both_onset"] is not None for row in overlap))
            self.assertTrue(all(row["onset_jaccard"] == 1.0 for row in overlap))
            geometry = _parent_child_rows(
                *sources["R0_W250_Q20_K3_WEAK_D010"],
                "R0_W250_Q20_K3_WEAK_D010",
                "fixture",
                "a" * 40,
            )
            raw, confirmed = geometry
            self.assertEqual(raw["geometry_unit"], "raw_segment")
            self.assertEqual(confirmed["geometry_unit"], "confirmed_interval")
            self.assertEqual(raw["child_segment_containment_mismatch_count"], 0)
            self.assertEqual(confirmed["child_interval_containment_mismatch_count"], 0)
            self.assertIsNotNone(raw["child_start_delay_from_parent_observations"])
            self.assertIsNotNone(confirmed["child_duration_share_of_parent_interval"])


if __name__ == "__main__":
    unittest.main()
