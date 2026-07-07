from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r0.candidate_artifact_engine import (
    BLOCKED,
    LEGACY_V1_FIELD_NAMES,
    UNKNOWN,
    VALID,
    assemble_candidate_daily_rows,
    assemble_confirmed_interval_rows,
    assert_no_forbidden_candidate_outputs,
    build_candidate_configs,
    build_candidate_manifest,
    check_candidate_lineage,
    content_hash,
    file_content_hash,
    write_candidate_artifacts,
)

SECURITY_ID = "000001.SZ"
TRADING_DATE = "2026-02-03"
RUN_ID = "R0-T08-SYNTHETIC"
CODE_COMMIT = "abcdef123456"
INPUT_DATA_VERSION = "synthetic-r0-grid-v1"
LINEAGE = (
    "synthetic_in_memory_r0_grid_inputs",
    "r0_t04_raw_metric_engine",
    "r0_t05_strict_past_percentile_score",
    "r0_t06_weak_dimension_nested_state",
    "r0_t07_confirmation_streak_interval",
)


def raw_metric(indicator_id: str, value: float) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "indicator_id": indicator_id,
        "raw_value": value,
        "validity_status": VALID,
        "reason_codes": ["valid_no_blocker"],
    }


def indicator_score(
    indicator_id: str,
    *,
    window: int = 250,
    percentile: float = 0.82,
    score: float = 0.82,
    eligible: bool = True,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "indicator_id": indicator_id,
        "raw_value": percentile,
        "eligible": eligible,
        "percentile": percentile,
        "score": score,
        "validity_status": status,
        "reason_codes": list(reasons),
    }


def dimension_score(dimension: str, *, window: int = 250) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "dimension": dimension,
        "score_dimension": 0.83,
        "score_dimension_min": 0.74,
        "eligible_dimension": True,
        "validity_status": VALID,
        "reason_codes": ["valid_no_blocker"],
        "component_indicator_ids": [f"{dimension}1", f"{dimension}2"],
    }


def nested_state(
    *,
    window: int = 250,
    q: float = 0.20,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "P_raw": True,
        "C_raw": True,
        "T_raw": True,
        "V_raw": True,
        "S_P_raw": True,
        "S_PC_raw": True,
        "S_PCT_raw": True,
        "S_PCVT_raw": True,
        "exclusive_state_layer": "PCVT",
        "eligible_state": True,
        "validity_status": status,
        "reason_codes": list(reasons),
    }


def confirmation(
    state_name: str,
    *,
    window: int = 250,
    q: float = 0.20,
    k: int = 3,
    confirmed: bool | None = True,
    streak: int | None = 3,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "confirmation_k": k,
        "state_name": state_name,
        "raw_state": confirmed,
        "raw_streak": streak,
        "raw_streak_start_date": "2026-02-01",
        "confirmed_state": confirmed,
        "confirmation_start_date": "2026-02-01" if confirmed else None,
        "confirmation_date": TRADING_DATE if confirmed else None,
        "validity_status": status,
        "reason_codes": list(reasons),
    }


def interval(
    state_name: str = "S_PCVT", *, open_interval: bool = False
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "percentile_window_W": 250,
        "q": 0.20,
        "weak_delta": 0.10,
        "confirmation_k": 3,
        "state_name": state_name,
        "interval_id": (
            f"{SECURITY_ID}|W250|q0.20|d0.10|K3|{state_name}|2026-02-03|0001"
        ),
        "raw_start_date": "2026-02-01",
        "confirmation_date": "2026-02-03",
        "confirmed_start_date": "2026-02-03",
        "interval_end_date": None if open_interval else "2026-02-05",
        "last_observed_date": "2026-02-06" if not open_interval else "2026-02-05",
        "duration_raw_days": 5,
        "duration_confirmed_days": 3,
        "is_open_interval": open_interval,
        "termination_reason": "end_of_input_open"
        if open_interval
        else "raw_state_false",
        "validity_status": VALID,
        "reason_codes": ["valid_no_blocker"],
    }


def raw_metrics() -> list[dict[str, object]]:
    return [
        raw_metric("P1_NATR14", 0.11),
        raw_metric("P2_LogRange20", 0.12),
        raw_metric("C1_LogMASpread_5_60", 0.13),
        raw_metric("C2_AdjVWAPSpread_5_60", 0.14),
        raw_metric("T1_ER20", 0.15),
        raw_metric("T2_AbsTrendT20", 0.16),
        raw_metric("V1_TurnoverShrink20_60", 0.17),
        raw_metric("V2_LogAmount20_base", 0.18),
    ]


def indicator_scores() -> list[dict[str, object]]:
    return [
        indicator_score("P1_NATR14", percentile=0.71),
        indicator_score("P2_LogRange20", percentile=0.72),
        indicator_score("C1_LogMASpread_5_60", percentile=0.73),
        indicator_score("C2_AdjVWAPSpread_5_60", percentile=0.74),
        indicator_score("T1_ER20", percentile=0.75),
        indicator_score("T2_AbsTrendT20", percentile=0.76),
        indicator_score("V1_TurnoverShrink20_60", percentile=0.77),
        indicator_score("V2_AmountLevel20Pct", percentile=0.21),
    ]


def dimension_scores() -> list[dict[str, object]]:
    return [dimension_score(dimension) for dimension in ("P", "C", "T", "V")]


def confirmations(k: int = 3) -> list[dict[str, object]]:
    return [
        confirmation(state_name, k=k)
        for state_name in ("S_P", "S_PC", "S_PCT", "S_PCVT")
    ]


def assembled_daily_rows(**overrides) -> tuple[dict[str, object], ...]:
    params = {
        "raw_metric_results": raw_metrics(),
        "indicator_score_results": indicator_scores(),
        "dimension_score_results": dimension_scores(),
        "nested_daily_state_results": [nested_state()],
        "daily_confirmation_results": confirmations(),
        "run_id": RUN_ID,
        "code_commit": CODE_COMMIT,
        "input_data_version": INPUT_DATA_VERSION,
        "source_lineage": LINEAGE,
    }
    params.update(overrides)
    return assemble_candidate_daily_rows(**params)


def baseline_row(rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    return next(
        row for row in rows if row["candidate_config_id"] == "R0_W250_Q20_K3_WEAK_D010"
    )


class R0T08CandidateArtifactEngineTest(unittest.TestCase):
    def test_candidate_config_grid_is_stable_and_excludes_k1(self) -> None:
        configs = build_candidate_configs()
        self.assertEqual(len(configs), 27)
        self.assertEqual(
            {item.percentile_window_W for item in configs}, {120, 250, 500}
        )
        self.assertEqual({item.low_quantile_q for item in configs}, {0.10, 0.20, 0.30})
        self.assertEqual({item.confirmation_days_K for item in configs}, {2, 3, 5})
        self.assertNotIn(1, {item.confirmation_days_K for item in configs})

        baseline = [item for item in configs if item.is_baseline_config]
        self.assertEqual(len(baseline), 1)
        self.assertEqual(baseline[0].candidate_config_id, "R0_W250_Q20_K3_WEAK_D010")
        self.assertEqual(
            [item.as_dict() for item in configs],
            [item.as_dict() for item in build_candidate_configs()],
        )
        self.assertNotIn(RUN_ID, baseline[0].config_hash)
        self.assertNotIn("2026", baseline[0].config_hash)
        self.assertNotIn("D:", baseline[0].config_hash)

    def test_daily_artifact_joins_same_w_q_k_and_preserves_fields(self) -> None:
        rows = assembled_daily_rows(
            daily_confirmation_results=[
                *confirmations(k=3),
                confirmation("S_PCVT", k=2, confirmed=False, streak=1),
            ]
        )
        row = baseline_row(rows)

        self.assertEqual(row["NATR14_raw"], 0.11)
        self.assertEqual(row["LogAmount20_raw"], 0.18)
        self.assertEqual(row["TurnoverShrink20_60_raw"], 0.17)
        self.assertEqual(row["AmountLevel20Pct"], 0.21)
        self.assertNotIn("AmountLevel20Pct_raw", row)
        self.assertTrue(row["S_PCVT_conf"])
        self.assertEqual(row["streak_PCVT"], 3)
        self.assertEqual(row["confirmation_date_PCVT"], TRADING_DATE)
        self.assertEqual(row["validity_state"], VALID)

        k2_row = next(
            item
            for item in rows
            if item["candidate_config_id"] == "R0_W250_Q20_K2_WEAK_D010"
        )
        self.assertFalse(k2_row["S_PCVT_conf"])
        self.assertNotEqual(k2_row["S_PCVT_conf"], row["S_PCVT_conf"])

    def test_unknown_blocked_and_missing_upstream_are_not_coerced_to_false(
        self,
    ) -> None:
        unknown_rows = assembled_daily_rows(
            nested_daily_state_results=[
                nested_state(status=UNKNOWN, reasons=("upstream_unknown",))
            ],
            daily_confirmation_results=[
                confirmation(
                    "S_PCVT",
                    confirmed=None,
                    streak=None,
                    status=UNKNOWN,
                    reasons=("upstream_unknown",),
                )
            ],
        )
        row = baseline_row(unknown_rows)
        self.assertIsNone(row["S_P_conf"])
        self.assertIsNone(row["S_PCVT_conf"])
        self.assertEqual(row["validity_state"], UNKNOWN)
        self.assertIn("missing_upstream_result", row["unknown_reason_codes"])
        self.assertIn("upstream_unknown", row["unknown_reason_codes"])

        blocked_rows = assembled_daily_rows(
            nested_daily_state_results=[
                nested_state(status=BLOCKED, reasons=("upstream_blocked",))
            ]
        )
        self.assertEqual(baseline_row(blocked_rows)["validity_state"], BLOCKED)

    def test_input_order_does_not_change_daily_output_or_hash(self) -> None:
        normal = assembled_daily_rows()
        shuffled = assembled_daily_rows(
            raw_metric_results=list(reversed(raw_metrics())),
            indicator_score_results=list(reversed(indicator_scores())),
            dimension_score_results=list(reversed(dimension_scores())),
            daily_confirmation_results=list(reversed(confirmations())),
        )
        self.assertEqual(normal, shuffled)
        self.assertEqual(content_hash(normal), content_hash(shuffled))

    def test_interval_artifact_mapping_closed_and_open(self) -> None:
        rows = assemble_confirmed_interval_rows(
            confirmed_interval_results=[
                interval(),
                interval("S_P", open_interval=True),
            ],
            run_id=RUN_ID,
            code_commit=CODE_COMMIT,
            input_data_version=INPUT_DATA_VERSION,
            source_lineage=LINEAGE,
        )
        closed = next(item for item in rows if item["state_level"] == "S_PCVT")
        self.assertEqual(closed["confirmation_time"], "2026-02-03")
        self.assertEqual(closed["last_raw_active_date"], "2026-02-05")
        self.assertEqual(closed["termination_time"], "2026-02-06")
        self.assertEqual(closed["termination_type"], "raw_state_false")
        self.assertEqual(closed["raw_length"], 5)
        self.assertEqual(closed["confirmed_length"], 3)

        open_row = next(item for item in rows if item["state_level"] == "S_P")
        self.assertEqual(open_row["last_raw_active_date"], "2026-02-05")
        self.assertIsNone(open_row["termination_time"])
        self.assertEqual(open_row["termination_type"], "end_of_input_open")

    def test_manifest_summarizes_counts_hashes_and_field_availability(self) -> None:
        daily_rows = assembled_daily_rows()
        interval_rows = assemble_confirmed_interval_rows(
            confirmed_interval_results=[interval(open_interval=True)],
            run_id=RUN_ID,
            code_commit=CODE_COMMIT,
            input_data_version=INPUT_DATA_VERSION,
            source_lineage=LINEAGE,
        )
        manifest = build_candidate_manifest(
            daily_rows=daily_rows,
            interval_rows=interval_rows,
            run_id=RUN_ID,
            created_at="2026-07-07T00:00:00Z",
            code_commit=CODE_COMMIT,
            repository="benzemaer/convergence-research",
            input_data_version=INPUT_DATA_VERSION,
            input_sources=LINEAGE,
            input_hashes={"synthetic": "abc123"},
            input_row_counts={"nested_daily_state_results": 1},
        )

        self.assertEqual(manifest["candidate_config_count"], 27)
        self.assertEqual(
            manifest["baseline_candidate_config_id"], "R0_W250_Q20_K3_WEAK_D010"
        )
        self.assertEqual(manifest["daily_content_hash"], content_hash(daily_rows))
        self.assertEqual(manifest["interval_content_hash"], content_hash(interval_rows))
        self.assertEqual(
            manifest["quality_summary"]["row_count_by_config"][
                "R0_W250_Q20_K3_WEAK_D010"
            ],
            1,
        )
        self.assertEqual(
            manifest["quality_summary"]["interval_count_by_config"][
                "R0_W250_Q20_K3_WEAK_D010"
            ],
            1,
        )
        self.assertIn("schema_versions", manifest)
        self.assertIn("contract_ids", manifest)
        self.assertIn(
            "null_field_counts", manifest["field_availability"]["daily_state_artifact"]
        )
        self.assertIn(
            "TurnoverShrink20_60_raw",
            manifest["field_availability"]["daily_state_artifact"]["required_fields"],
        )

    def test_forbidden_outputs_and_lineage_guards(self) -> None:
        forbidden = assert_no_forbidden_candidate_outputs(
            {
                "future_label": "up",
                "future_return": 0.1,
                "breakout_direction": "up",
                "backtest": {},
                "portfolio": [],
                "pnl": 1.0,
                "trade_signal": "buy",
                "buy_signal": True,
                "sell_signal": False,
            }
        )
        self.assertEqual(forbidden.validity_status, BLOCKED)
        self.assertIn("forbidden_output_field", forbidden.reason_codes)

        self.assertEqual(check_candidate_lineage(LINEAGE).validity_status, VALID)
        for source in (
            "data/raw/vendor.csv",
            "data/external/ref.csv",
            "data/generated/r0/formal.parquet",
            "MarketDB/prices",
            "SH000001.day",
        ):
            with self.subTest(source=source):
                result = check_candidate_lineage([source])
                self.assertEqual(result.validity_status, BLOCKED)
                self.assertIn("direct_real_data_source_forbidden", result.reason_codes)

    def test_legacy_v1_fields_are_forbidden_as_keys_and_sequence_values(self) -> None:
        for legacy_name in sorted(LEGACY_V1_FIELD_NAMES):
            with self.subTest(location="key", legacy_name=legacy_name):
                result = assert_no_forbidden_candidate_outputs({legacy_name: 0.1})
                self.assertEqual(result.validity_status, BLOCKED)
                self.assertIn("legacy_v1_field_forbidden", result.reason_codes)

            with self.subTest(location="schema_list", legacy_name=legacy_name):
                result = assert_no_forbidden_candidate_outputs(
                    {"candidate_daily_state_required_fields": [legacy_name]}
                )
                self.assertEqual(result.validity_status, BLOCKED)
                self.assertIn("legacy_v1_field_forbidden", result.reason_codes)

    def test_r0_t08_valid_outputs_do_not_use_legacy_v1_names(self) -> None:
        daily_rows = assembled_daily_rows()
        interval_rows = assemble_confirmed_interval_rows(
            confirmed_interval_results=[interval()],
            run_id=RUN_ID,
            code_commit=CODE_COMMIT,
            input_data_version=INPUT_DATA_VERSION,
            source_lineage=LINEAGE,
        )
        manifest = build_candidate_manifest(
            daily_rows=daily_rows,
            interval_rows=interval_rows,
            run_id=RUN_ID,
            created_at="2026-07-07T00:00:00Z",
            code_commit=CODE_COMMIT,
            repository="benzemaer/convergence-research",
            input_data_version=INPUT_DATA_VERSION,
            input_sources=LINEAGE,
            input_hashes={"synthetic": "abc123"},
            input_row_counts={"daily": len(daily_rows)},
        )
        serialized = json.dumps(
            {
                "daily_rows": daily_rows,
                "interval_rows": interval_rows,
                "manifest": manifest,
            },
            sort_keys=True,
        )
        for legacy_name in LEGACY_V1_FIELD_NAMES:
            with self.subTest(legacy_name=legacy_name):
                self.assertNotIn(legacy_name, serialized)

    def test_writer_uses_tmpdir_and_is_deterministic(self) -> None:
        daily_rows = assembled_daily_rows()
        interval_rows = assemble_confirmed_interval_rows(
            confirmed_interval_results=[interval()],
            run_id=RUN_ID,
            code_commit=CODE_COMMIT,
            input_data_version=INPUT_DATA_VERSION,
            source_lineage=LINEAGE,
        )
        manifest = build_candidate_manifest(
            daily_rows=daily_rows,
            interval_rows=interval_rows,
            run_id=RUN_ID,
            created_at="2026-07-07T00:00:00Z",
            code_commit=CODE_COMMIT,
            repository="benzemaer/convergence-research",
            input_data_version=INPUT_DATA_VERSION,
            input_sources=LINEAGE,
            input_hashes={"synthetic": "abc123"},
            input_row_counts={"daily": len(daily_rows)},
        )
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_result = write_candidate_artifacts(
                first,
                daily_rows=daily_rows,
                interval_rows=interval_rows,
                manifest=manifest,
            )
            second_result = write_candidate_artifacts(
                second,
                daily_rows=daily_rows,
                interval_rows=interval_rows,
                manifest=manifest,
            )
            self.assertTrue(Path(first_result["daily_path"]).is_file())
            self.assertEqual(
                first_result["daily_content_hash"],
                file_content_hash(first_result["daily_path"]),
            )
            self.assertEqual(
                first_result["daily_content_hash"], second_result["daily_content_hash"]
            )
            self.assertEqual(
                json.loads(
                    Path(first_result["manifest_path"]).read_text(encoding="utf-8")
                ),
                json.loads(
                    Path(second_result["manifest_path"]).read_text(encoding="utf-8")
                ),
            )


if __name__ == "__main__":
    unittest.main()
