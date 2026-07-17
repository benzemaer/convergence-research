# ruff: noqa: E501
"""DuckDB set-based producer for EXP-A03.

Only compact aggregates are returned to Python.  The accepted A01 database is
opened read-only by the runner; this module never creates a persistent store or
iterates over raw observations in Python.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A03"
RAW_TABLE = "exp_a01_raw_metrics"
A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATORS = (A1_ID, A2_ID, A2B_ID)
PAIR_DEFS = {
    "A1_A2": (A1_ID, A2_ID, "a1", "a2"),
    "A1_A2b": (A1_ID, A2B_ID, "a1", "a2b"),
    "A2_A2b": (A2_ID, A2B_ID, "a2", "a2b"),
}
TAILS = (0.01, 0.05, 0.1)
A2_GRID_TOLERANCE = 1e-10
OUTPUT_FILES = {
    "pairwise_overall": "exp_a03_pairwise_overall.csv",
    "pairwise_year": "exp_a03_pairwise_year.csv",
    "pairwise_security": "exp_a03_pairwise_security.csv",
    "tail_overlap": "exp_a03_tail_overlap.csv",
    "conditional_profile": "exp_a03_a2_a2b_conditional_profile.csv",
    "variance_decomposition": "exp_a03_a2_a2b_variance_decomposition.csv",
    "stability_summary": "exp_a03_stability_summary.csv",
    "candidate_disposition": "exp_a03_candidate_disposition.json",
    "manifest": "exp_a03_manifest.json",
    "validator_result": "exp_a03_validator_result.json",
    "anomaly_scan": "exp_a03_anomaly_scan.json",
    "result_analysis": "exp_a03_result_analysis.md",
}
CSV_FIELDS = {
    "pairwise_overall": (
        "pair_id",
        "left_indicator_id",
        "right_indicator_id",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "left_unique_value_count",
        "right_unique_value_count",
        "left_tied_row_count",
        "right_tied_row_count",
    ),
    "pairwise_year": (
        "pair_id",
        "calendar_year",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
    ),
    "pairwise_security": (
        "pair_id",
        "security_id",
        "common_count",
        "eligible",
        "pearson_raw",
        "spearman_midrank",
        "reason",
    ),
    "tail_overlap": (
        "pair_id",
        "tail_fraction",
        "left_indicator_id",
        "right_indicator_id",
        "left_threshold",
        "right_threshold",
        "left_selected_count",
        "left_realized_rate",
        "right_selected_count",
        "right_realized_rate",
        "intersection_count",
        "union_count",
        "jaccard",
        "left_containment",
        "right_containment",
    ),
    "conditional_profile": (
        "a2_level",
        "row_count",
        "row_share",
        "a2b_min",
        "a2b_q05",
        "a2b_q25",
        "a2b_median",
        "a2b_q75",
        "a2b_q95",
        "a2b_max",
        "a2b_mean",
        "a2b_stddev_pop",
        "a2b_unique_value_count",
    ),
    "variance_decomposition": (
        "global_mean",
        "total_ss",
        "between_group_ss",
        "within_group_ss",
        "eta_squared",
        "within_variance_ratio",
        "reconciliation_residual",
    ),
    "stability_summary": (
        "pair_id",
        "overall_pearson",
        "overall_spearman",
        "year_count",
        "year_spearman_min",
        "year_spearman_q25",
        "year_spearman_median",
        "year_spearman_q75",
        "year_spearman_max",
        "year_negative_count",
        "security_total_count",
        "security_eligible_count",
        "security_insufficient_count",
        "security_spearman_q10",
        "security_spearman_q25",
        "security_spearman_median",
        "security_spearman_q75",
        "security_spearman_q90",
        "security_negative_count",
    ),
}
ANALYSIS_HEADINGS = [
    "## 1. Actual run / reviewed SHA",
    "## 2. Accepted EXP-A02 handoff",
    "## 3. Input artifacts and lineage",
    "## 4. Frozen common-valid universe",
    "## 5. Overall pairwise relationships",
    "## 6. Year stability",
    "## 7. Security stability",
    "## 8. Low-tail identity overlap",
    "## 9. A2 grid and tie structure",
    "## 10. A2b conditional variation within A2",
    "## 11. A2-to-A2b variance decomposition",
    "## 12. A2/A2b redundancy gate",
    "## 13. A2 representation adequacy",
    "## 14. A1 collision diagnostics",
    "## 15. Provisional candidate dispositions",
    "## 16. Full invariant validation",
    "## 17. Independent aggregate recomputation",
    "## 18. Anomaly scan",
    "## 19. Supported conclusions",
    "## 20. Unsupported conclusions",
    "## 21. Readiness for Formal-result review",
]


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _finite(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _rows(connection: Any, query: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        dict(zip(fields, row, strict=True))
        for row in connection.execute(query).fetchall()
    ]


def _make_common(connection: Any, raw_table: str = RAW_TABLE) -> None:
    table = _quote(raw_table)
    connection.execute(f"""
      CREATE OR REPLACE TEMP TABLE a03_common AS
      SELECT security_id, trading_date, observation_sequence,
        MAX(raw_value) FILTER(WHERE indicator_id={_sql(A1_ID)}) a1,
        MAX(raw_value) FILTER(WHERE indicator_id={_sql(A2_ID)}) a2,
        MAX(raw_value) FILTER(WHERE indicator_id={_sql(A2B_ID)}) a2b
      FROM {table}
      WHERE indicator_id IN ({_sql(A1_ID)},{_sql(A2_ID)},{_sql(A2B_ID)})
        AND validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
        AND ((indicator_id IN ({_sql(A1_ID)},{_sql(A2B_ID)}) AND raw_value>=0)
             OR (indicator_id={_sql(A2_ID)} AND raw_value BETWEEN 0 AND 1))
      GROUP BY security_id,trading_date,observation_sequence
      HAVING COUNT(DISTINCT indicator_id)=3
    """)


def _rank_query(
    left: str, right: str, group: str = "", where: str | None = None
) -> str:
    partition = f"PARTITION BY {group}" if group else ""
    value_left = f"PARTITION BY {group},{left}" if group else f"PARTITION BY {left}"
    value_right = f"PARTITION BY {group},{right}" if group else f"PARTITION BY {right}"
    select_group = f"{group}," if group else ""
    group_clause = f" GROUP BY {group}" if group else ""
    return f"""
      WITH r AS (
        SELECT *,
          RANK() OVER({partition} ORDER BY {left}) + (COUNT(*) OVER({value_left})-1)/2.0 lm,
          RANK() OVER({partition} ORDER BY {right}) + (COUNT(*) OVER({value_right})-1)/2.0 rm,
          COUNT(*) OVER({partition}) n
        FROM a03_common {f"WHERE {where}" if where else ""}
      ), p AS (SELECT *, (lm-.5)/n lp, (rm-.5)/n rp FROM r)
      SELECT {select_group}COUNT(*) common_count,CORR({left},{right}) pearson_raw,CORR(lp,rp) spearman_midrank
      FROM p{group_clause}
    """


def _pairwise(
    connection: Any, config: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    years = list(config["candidate_universe"]["years"])
    security_ids = [
        row[0]
        for row in connection.execute(
            "SELECT security_id FROM a03_security_ids ORDER BY security_id"
        ).fetchall()
    ]
    overall: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    security_rows: list[dict[str, Any]] = []
    minimum = int(config["correlation"]["security_min_common_rows"])
    for pair_id, (left_id, right_id, left, right) in PAIR_DEFS.items():
        count, pearson, spearman = connection.execute(
            _rank_query(left, right)
        ).fetchone()
        tie_left, tie_right = connection.execute(
            f"SELECT (SELECT COALESCE(SUM(n) FILTER(WHERE n>1),0) FROM (SELECT {left},COUNT(*) n FROM a03_common GROUP BY {left})),(SELECT COALESCE(SUM(n) FILTER(WHERE n>1),0) FROM (SELECT {right},COUNT(*) n FROM a03_common GROUP BY {right}))"
        ).fetchone()
        left_unique, right_unique = connection.execute(
            f"SELECT COUNT(DISTINCT {left}),COUNT(DISTINCT {right}) FROM a03_common"
        ).fetchone()
        overall.append(
            {
                "pair_id": pair_id,
                "left_indicator_id": left_id,
                "right_indicator_id": right_id,
                "common_count": int(count),
                "pearson_raw": pearson,
                "spearman_midrank": spearman,
                "left_unique_value_count": int(left_unique),
                "right_unique_value_count": int(right_unique),
                "left_tied_row_count": int(tie_left),
                "right_tied_row_count": int(tie_right),
            }
        )
        for year in years:
            row = connection.execute(
                _rank_query(
                    left, right, "YEAR(trading_date)", f"YEAR(trading_date)={year}"
                )
            ).fetchone()
            if row is None:
                row = (0, None, None)
            else:
                row = row[1:]
            year_rows.append(
                {
                    "pair_id": pair_id,
                    "calendar_year": year,
                    "common_count": int(row[0] or 0),
                    "pearson_raw": row[1],
                    "spearman_midrank": row[2],
                }
            )
        security_query = _rank_query(left, right, "security_id")
        grouped = {
            row[0]: row[1:] for row in connection.execute(security_query).fetchall()
        }
        for security_id in security_ids:
            values = grouped.get(security_id, (0, None, None))
            eligible = int(values[0] or 0) >= minimum
            security_rows.append(
                {
                    "pair_id": pair_id,
                    "security_id": security_id,
                    "common_count": int(values[0] or 0),
                    "eligible": eligible,
                    "pearson_raw": values[1] if eligible else None,
                    "spearman_midrank": values[2] if eligible else None,
                    "reason": None if eligible else "insufficient_common_rows",
                }
            )
    return overall, year_rows, security_rows


def _tail_overlap(connection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair_id, (left_id, right_id, left, right) in PAIR_DEFS.items():
        for fraction in TAILS:
            row = connection.execute(f"""
              WITH t AS (SELECT QUANTILE_DISC({left},{fraction}) lt,QUANTILE_DISC({right},{fraction}) rt FROM a03_common), f AS (SELECT {left}<=(SELECT lt FROM t) l,{right}<=(SELECT rt FROM t) r FROM a03_common)
              SELECT (SELECT lt FROM t),(SELECT rt FROM t),COUNT(*) FILTER(WHERE l),COUNT(*) FILTER(WHERE r),COUNT(*) FILTER(WHERE l AND r),COUNT(*) FILTER(WHERE l OR r),COUNT(*) FROM f
            """).fetchone()
            lt, rt, lc, rc, inter, union, total = row
            rows.append(
                {
                    "pair_id": pair_id,
                    "tail_fraction": fraction,
                    "left_indicator_id": left_id,
                    "right_indicator_id": right_id,
                    "left_threshold": lt,
                    "right_threshold": rt,
                    "left_selected_count": int(lc),
                    "left_realized_rate": lc / total if total else 0.0,
                    "right_selected_count": int(rc),
                    "right_realized_rate": rc / total if total else 0.0,
                    "intersection_count": int(inter),
                    "union_count": int(union),
                    "jaccard": inter / union if union else 1.0,
                    "left_containment": inter / lc if lc else 0.0,
                    "right_containment": inter / rc if rc else 0.0,
                }
            )
    return rows


def _conditional(connection: Any, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    levels = list(config["conditional_profile"]["a2_levels"])
    level_values = ",".join(f"({value})" for value in levels)
    fields = CSV_FIELDS["conditional_profile"]
    return _rows(
        connection,
        f"""
      WITH levels(a2_level) AS (VALUES {level_values}), p AS (SELECT a2,a2b FROM a03_common)
      SELECT l.a2_level,COUNT(p.a2b),COUNT(p.a2b)::DOUBLE/(SELECT COUNT(*) FROM a03_common),MIN(p.a2b),QUANTILE_CONT(p.a2b,.05),QUANTILE_CONT(p.a2b,.25),QUANTILE_CONT(p.a2b,.5),QUANTILE_CONT(p.a2b,.75),QUANTILE_CONT(p.a2b,.95),MAX(p.a2b),AVG(p.a2b),STDDEV_POP(p.a2b),COUNT(DISTINCT p.a2b)
      FROM levels l LEFT JOIN p ON p.a2=l.a2_level GROUP BY l.a2_level ORDER BY l.a2_level
    """,
        fields,
    )


def _variance(connection: Any) -> dict[str, Any]:
    row = connection.execute("""
      WITH g AS (SELECT a2,AVG(a2b) gm,COUNT(*) n FROM a03_common GROUP BY a2), s AS (SELECT AVG(a2b) global_mean FROM a03_common), totals AS (SELECT s.global_mean,SUM(POW(c.a2b-s.global_mean,2)) total_ss FROM a03_common c CROSS JOIN s GROUP BY s.global_mean), b AS (SELECT totals.global_mean,totals.total_ss,SUM(g.n*POW(g.gm-totals.global_mean,2)) between_group_ss FROM g CROSS JOIN totals GROUP BY totals.global_mean,totals.total_ss), w AS (SELECT SUM(POW(c.a2b-g.gm,2)) within_group_ss FROM a03_common c JOIN g USING(a2))
      SELECT b.global_mean,b.total_ss,b.between_group_ss,w.within_group_ss,b.between_group_ss/NULLIF(b.total_ss,0),w.within_group_ss/NULLIF(b.total_ss,0),b.total_ss-b.between_group_ss-w.within_group_ss FROM b CROSS JOIN w
    """).fetchone()
    fields = CSV_FIELDS["variance_decomposition"]
    return dict(zip(fields, row, strict=True))


def _stability(
    connection: Any,
    overall: list[dict[str, Any]],
    years: list[dict[str, Any]],
    securities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_stability_pairs (pair_id VARCHAR, overall_pearson DOUBLE, overall_spearman DOUBLE, security_total_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO a03_stability_pairs VALUES (?,?,?,?)",
        [
            (
                row["pair_id"],
                row["pearson_raw"],
                row["spearman_midrank"],
                sum(1 for item in securities if item["pair_id"] == row["pair_id"]),
            )
            for row in overall
        ],
    )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_year_stability (pair_id VARCHAR, spearman_midrank DOUBLE)"
    )
    year_values = [
        (row["pair_id"], row["spearman_midrank"])
        for row in years
        if row["common_count"] > 0 and row["spearman_midrank"] is not None
    ]
    if year_values:
        connection.executemany(
            "INSERT INTO a03_year_stability VALUES (?,?)", year_values
        )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE a03_security_stability (pair_id VARCHAR, spearman_midrank DOUBLE)"
    )
    security_values = [
        (row["pair_id"], row["spearman_midrank"])
        for row in securities
        if row["eligible"] and row["spearman_midrank"] is not None
    ]
    if security_values:
        connection.executemany(
            "INSERT INTO a03_security_stability VALUES (?,?)", security_values
        )
    fields = CSV_FIELDS["stability_summary"]
    rows = connection.execute("""
      WITH y AS (
        SELECT pair_id,COUNT(*) year_count,MIN(spearman_midrank) year_spearman_min,
          QUANTILE_CONT(spearman_midrank,.25) year_spearman_q25,
          QUANTILE_CONT(spearman_midrank,.5) year_spearman_median,
          QUANTILE_CONT(spearman_midrank,.75) year_spearman_q75,
          MAX(spearman_midrank) year_spearman_max,
          SUM(CASE WHEN spearman_midrank<0 THEN 1 ELSE 0 END) year_negative_count
        FROM a03_year_stability GROUP BY pair_id
      ), s AS (
        SELECT pair_id,COUNT(*) security_eligible_count,
          QUANTILE_CONT(spearman_midrank,.1) security_spearman_q10,
          QUANTILE_CONT(spearman_midrank,.25) security_spearman_q25,
          QUANTILE_CONT(spearman_midrank,.5) security_spearman_median,
          QUANTILE_CONT(spearman_midrank,.75) security_spearman_q75,
          QUANTILE_CONT(spearman_midrank,.9) security_spearman_q90,
          SUM(CASE WHEN spearman_midrank<0 THEN 1 ELSE 0 END) security_negative_count
        FROM a03_security_stability GROUP BY pair_id
      )
      SELECT p.pair_id,p.overall_pearson,p.overall_spearman,
        COALESCE(y.year_count,0),y.year_spearman_min,y.year_spearman_q25,y.year_spearman_median,y.year_spearman_q75,y.year_spearman_max,COALESCE(y.year_negative_count,0),
        p.security_total_count,COALESCE(s.security_eligible_count,0),p.security_total_count-COALESCE(s.security_eligible_count,0),
        s.security_spearman_q10,s.security_spearman_q25,s.security_spearman_median,s.security_spearman_q75,s.security_spearman_q90,COALESCE(s.security_negative_count,0)
      FROM a03_stability_pairs p LEFT JOIN y USING(pair_id) LEFT JOIN s USING(pair_id) ORDER BY p.pair_id
    """).fetchall()
    return [dict(zip(fields, row, strict=True)) for row in rows]


def _criterion(actual: Any, threshold: Any, passed: bool) -> dict[str, Any]:
    return {"actual": actual, "threshold": threshold, "passed": bool(passed)}


def _disposition(
    connection: Any,
    config: Mapping[str, Any],
    overall: list[dict[str, Any]],
    years: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    tails: list[dict[str, Any]],
    conditional: list[dict[str, Any]],
    variance: dict[str, Any],
) -> dict[str, Any]:
    gate_config = config["redundancy_gate"]
    adequacy_config = config["representation_adequacy"]
    stability = {
        row["pair_id"]: row
        for row in _stability(connection, overall, years, securities)
    }
    a2a2b = stability["A2_A2b"]
    tail = {(row["pair_id"], row["tail_fraction"]): row for row in tails}
    gate_values = {
        "overall_spearman": _criterion(
            a2a2b["overall_spearman"],
            gate_config["overall_spearman_min"],
            a2a2b["overall_spearman"] is not None
            and a2a2b["overall_spearman"] >= gate_config["overall_spearman_min"],
        ),
        "minimum_year_spearman": _criterion(
            a2a2b["year_spearman_min"],
            gate_config["minimum_year_spearman_min"],
            a2a2b["year_spearman_min"] is not None
            and a2a2b["year_spearman_min"] >= gate_config["minimum_year_spearman_min"],
        ),
        "eligible_security_spearman_q10": _criterion(
            a2a2b["security_spearman_q10"],
            gate_config["eligible_security_spearman_q10_min"],
            a2a2b["security_spearman_q10"] is not None
            and a2a2b["security_spearman_q10"]
            >= gate_config["eligible_security_spearman_q10_min"],
        ),
        "tail_jaccard_005": _criterion(
            tail[("A2_A2b", 0.05)]["jaccard"],
            gate_config["tail_jaccard_005_min"],
            tail[("A2_A2b", 0.05)]["jaccard"] >= gate_config["tail_jaccard_005_min"],
        ),
        "tail_jaccard_010": _criterion(
            tail[("A2_A2b", 0.1)]["jaccard"],
            gate_config["tail_jaccard_010_min"],
            tail[("A2_A2b", 0.1)]["jaccard"] >= gate_config["tail_jaccard_010_min"],
        ),
        "eta_squared": _criterion(
            variance["eta_squared"],
            gate_config["eta_squared_min"],
            variance["eta_squared"] is not None
            and variance["eta_squared"] >= gate_config["eta_squared_min"],
        ),
    }
    gate_values["all_passed"] = all(item["passed"] for item in gate_values.values())
    a2 = connection.execute(
        f"SELECT COUNT(*) FILTER(WHERE ABS(a2*20-ROUND(a2*20))>{A2_GRID_TOLERANCE}),COUNT(DISTINCT a2) FROM a03_common"
    ).fetchone()
    max_level_share = connection.execute(
        "SELECT MAX(n)::DOUBLE/(SELECT COUNT(*) FROM a03_common) FROM (SELECT a2,COUNT(*) n FROM a03_common GROUP BY a2)"
    ).fetchone()[0]
    a2_tail_005 = tail[("A2_A2b", 0.05)]["left_realized_rate"]
    a2_tail_010 = tail[("A2_A2b", 0.1)]["left_realized_rate"]
    adequacy = {
        "grid_violation_count": _criterion(
            a2[0],
            adequacy_config["a2_grid_violation_max"],
            a2[0] <= adequacy_config["a2_grid_violation_max"],
        ),
        "unique_grid_level_count": _criterion(
            a2[1],
            adequacy_config["a2_unique_level_count"],
            a2[1] == adequacy_config["a2_unique_level_count"],
        ),
        "maximum_level_share": _criterion(
            max_level_share,
            adequacy_config["a2_max_level_share"],
            max_level_share <= adequacy_config["a2_max_level_share"],
        ),
        "tail_realized_rate_005": _criterion(
            a2_tail_005,
            adequacy_config["a2_tail_realized_rate_005_max"],
            a2_tail_005 <= adequacy_config["a2_tail_realized_rate_005_max"],
        ),
        "tail_realized_rate_010": _criterion(
            a2_tail_010,
            adequacy_config["a2_tail_realized_rate_010_max"],
            a2_tail_010 <= adequacy_config["a2_tail_realized_rate_010_max"],
        ),
    }
    adequacy["all_passed"] = all(item["passed"] for item in adequacy.values())
    collisions: dict[str, bool] = {}
    for pair_id in ("A1_A2", "A1_A2b"):
        s = stability[pair_id]
        collisions[pair_id] = bool(
            s["overall_spearman"] is not None
            and s["overall_spearman"] >= 0.95
            and s["year_spearman_min"] is not None
            and s["year_spearman_min"] >= 0.9
            and tail[(pair_id, 0.05)]["jaccard"] >= 0.8
            and tail[(pair_id, 0.1)]["jaccard"] >= 0.8
        )
    if gate_values["all_passed"] and adequacy["all_passed"]:
        candidates, reason = (
            ["A1", "A2"],
            "redundant_and_A2_preferred_for_topological_interpretability",
        )
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "selected_persistence_representative",
            "A2b": "retain_as_redundant_backup_not_carried_to_A04",
        }
    elif gate_values["all_passed"]:
        candidates, reason = ["A1", "A2b"], "redundant_but_A2_representation_inadequate"
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "retain_as_coarse_backup_not_carried_to_A04",
            "A2b": "selected_persistence_representative",
        }
    else:
        candidates, reason = ["A1", "A2", "A2b"], "material_internal_difference"
        dispositions = {
            "A1": "instantaneous_distance_anchor",
            "A2": "retain_for_A04",
            "A2b": "retain_for_A04",
        }
    return {
        "task_id": TASK_ID,
        "run_id": None,
        "decision_version": "EXP-A03-v1",
        "candidate_ids": ["A1", "A2", "A2b"],
        "common_valid_count": int(overall[0]["common_count"]),
        "thresholds": {
            "A2_A2b_redundancy_gate": gate_values,
            "A2_representation_adequacy": adequacy,
        },
        "A2_A2b_redundancy_gate": gate_values,
        "A2_representation_adequacy": adequacy,
        "A1_collision_flags": collisions,
        "recommended_candidate_set_for_A04": candidates,
        "candidate_dispositions": dispositions,
        "decision_reason": reason,
        "decision_status": "provisional_A03_recommendation",
        "A_layer_registered": False,
        "PCATV_created": False,
        "EXP_A04_started": False,
    }


def build_analysis(
    connection: Any, config: Mapping[str, Any], *, raw_table: str = RAW_TABLE
) -> dict[str, Any]:
    """Materialize compact analysis tables using only set-based SQL."""
    table = _quote(raw_table)
    _make_common(connection, raw_table)
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE a03_security_ids AS SELECT DISTINCT security_id FROM {table}"
    )
    overall, years, securities = _pairwise(connection, config)
    tails = _tail_overlap(connection)
    conditional = _conditional(connection, config)
    variance = _variance(connection)
    stability = _stability(connection, overall, years, securities)
    disposition = _disposition(
        connection, config, overall, years, securities, tails, conditional, variance
    )
    return {
        "pairwise_overall": overall,
        "pairwise_year": years,
        "pairwise_security": securities,
        "tail_overlap": tails,
        "conditional_profile": conditional,
        "variance_decomposition": [variance],
        "stability_summary": stability,
        "candidate_disposition": disposition,
    }


def write_outputs(output_root: Path, analysis: Mapping[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for name, fields in CSV_FIELDS.items():
        with (output_root / OUTPUT_FILES[name]).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            for row in analysis[name]:
                writer.writerow({field: _finite(row.get(field)) for field in fields})
    (output_root / OUTPUT_FILES["candidate_disposition"]).write_text(
        json.dumps(
            analysis["candidate_disposition"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_result_analysis(
    run_id: str,
    reviewed_sha: str,
    analysis: Mapping[str, Any],
    *,
    synthetic_fixture: bool,
) -> str:
    disposition = analysis["candidate_disposition"]
    lines = ["# EXP-A03 candidate intralayer redundancy and selection"]
    for heading in ANALYSIS_HEADINGS:
        lines.append(heading)
        if heading == ANALYSIS_HEADINGS[0]:
            lines.extend(
                [
                    f"run_id: {run_id}",
                    f"reviewed_implementation_sha: {reviewed_sha}",
                    f"execution_mode: {'synthetic_fixture_only' if synthetic_fixture else 'formal_run'}",
                    "formal_data_version: false",
                ]
            )
        elif heading == ANALYSIS_HEADINGS[3]:
            lines.append(
                "The universe is exactly the accepted A01 rows with all three indicators valid and the accepted A02 common-valid count."
            )
        elif heading == ANALYSIS_HEADINGS[14]:
            lines.append(
                f"recommended_candidate_set_for_A04: {json.dumps(disposition['recommended_candidate_set_for_A04'])}"
            )
        elif heading == ANALYSIS_HEADINGS[-1]:
            lines.append(
                "needs_investigation_before_user_review"
                if synthetic_fixture
                else "ready_for_user_formal_result_review"
            )
        else:
            lines.append("See the corresponding compact artifact.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_anomaly_scan(
    analysis: Mapping[str, Any],
    validator_result: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    synthetic_fixture: bool,
) -> dict[str, Any]:
    blocking = list(validator_result.get("errors", []))
    investigations: list[str] = []
    for pair in analysis["stability_summary"]:
        if pair["year_negative_count"]:
            investigations.append(f"negative_year_spearman:{pair['pair_id']}")
        if pair["security_negative_count"]:
            investigations.append(f"negative_security_spearman:{pair['pair_id']}")
        if pair["security_eligible_count"] < 720:
            investigations.append(
                f"eligible_security_count_below_720:{pair['pair_id']}"
            )
        if (
            pair["year_spearman_min"] is not None
            and pair["year_spearman_max"] is not None
            and pair["year_spearman_max"] - pair["year_spearman_min"] > 0.20
        ):
            investigations.append(f"year_spearman_range_high:{pair['pair_id']}")
        if (
            pair["security_spearman_q10"] is not None
            and pair["security_spearman_q90"] is not None
            and pair["security_spearman_q90"] - pair["security_spearman_q10"] > 0.30
        ):
            investigations.append(f"security_spearman_range_high:{pair['pair_id']}")
    gate = analysis["candidate_disposition"]["A2_A2b_redundancy_gate"]
    for criterion, item in gate.items():
        if (
            criterion != "all_passed"
            and item["actual"] is not None
            and abs(item["actual"] - item["threshold"]) <= 0.02
        ):
            investigations.append(f"gate_near_threshold:{criterion}")
    tails = {
        (row["pair_id"], row["tail_fraction"]): row for row in analysis["tail_overlap"]
    }
    adequacy_config = config["representation_adequacy"]
    for fraction, threshold_key, label in (
        (0.05, "a2_tail_realized_rate_005_max", "005"),
        (0.1, "a2_tail_realized_rate_010_max", "010"),
    ):
        rate = tails[("A2_A2b", fraction)]["left_realized_rate"]
        if rate > adequacy_config[threshold_key]:
            investigations.append(f"a2_tail_realized_rate_high:{label}")
    for pair_id, flag in analysis["candidate_disposition"][
        "A1_collision_flags"
    ].items():
        if flag:
            investigations.append(f"a1_collision:{pair_id}")
    return {
        "task_id": TASK_ID,
        "status": "failed"
        if blocking
        else "passed_with_investigation_items"
        if investigations
        else "passed",
        "blocking_anomalies": blocking,
        "blocking_anomaly_count": len(blocking),
        "investigation_items": investigations,
        "investigation_item_count": len(investigations),
        "synthetic_fixture": synthetic_fixture,
    }
