# ruff: noqa: E501

"""Set-based EXP-A04 cross-layer diagnostics.

The producer keeps the two accepted raw databases read-only.  Only compact
aggregates are materialized in Python; joined observation rows remain in
DuckDB temporary relations and are never exported.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A04"
A_IDS = (
    "A1_LogBodyCenterToMACloudCenter_5_60",
    "A2_BodyCenterOutsideMACloudRate20_5_60",
    "A2b_BodyToMACloudGapMean20_5_60",
)
A_SHORT_IDS = {A_IDS[0]: "A1", A_IDS[1]: "A2", A_IDS[2]: "A2b"}
A_RAW_NAMES = {
    A_IDS[0]: "LogBodyCenterToMACloudCenter_5_60",
    A_IDS[1]: "BodyCenterOutsideMACloudRate20_5_60",
    A_IDS[2]: "BodyToMACloudGapMean20_5_60",
}
LAYERS = ("P", "C", "T", "V")
TAILS = (0.01, 0.05, 0.1)
YEARS = tuple(range(2016, 2027))
OUTPUT_FILES = (
    "exp_a04_indicator_registry.csv",
    "exp_a04_pairwise_coverage.csv",
    "exp_a04_pairwise_overall.csv",
    "exp_a04_pairwise_year.csv",
    "exp_a04_pairwise_security.csv",
    "exp_a04_tail_overlap.csv",
    "exp_a04_layer_summary.csv",
    "exp_a04_candidate_summary.csv",
    "exp_a04_cross_layer_disposition.json",
    "exp_a04_manifest.json",
    "exp_a04_validator_result.json",
    "exp_a04_anomaly_scan.json",
    "exp_a04_result_analysis.md",
)
CSV_FIELDS = {
    "indicator_registry": (
        "registry_role",
        "indicator_id",
        "layer",
        "raw_metric_name",
        "raw_source_indicator_id",
        "raw_value_direction",
    ),
    "pairwise_coverage": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "a_valid_count",
        "pcvt_valid_count",
        "common_count",
        "common_rate_of_a",
        "common_rate_of_pcvt",
        "common_rate_of_smaller_side",
        "join_key_policy",
        "one_to_one_key_proven",
    ),
    "pairwise_overall": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "a_tied_row_count",
        "pcvt_tied_row_count",
    ),
    "pairwise_year": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "calendar_year",
        "common_count",
        "pearson_raw",
        "spearman_midrank",
        "undefined_reason",
    ),
    "pairwise_security": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "security_id",
        "common_count",
        "eligible",
        "pearson_raw",
        "spearman_midrank",
        "reason",
    ),
    "tail_overlap": (
        "pair_id",
        "a_candidate_id",
        "pcvt_indicator_id",
        "pcvt_layer",
        "tail_fraction",
        "a_threshold",
        "pcvt_threshold",
        "a_selected_count",
        "a_realized_rate",
        "pcvt_selected_count",
        "pcvt_realized_rate",
        "intersection_count",
        "union_count",
        "jaccard",
        "a_containment",
        "pcvt_containment",
    ),
    "layer_summary": (
        "a_candidate_id",
        "pcvt_layer",
        "indicator_pair_count",
        "valid_pair_count",
        "nearest_indicator_by_spearman",
        "max_overall_spearman",
        "nearest_indicator_by_tail_jaccard_005",
        "max_tail_jaccard_005",
        "nearest_indicator_by_tail_jaccard_010",
        "max_tail_jaccard_010",
        "hard_collision_count",
        "hard_collision_indicator_ids_json",
    ),
    "candidate_summary": (
        "a_candidate_id",
        "nearest_layer",
        "nearest_indicator",
        "max_overall_spearman",
        "max_tail_jaccard_005",
        "max_tail_jaccard_010",
        "hard_collision_count",
        "hard_collision_pairs_json",
        "eligible_pair_count",
        "low_coverage_pair_count",
        "provisional_status_for_A05",
    ),
}
ANALYSIS_HEADINGS = [
    "## 1. Actual run / reviewed SHA",
    "## 2. Accepted EXP-A03 handoff",
    "## 3. Accepted PCVT raw handoff",
    "## 4. Input artifacts and lineage",
    "## 5. Frozen indicator registry",
    "## 6. Pairwise common-universe coverage",
    "## 7. Overall cross-layer relationships",
    "## 8. Year stability",
    "## 9. Security stability",
    "## 10. Low-tail identity overlap",
    "## 11. Hard collision gate results",
    "## 12. Layer summaries",
    "## 13. Candidate summaries",
    "## 14. Provisional A05 carry-forward status",
    "## 15. Full invariant validation",
    "## 16. Independent aggregate recomputation",
    "## 17. Anomaly scan",
    "## 18. Supported conclusions",
    "## 19. Unsupported conclusions",
    "## 20. Readiness for Formal-result review",
]


class LineageError(RuntimeError):
    """Raised when an accepted input contract cannot be proven."""


def _sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _date_expr(column: str) -> str:
    value = f"CAST({column} AS VARCHAR)"
    return (
        f"COALESCE(try_strptime({value}, '%Y-%m-%d')::DATE, "
        f"try_strptime({value}, '%Y%m%d')::DATE)"
    )


def _finite(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quantile_cont(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def _rows(connection: Any, query: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        dict(zip(fields, row, strict=True))
        for row in connection.execute(query).fetchall()
    ]


def pcvt_registry(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    registry = list(config["pcvt_indicator_registry"])
    if len(registry) != 8 or {row["layer"] for row in registry} != set(LAYERS):
        raise LineageError("pcvt_registry_shape_mismatch")
    if any(
        row["raw_value_direction"] != "lower_is_more_convergent" for row in registry
    ):
        raise LineageError("pcvt_direction_mismatch")
    if any(sum(row["layer"] == layer for row in registry) != 2 for layer in LAYERS):
        raise LineageError("pcvt_layer_balance_mismatch")
    return registry


def pair_registry(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = list(config["candidate_universe"]["candidate_ids"])
    if candidates != list(A_IDS):
        raise LineageError("a_candidate_registry_mismatch")
    registry = pcvt_registry(config)
    pairs: list[dict[str, Any]] = []
    for candidate in candidates:
        for pcvt in registry:
            pairs.append(
                {
                    "pair_id": f"{A_SHORT_IDS[candidate]}__{pcvt['indicator_id']}",
                    "a_candidate_id": candidate,
                    "pcvt_indicator_id": pcvt["indicator_id"],
                    "pcvt_layer": pcvt["layer"],
                    "a_direction": "lower_raw_is_more_convergent",
                    "pcvt_direction": "lower_raw_is_more_convergent",
                }
            )
    if len(pairs) != 24 or len({row["pair_id"] for row in pairs}) != 24:
        raise LineageError("pair_registry_mismatch")
    return pairs


def _table_columns(connection: Any, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({_sql(table)})").fetchall()
    if not rows:
        raise LineageError(f"missing_table:{table}")
    return {str(row[1]) for row in rows}


def _build_source_views(
    connection: Any,
    *,
    a_table: str,
    pcvt_schema: str,
    pcvt_table: str,
    registry: list[dict[str, Any]],
) -> None:
    a_columns = _table_columns(connection, a_table)
    required_a = {
        "security_id",
        "trading_date",
        "observation_sequence",
        "indicator_id",
        "raw_value",
        "validity_status",
    }
    if not required_a <= a_columns:
        raise LineageError(f"a_schema_mismatch:{sorted(required_a - a_columns)}")
    pcvt_relation = f"{_quote(pcvt_schema)}.{_quote(pcvt_table)}"
    pcvt_columns = _table_columns(connection, f"{pcvt_schema}.{pcvt_table}")
    required_pcvt = {
        "security_id",
        "trading_date",
        "indicator_id",
        "raw_value",
        "validity_status",
    }
    if not required_pcvt <= pcvt_columns:
        raise LineageError(
            f"pcvt_schema_mismatch:{sorted(required_pcvt - pcvt_columns)}"
        )
    pcvt_eligibility = ""
    for name in ("eligible", "eligibility"):
        if name in pcvt_columns:
            pcvt_eligibility = f" AND COALESCE(CAST({name} AS BOOLEAN), FALSE)"
            break
    a_ids = ",".join(_sql(value) for value in A_IDS)
    pcvt_ids = ",".join(_sql(row["indicator_id"]) for row in registry)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE a04_a_valid AS
        SELECT CAST(security_id AS VARCHAR) AS security_id,
               {_date_expr("trading_date")} AS trading_date,
               CAST(observation_sequence AS BIGINT) AS observation_sequence,
               CAST(indicator_id AS VARCHAR) AS indicator_id,
               TRY_CAST(raw_value AS DOUBLE) AS raw_value
        FROM {_quote(a_table)}
        WHERE indicator_id IN ({a_ids})
          AND validity_status = 'valid'
          AND {_date_expr("trading_date")} IS NOT NULL
          AND TRY_CAST(raw_value AS DOUBLE) IS NOT NULL
          AND isfinite(TRY_CAST(raw_value AS DOUBLE))
        """
    )
    invalid_a = connection.execute(
        f"SELECT COUNT(*) FROM {_quote(a_table)} WHERE indicator_id IN ({a_ids}) AND {_date_expr('trading_date')} IS NULL"
    ).fetchone()[0]
    if invalid_a:
        raise LineageError(f"invalid_a_date:{invalid_a}")
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE a04_pcvt_valid AS
        SELECT CAST(security_id AS VARCHAR) AS security_id,
               {_date_expr("trading_date")} AS trading_date,
               CAST(indicator_id AS VARCHAR) AS indicator_id,
               TRY_CAST(raw_value AS DOUBLE) AS raw_value
        FROM {pcvt_relation}
        WHERE indicator_id IN ({pcvt_ids})
          AND validity_status = 'valid'
          {pcvt_eligibility}
          AND {_date_expr("trading_date")} IS NOT NULL
          AND TRY_CAST(raw_value AS DOUBLE) IS NOT NULL
          AND isfinite(TRY_CAST(raw_value AS DOUBLE))
        """
    )
    invalid_pcvt = connection.execute(
        f"SELECT COUNT(*) FROM {pcvt_relation} WHERE indicator_id IN ({pcvt_ids}) AND {_date_expr('trading_date')} IS NULL"
    ).fetchone()[0]
    if invalid_pcvt:
        raise LineageError(f"invalid_pcvt_date:{invalid_pcvt}")
    a_dupes = connection.execute(
        """SELECT COUNT(*) FROM (SELECT indicator_id,security_id,trading_date,COUNT(*) n FROM a04_a_valid GROUP BY ALL HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    pcvt_dupes = connection.execute(
        """SELECT COUNT(*) FROM (SELECT indicator_id,security_id,trading_date,COUNT(*) n FROM a04_pcvt_valid GROUP BY ALL HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    if a_dupes:
        raise LineageError(f"duplicate_a_security_date_key:{a_dupes}")
    if pcvt_dupes:
        raise LineageError(f"duplicate_pcvt_security_date_key:{pcvt_dupes}")


def _make_pair_rows(connection: Any, pairs: list[dict[str, Any]]) -> None:
    connection.execute("DROP TABLE IF EXISTS a04_pair_registry")
    connection.execute(
        "CREATE TEMP TABLE a04_pair_registry(pair_id VARCHAR,a_candidate_id VARCHAR,pcvt_indicator_id VARCHAR,pcvt_layer VARCHAR,a_direction VARCHAR,pcvt_direction VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO a04_pair_registry VALUES (?,?,?,?,?,?)",
        [
            (
                row["pair_id"],
                row["a_candidate_id"],
                row["pcvt_indicator_id"],
                row["pcvt_layer"],
                row["a_direction"],
                row["pcvt_direction"],
            )
            for row in pairs
        ],
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE a04_pair_rows AS
        SELECT r.pair_id,r.a_candidate_id,r.pcvt_indicator_id,r.pcvt_layer,
               a.security_id,a.trading_date,YEAR(a.trading_date) calendar_year,
               a.raw_value a_raw,p.raw_value pcvt_raw
        FROM a04_pair_registry r
        JOIN a04_a_valid a ON a.indicator_id=r.a_candidate_id
        JOIN a04_pcvt_valid p ON p.indicator_id=r.pcvt_indicator_id
          AND p.security_id=a.security_id AND p.trading_date=a.trading_date
        """
    )


def _ranked(connection: Any, partition: str, name: str) -> None:
    partition_expr = f"PARTITION BY pair_id{',' + partition if partition else ''}"
    value_a = f"PARTITION BY pair_id{',' + partition if partition else ''},a_raw"
    value_p = f"PARTITION BY pair_id{',' + partition if partition else ''},pcvt_raw"
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {name} AS
        SELECT *,
          RANK() OVER({partition_expr} ORDER BY a_raw)
            + (COUNT(*) OVER({value_a})-1)/2.0 AS a_midrank,
          RANK() OVER({partition_expr} ORDER BY pcvt_raw)
            + (COUNT(*) OVER({value_p})-1)/2.0 AS pcvt_midrank
        FROM a04_pair_rows
        """
    )


def _pairwise_coverage(
    connection: Any, pairs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    fields = CSV_FIELDS["pairwise_coverage"]
    rows = _rows(
        connection,
        """
        WITH a AS (SELECT indicator_id,COUNT(*) n FROM a04_a_valid GROUP BY indicator_id),
             p AS (SELECT indicator_id,COUNT(*) n FROM a04_pcvt_valid GROUP BY indicator_id),
             c AS (SELECT pair_id,COUNT(*) n FROM a04_pair_rows GROUP BY pair_id)
        SELECT r.pair_id,r.a_candidate_id,r.pcvt_indicator_id,r.pcvt_layer,
          COALESCE(a.n,0),COALESCE(p.n,0),COALESCE(c.n,0),
          COALESCE(c.n,0)::DOUBLE/NULLIF(a.n,0),
          COALESCE(c.n,0)::DOUBLE/NULLIF(p.n,0),
          COALESCE(c.n,0)::DOUBLE/NULLIF(LEAST(a.n,p.n),0),
          'security_id+trading_date_after_strict_uniqueness_proof',TRUE
        FROM a04_pair_registry r
        LEFT JOIN a ON a.indicator_id=r.a_candidate_id
        LEFT JOIN p ON p.indicator_id=r.pcvt_indicator_id
        LEFT JOIN c ON c.pair_id=r.pair_id
        ORDER BY r.pair_id
        """,
        fields,
    )
    return rows


def _pairwise_overall(connection: Any) -> list[dict[str, Any]]:
    _ranked(connection, "", "a04_rank_overall")
    fields = CSV_FIELDS["pairwise_overall"]
    rows = _rows(
        connection,
        """
        WITH ties AS (
          SELECT pair_id,
            COALESCE(SUM(a_n) FILTER(WHERE a_n > 1),0) a_tied,
            COALESCE(SUM(p_n) FILTER(WHERE p_n > 1),0) p_tied
          FROM (
            SELECT pair_id,a_raw,COUNT(*) a_n,0 p_n FROM a04_pair_rows GROUP BY pair_id,a_raw
            UNION ALL
            SELECT pair_id,pcvt_raw,0,COUNT(*) FROM a04_pair_rows GROUP BY pair_id,pcvt_raw
          ) GROUP BY pair_id
        ), agg AS (
          SELECT pair_id,COUNT(*) common_count,CORR(a_raw,pcvt_raw) pearson_raw,
                 CORR(a_midrank,pcvt_midrank) spearman_midrank
          FROM a04_rank_overall GROUP BY pair_id
        )
        SELECT r.pair_id,r.a_candidate_id,r.pcvt_indicator_id,r.pcvt_layer,
               COALESCE(agg.common_count,0),agg.pearson_raw,agg.spearman_midrank,
               COALESCE(t.a_tied,0),COALESCE(t.p_tied,0)
        FROM a04_pair_registry r LEFT JOIN agg USING(pair_id) LEFT JOIN ties t USING(pair_id)
        ORDER BY r.pair_id
        """,
        fields,
    )
    return rows


def _pairwise_year(connection: Any) -> list[dict[str, Any]]:
    _ranked(connection, "calendar_year", "a04_rank_year")
    fields = CSV_FIELDS["pairwise_year"]
    rows = _rows(
        connection,
        """
        WITH years(calendar_year) AS (SELECT * FROM range(2016,2027)),
        agg AS (
          SELECT pair_id,calendar_year,COUNT(*) common_count,CORR(a_raw,pcvt_raw) pearson_raw,
                 CORR(a_midrank,pcvt_midrank) spearman_midrank
          FROM a04_rank_year GROUP BY pair_id,calendar_year
        )
        SELECT r.pair_id,r.a_candidate_id,r.pcvt_indicator_id,r.pcvt_layer,y.calendar_year,
          COALESCE(a.common_count,0),a.pearson_raw,a.spearman_midrank,
          CASE WHEN COALESCE(a.common_count,0)>0 AND (a.spearman_midrank IS NULL OR NOT isfinite(a.spearman_midrank)) THEN 'undefined_correlation' ELSE NULL END
        FROM a04_pair_registry r CROSS JOIN years y LEFT JOIN agg a USING(pair_id,calendar_year)
        ORDER BY r.pair_id,y.calendar_year
        """,
        fields,
    )
    return rows


def _pairwise_security(connection: Any) -> list[dict[str, Any]]:
    _ranked(connection, "security_id", "a04_rank_security")
    fields = CSV_FIELDS["pairwise_security"]
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE a04_security_ids AS SELECT security_id FROM a04_a_valid GROUP BY security_id UNION SELECT security_id FROM a04_pcvt_valid GROUP BY security_id"""
    )
    rows = _rows(
        connection,
        """
        WITH agg AS (
          SELECT pair_id,security_id,COUNT(*) common_count,CORR(a_raw,pcvt_raw) pearson_raw,
                 CORR(a_midrank,pcvt_midrank) spearman_midrank
          FROM a04_rank_security GROUP BY pair_id,security_id
        )
        SELECT r.pair_id,r.a_candidate_id,r.pcvt_indicator_id,r.pcvt_layer,s.security_id,
          COALESCE(a.common_count,0),
          CASE WHEN COALESCE(a.common_count,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL
                    AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN TRUE ELSE FALSE END,
          CASE WHEN COALESCE(a.common_count,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL
                    AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN a.pearson_raw ELSE NULL END,
          CASE WHEN COALESCE(a.common_count,0)>=100 AND a.pearson_raw IS NOT NULL AND a.spearman_midrank IS NOT NULL
                    AND isfinite(a.pearson_raw) AND isfinite(a.spearman_midrank) THEN a.spearman_midrank ELSE NULL END,
          CASE WHEN COALESCE(a.common_count,0)<100 THEN 'insufficient_common_rows'
               WHEN a.pearson_raw IS NULL OR a.spearman_midrank IS NULL OR NOT isfinite(a.pearson_raw) OR NOT isfinite(a.spearman_midrank) THEN 'undefined_correlation_constant_input'
               ELSE NULL END
        FROM a04_pair_registry r CROSS JOIN a04_security_ids s LEFT JOIN agg a USING(pair_id,security_id)
        ORDER BY r.pair_id,s.security_id
        """,
        fields,
    )
    return rows


def _tail_overlap(connection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in connection.execute(
        "SELECT pair_id,a_candidate_id,pcvt_indicator_id,pcvt_layer FROM a04_pair_registry ORDER BY pair_id"
    ).fetchall():
        pair_id, a_id, p_id, layer = pair
        for fraction in TAILS:
            row = connection.execute(
                f"""
                WITH q AS (
                  SELECT QUANTILE_DISC(a_raw,{fraction}) a_threshold,QUANTILE_DISC(pcvt_raw,{fraction}) pcvt_threshold
                  FROM a04_pair_rows WHERE pair_id={_sql(pair_id)}
                ), flags AS (
                  SELECT a_raw <= q.a_threshold a_selected,pcvt_raw <= q.pcvt_threshold p_selected
                  FROM a04_pair_rows CROSS JOIN q WHERE pair_id={_sql(pair_id)}
                )
                SELECT (SELECT a_threshold FROM q),(SELECT pcvt_threshold FROM q),
                  COUNT(*) FILTER(WHERE a_selected),COUNT(*) FILTER(WHERE p_selected),
                  COUNT(*) FILTER(WHERE a_selected AND p_selected),COUNT(*) FILTER(WHERE a_selected OR p_selected),COUNT(*)
                FROM flags
                """
            ).fetchone()
            threshold_a, threshold_p, a_count, p_count, inter, union, total = row
            a_count = int(a_count or 0)
            p_count = int(p_count or 0)
            inter = int(inter or 0)
            union = int(union or 0)
            total = int(total or 0)
            rows.append(
                {
                    "pair_id": pair_id,
                    "a_candidate_id": a_id,
                    "pcvt_indicator_id": p_id,
                    "pcvt_layer": layer,
                    "tail_fraction": fraction,
                    "a_threshold": threshold_a,
                    "pcvt_threshold": threshold_p,
                    "a_selected_count": a_count,
                    "a_realized_rate": a_count / total if total else None,
                    "pcvt_selected_count": p_count,
                    "pcvt_realized_rate": p_count / total if total else None,
                    "intersection_count": inter,
                    "union_count": union,
                    "jaccard": inter / union if union else None,
                    "a_containment": inter / a_count if a_count else None,
                    "pcvt_containment": inter / p_count if p_count else None,
                }
            )
    return rows


def _criterion(actual: Any, threshold: float, passed: bool) -> dict[str, Any]:
    return {"actual": _finite(actual), "threshold": threshold, "passed": bool(passed)}


def _metric_key(
    row: Mapping[str, Any], metric: str, layer_order: Mapping[str, int]
) -> tuple[Any, ...]:
    value = _float_or_none(row.get(metric))
    return (
        value is not None,
        value if value is not None else float("-inf"),
        -layer_order[row["pcvt_layer"]],
        tuple(reversed(row["pcvt_indicator_id"])),
    )


def _best(
    rows: list[dict[str, Any]], metric: str, layer_order: Mapping[str, int]
) -> dict[str, Any] | None:
    valid = [row for row in rows if _float_or_none(row.get(metric)) is not None]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda row: (
            -round(float(row[metric]), 12),
            layer_order[row["pcvt_layer"]],
            row["pcvt_indicator_id"],
        ),
    )[0]


def _summaries(
    coverage: list[dict[str, Any]],
    overall: list[dict[str, Any]],
    tails: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    collisions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layer_order = {layer: index for index, layer in enumerate(LAYERS)}
    tail_map = {(row["pair_id"], float(row["tail_fraction"])): row for row in tails}
    overall_map = {row["pair_id"]: row for row in overall}
    coverage_map = {row["pair_id"]: row for row in coverage}
    security_by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in securities:
        security_by_pair.setdefault(row["pair_id"], []).append(row)
    layer_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for candidate in A_IDS:
        candidate_pairs = [row for row in overall if row["a_candidate_id"] == candidate]
        for layer in LAYERS:
            layer_pairs = [row for row in candidate_pairs if row["pcvt_layer"] == layer]
            best_s = _best(layer_pairs, "spearman_midrank", layer_order)
            tail5 = [
                {**row, "tail_metric": tail_map[(row["pair_id"], 0.05)]["jaccard"]}
                for row in layer_pairs
            ]
            tail10 = [
                {**row, "tail_metric": tail_map[(row["pair_id"], 0.1)]["jaccard"]}
                for row in layer_pairs
            ]
            best5 = _best(tail5, "tail_metric", layer_order)
            best10 = _best(tail10, "tail_metric", layer_order)
            collision_ids = sorted(
                row["pcvt_indicator_id"]
                for row in layer_pairs
                if collisions[row["pair_id"]]["hard_cross_layer_collision"]
            )
            layer_rows.append(
                {
                    "a_candidate_id": candidate,
                    "pcvt_layer": layer,
                    "indicator_pair_count": len(layer_pairs),
                    "valid_pair_count": sum(
                        overall_map[row["pair_id"]]["common_count"] > 0
                        for row in layer_pairs
                    ),
                    "nearest_indicator_by_spearman": best_s["pcvt_indicator_id"]
                    if best_s
                    else None,
                    "max_overall_spearman": best_s["spearman_midrank"]
                    if best_s
                    else None,
                    "nearest_indicator_by_tail_jaccard_005": best5["pcvt_indicator_id"]
                    if best5
                    else None,
                    "max_tail_jaccard_005": best5["tail_metric"] if best5 else None,
                    "nearest_indicator_by_tail_jaccard_010": best10["pcvt_indicator_id"]
                    if best10
                    else None,
                    "max_tail_jaccard_010": best10["tail_metric"] if best10 else None,
                    "hard_collision_count": len(collision_ids),
                    "hard_collision_indicator_ids_json": json.dumps(
                        collision_ids, separators=(",", ":")
                    ),
                }
            )
        best_s = _best(candidate_pairs, "spearman_midrank", layer_order)
        all_tail5 = [
            {**row, "tail_metric": tail_map[(row["pair_id"], 0.05)]["jaccard"]}
            for row in candidate_pairs
        ]
        all_tail10 = [
            {**row, "tail_metric": tail_map[(row["pair_id"], 0.1)]["jaccard"]}
            for row in candidate_pairs
        ]
        best5 = _best(all_tail5, "tail_metric", layer_order)
        best10 = _best(all_tail10, "tail_metric", layer_order)
        hard_pairs = sorted(
            row["pair_id"]
            for row in candidate_pairs
            if collisions[row["pair_id"]]["hard_cross_layer_collision"]
        )
        eligible_pair_count = 0
        low_coverage_pair_count = 0
        for row in candidate_pairs:
            pair_id = row["pair_id"]
            if (
                coverage_map[pair_id]["common_rate_of_smaller_side"] is not None
                and coverage_map[pair_id]["common_rate_of_smaller_side"] < 0.8
            ):
                low_coverage_pair_count += 1
            sec_eligible = sum(
                item["eligible"] for item in security_by_pair.get(pair_id, [])
            )
            if (
                sec_eligible >= 720
                and coverage_map[pair_id]["common_rate_of_smaller_side"] is not None
                and coverage_map[pair_id]["common_rate_of_smaller_side"] >= 0.8
            ):
                eligible_pair_count += 1
        candidate_rows.append(
            {
                "a_candidate_id": candidate,
                "nearest_layer": best_s["pcvt_layer"] if best_s else None,
                "nearest_indicator": best_s["pcvt_indicator_id"] if best_s else None,
                "max_overall_spearman": best_s["spearman_midrank"] if best_s else None,
                "max_tail_jaccard_005": best5["tail_metric"] if best5 else None,
                "max_tail_jaccard_010": best10["tail_metric"] if best10 else None,
                "hard_collision_count": len(hard_pairs),
                "hard_collision_pairs_json": json.dumps(
                    hard_pairs, separators=(",", ":")
                ),
                "eligible_pair_count": eligible_pair_count,
                "low_coverage_pair_count": low_coverage_pair_count,
                "provisional_status_for_A05": "carry_to_A05_with_collision_review"
                if hard_pairs
                else "carry_to_A05",
            }
        )
    return layer_rows, candidate_rows


def _collision_results(
    overall: list[dict[str, Any]],
    years: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    tails: list[dict[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    gate = config["hard_collision_gate"]
    tail_map = {(row["pair_id"], float(row["tail_fraction"])): row for row in tails}
    year_map: dict[str, list[dict[str, Any]]] = {}
    sec_map: dict[str, list[dict[str, Any]]] = {}
    for row in years:
        if row["common_count"] > 0:
            year_map.setdefault(row["pair_id"], []).append(row)
    for row in securities:
        if row["eligible"]:
            sec_map.setdefault(row["pair_id"], []).append(row)
    results: dict[str, dict[str, Any]] = {}
    for row in overall:
        pair_id = row["pair_id"]
        y_values = [
            _float_or_none(item["spearman_midrank"])
            for item in year_map.get(pair_id, [])
        ]
        s_values = [
            _float_or_none(item["spearman_midrank"])
            for item in sec_map.get(pair_id, [])
        ]
        y_min = (
            min(y_values)
            if y_values and all(value is not None for value in y_values)
            else None
        )
        s_q10 = _quantile_cont(s_values, 0.1)
        t5 = _float_or_none(tail_map[(pair_id, 0.05)]["jaccard"])
        t10 = _float_or_none(tail_map[(pair_id, 0.1)]["jaccard"])
        criteria = {
            "overall_spearman": _criterion(
                row["spearman_midrank"],
                gate["overall_spearman_min"],
                _float_or_none(row["spearman_midrank"]) is not None
                and row["spearman_midrank"] >= gate["overall_spearman_min"],
            ),
            "minimum_year_spearman": _criterion(
                y_min,
                gate["minimum_year_spearman_min"],
                y_min is not None and y_min >= gate["minimum_year_spearman_min"],
            ),
            "eligible_security_spearman_q10": _criterion(
                s_q10,
                gate["eligible_security_spearman_q10_min"],
                s_q10 is not None
                and s_q10 >= gate["eligible_security_spearman_q10_min"],
            ),
            "tail_jaccard_005": _criterion(
                t5,
                gate["tail_jaccard_005_min"],
                t5 is not None and t5 >= gate["tail_jaccard_005_min"],
            ),
            "tail_jaccard_010": _criterion(
                t10,
                gate["tail_jaccard_010_min"],
                t10 is not None and t10 >= gate["tail_jaccard_010_min"],
            ),
        }
        results[pair_id] = {
            "pair_id": pair_id,
            "a_candidate_id": row["a_candidate_id"],
            "pcvt_indicator_id": row["pcvt_indicator_id"],
            "pcvt_layer": row["pcvt_layer"],
            "criteria": criteria,
            "hard_cross_layer_collision": all(
                item["passed"] for item in criteria.values()
            ),
        }
    return results


def build_analysis(
    connection: Any,
    pcvt_connection: Any | None,
    config: Mapping[str, Any],
    *,
    a_table: str = "exp_a01_raw_metrics",
    pcvt_table: str = "r0_t04_raw_metric_results",
    pcvt_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build all compact diagnostic aggregates from two read-only databases."""
    registry = pcvt_registry(config)
    pairs = pair_registry(config)
    if pcvt_path is not None:
        alias = "a04_pcvt_db"
        connection.execute(
            f"ATTACH {_sql(str(pcvt_path))} AS {_quote(alias)} (READ_ONLY)"
        )
        pcvt_schema = alias
    elif pcvt_connection is connection:
        pcvt_schema = "main"
    else:
        raise LineageError("pcvt_path_required_for_separate_connection")
    _build_source_views(
        connection,
        a_table=a_table,
        pcvt_schema=pcvt_schema,
        pcvt_table=pcvt_table,
        registry=registry,
    )
    _make_pair_rows(connection, pairs)
    coverage = _pairwise_coverage(connection, pairs)
    overall = _pairwise_overall(connection)
    years = _pairwise_year(connection)
    securities = _pairwise_security(connection)
    tails = _tail_overlap(connection)
    collisions = _collision_results(overall, years, securities, tails, config)
    layer_rows, candidate_rows = _summaries(
        coverage, overall, tails, securities, collisions
    )
    indicator_rows: list[dict[str, Any]] = []
    for row in registry:
        indicator_rows.append(
            {
                "registry_role": "PCVT",
                "indicator_id": row["indicator_id"],
                "layer": row["layer"],
                "raw_metric_name": row["raw_metric_name"],
                "raw_source_indicator_id": row["raw_source_indicator_id"],
                "raw_value_direction": row["raw_value_direction"],
            }
        )
    for candidate in A_IDS:
        indicator_rows.append(
            {
                "registry_role": "A",
                "indicator_id": candidate,
                "layer": "A",
                "raw_metric_name": A_RAW_NAMES[candidate],
                "raw_source_indicator_id": candidate,
                "raw_value_direction": "lower_raw_is_more_convergent",
            }
        )
    disposition = {
        "task_id": TASK_ID,
        "run_id": None,
        "decision_version": "EXP-A04-v1",
        "accepted_A03_candidate_set": ["A1", "A2", "A2b"],
        "pcvt_indicator_ids": [row["indicator_id"] for row in registry],
        "pcvt_layer_mapping": {row["indicator_id"]: row["layer"] for row in registry},
        "pair_count": 24,
        "common_universe_policy": "pair-specific valid finite intersection with security-date one-to-one adapter",
        "hard_collision_thresholds": {
            key: gate
            for key, gate in config["hard_collision_gate"].items()
            if key.endswith("_min")
        },
        "pair_collision_results": [
            collisions[pair_id] for pair_id in sorted(collisions)
        ],
        "candidate_collision_summary": {
            A_SHORT_IDS[row["a_candidate_id"]]: {
                "hard_collision_count": row["hard_collision_count"],
                "hard_collision_pairs": json.loads(row["hard_collision_pairs_json"]),
                "provisional_status_for_A05": row["provisional_status_for_A05"],
            }
            for row in candidate_rows
        },
        "candidate_set_for_A05": ["A1", "A2", "A2b"],
        "candidate_status_for_A05": {
            A_SHORT_IDS[row["a_candidate_id"]]: row["provisional_status_for_A05"]
            for row in candidate_rows
        },
        "decision_status": "provisional_A04_diagnostic",
        "EXP_A05_started": False,
        "A_layer_registered": False,
        "PCATV_created": False,
    }
    return {
        "indicator_registry": indicator_rows,
        "pairwise_coverage": coverage,
        "pairwise_overall": overall,
        "pairwise_year": years,
        "pairwise_security": securities,
        "tail_overlap": tails,
        "layer_summary": layer_rows,
        "candidate_summary": candidate_rows,
        "cross_layer_disposition": disposition,
        "pair_collision_results": collisions,
    }


def build_anomaly_scan(
    analysis: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    synthetic_fixture: bool,
    blocking: list[str] | None = None,
) -> dict[str, Any]:
    blocking_items = list(blocking or [])
    for row in analysis["pairwise_overall"]:
        if not row["common_count"]:
            blocking_items.append(f"pair_common_count_zero:{row['pair_id']}")
        if row["pearson_raw"] is None or row["spearman_midrank"] is None:
            blocking_items.append(f"undefined_overall_correlation:{row['pair_id']}")
    for row in analysis["pairwise_year"]:
        if row["common_count"] > 0 and row["spearman_midrank"] is None:
            blocking_items.append(
                f"undefined_year_correlation:{row['pair_id']}:{row['calendar_year']}"
            )
    if not any(row["common_count"] > 0 for row in analysis["pairwise_year"]):
        blocking_items.append("accepted_year_completely_missing")
    investigation: list[str] = []
    for row in analysis["pairwise_coverage"]:
        if (
            row["common_rate_of_smaller_side"] is not None
            and row["common_rate_of_smaller_side"]
            < config["investigation_policy"]["common_rate_smaller_min"]
        ):
            investigation.append(f"common_rate_smaller_below_80:{row['pair_id']}")
    security_by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in analysis["pairwise_security"]:
        if row["eligible"]:
            security_by_pair.setdefault(row["pair_id"], []).append(row)
    year_by_pair: dict[str, list[float]] = {}
    for row in analysis["pairwise_year"]:
        if row["spearman_midrank"] is not None:
            year_by_pair.setdefault(row["pair_id"], []).append(
                float(row["spearman_midrank"])
            )
    tails = {
        (row["pair_id"], float(row["tail_fraction"])): row
        for row in analysis["tail_overlap"]
    }
    for row in analysis["pairwise_overall"]:
        pair_id = row["pair_id"]
        sec = security_by_pair.get(pair_id, [])
        if len(sec) < config["investigation_policy"]["eligible_security_min"]:
            investigation.append(f"eligible_security_count_below_720:{pair_id}")
        y = year_by_pair.get(pair_id, [])
        if (
            y
            and max(y) - min(y)
            > config["investigation_policy"]["year_spearman_range_max"]
        ):
            investigation.append(f"year_spearman_range_high:{pair_id}")
        s = [
            float(item["spearman_midrank"])
            for item in sec
            if item["spearman_midrank"] is not None
        ]
        if (
            len(s) >= 2
            and (_quantile_cont(s, 0.9) - _quantile_cont(s, 0.1))
            > config["investigation_policy"]["security_spearman_iqr10_90_max"]
        ):
            investigation.append(f"security_spearman_range_high:{pair_id}")
        if (
            row["spearman_midrank"] is not None
            and row["spearman_midrank"]
            <= config["investigation_policy"][
                "overall_spearman_investigate_below_or_equal"
            ]
        ):
            investigation.append(f"negative_overall_spearman:{pair_id}")
        for fraction, key in (
            (0.05, "tail_jaccard_005_min"),
            (0.1, "tail_jaccard_010_min"),
        ):
            value = tails[(pair_id, fraction)]["jaccard"]
            if (
                value is not None
                and abs(value - config["hard_collision_gate"][key])
                <= config["investigation_policy"]["near_gate_distance"]
            ):
                investigation.append(f"gate_near_threshold:{pair_id}:{key}")
        collision = analysis["pair_collision_results"][pair_id][
            "hard_cross_layer_collision"
        ]
        if collision:
            investigation.append(f"hard_cross_layer_collision:{pair_id}")
        for key, threshold_key in (
            ("overall_spearman", "overall_spearman_min"),
            ("minimum_year_spearman", "minimum_year_spearman_min"),
            ("eligible_security_spearman_q10", "eligible_security_spearman_q10_min"),
        ):
            actual = analysis["pair_collision_results"][pair_id]["criteria"][key][
                "actual"
            ]
            if (
                actual is not None
                and abs(actual - config["hard_collision_gate"][threshold_key])
                <= config["investigation_policy"]["near_gate_distance"]
            ):
                investigation.append(f"gate_near_threshold:{pair_id}:{key}")
    if synthetic_fixture:
        investigation.append("synthetic_fixture_requires_investigation")
    # preserve deterministic first occurrence order while removing repeats
    investigation = list(dict.fromkeys(investigation))
    blocking_items = list(dict.fromkeys(blocking_items))
    status = (
        "failed"
        if blocking_items
        else "passed_with_investigation_items"
        if investigation
        else "passed"
    )
    return {
        "task_id": TASK_ID,
        "status": status,
        "blocking_anomalies": blocking_items,
        "blocking_anomaly_count": len(blocking_items),
        "investigation_items": investigation,
        "investigation_item_count": len(investigation),
        "synthetic_fixture": synthetic_fixture,
    }


def build_result_analysis(
    run_id: str, reviewed_sha: str, anomaly_status: str, *, synthetic_fixture: bool
) -> str:
    lines = ["# EXP-A04 cross-layer diagnostics"]
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
        elif heading == ANALYSIS_HEADINGS[-1]:
            lines.append(
                "needs_investigation_before_user_review"
                if synthetic_fixture
                or anomaly_status == "passed_with_investigation_items"
                else "ready_for_user_formal_result_review"
            )
        else:
            lines.append(
                "See the corresponding compact artifact and independent validator result."
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    output_root: Path, analysis: Mapping[str, Any], *, run_id: str | None = None
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for name, fields in CSV_FIELDS.items():
        filename = f"exp_a04_{name}.csv"
        with (output_root / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            for row in analysis[name]:
                writer.writerow({field: _finite(row.get(field)) for field in fields})
    disposition = dict(analysis["cross_layer_disposition"])
    disposition["run_id"] = run_id
    (output_root / "exp_a04_cross_layer_disposition.json").write_text(
        json.dumps(
            disposition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def expected_output_row_counts() -> dict[str, int]:
    return {
        "exp_a04_indicator_registry.csv": 11,
        "exp_a04_pairwise_coverage.csv": 24,
        "exp_a04_pairwise_overall.csv": 24,
        "exp_a04_pairwise_year.csv": 264,
        "exp_a04_pairwise_security.csv": 19200,
        "exp_a04_tail_overlap.csv": 72,
        "exp_a04_layer_summary.csv": 12,
        "exp_a04_candidate_summary.csv": 3,
    }
