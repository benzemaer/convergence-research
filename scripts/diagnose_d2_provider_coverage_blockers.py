"""Diagnose D2 provider coverage blockers from candidate DuckDB staging.

D2-T18 is read-only: it inspects D2-T15/D2-T17 candidate staging tables and
writes diagnostic CSV/JSON/Markdown reports. It does not fetch provider data,
modify DuckDB contents, publish manifests, or change acceptance decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_PATH_TOKENS = (
    "data/raw",
    "data\\raw",
    "data/external",
    "data\\external",
    "marketdb",
    ".day",
)
OUTPUT_FILES = (
    "d2_t18_coverage_blocker_summary.json",
    "d2_t18_gap_counts_by_type.csv",
    "d2_t18_gap_counts_by_security.csv",
    "d2_t18_gap_counts_by_date.csv",
    "d2_t18_gap_rows.csv",
    "d2_t18_gap_overlap_by_security_date.csv",
    "d2_t18_missing_daily_rows.csv",
    "d2_t18_missing_adj_factor_rows.csv",
    "d2_t18_missing_stk_limit_rows.csv",
    "d2_t18_missing_daily_intervals.csv",
    "d2_t18_missing_adj_factor_intervals.csv",
    "d2_t18_missing_stk_limit_intervals.csv",
    "d2_t18_security_level_diagnosis.csv",
    "d2_t18_date_level_diagnosis.csv",
    "d2_t18_gap_policy_candidates.csv",
    "d2_t18_targeted_repair_candidates.csv",
    "d2_t18_recommended_actions.md",
    "d2_t18_sql_manifest.sql",
)


class D2T18DiagnosticsError(ValueError):
    """Raised when D2-T18 diagnostic input or output gates fail."""


@dataclass(frozen=True)
class GapInterval:
    ts_code: str
    gap_type: str
    interval_start: str
    interval_end: str
    interval_length: int


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def guard_input_duckdb_path(path: Path) -> None:
    normalized = _norm(path)
    if any(token.replace("\\", "/") in normalized for token in FORBIDDEN_PATH_TOKENS):
        raise D2T18DiagnosticsError(f"forbidden input DuckDB path: {path}")
    if path.suffix.lower() != ".duckdb":
        raise D2T18DiagnosticsError(f"input must be a DuckDB file: {path}")
    if "data/generated/d2/" not in normalized:
        raise D2T18DiagnosticsError(
            "input DuckDB must be an ignored D2 candidate staging path"
        )


def guard_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if any(token.replace("\\", "/") in normalized for token in FORBIDDEN_PATH_TOKENS):
        raise D2T18DiagnosticsError(f"forbidden output path: {path}")
    if normalized.endswith(".duckdb") or ".duckdb/" in normalized:
        raise D2T18DiagnosticsError(f"output-dir must not be a DuckDB path: {path}")
    if "data/generated/d2/" not in normalized:
        raise D2T18DiagnosticsError("output-dir must be under data/generated/d2/")


def rows_as_dicts(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
    )


def require_tables(conn: duckdb.DuckDBPyConnection) -> None:
    required = {
        "d2_coverage_gaps",
        "d2_source_status",
        "d2_factor_evidence",
        "d2_expected_security_dates",
        "staging_daily_raw",
        "staging_adj_factor",
        "staging_suspend_d",
        "staging_stk_limit",
        "staging_stock_basic",
        "staging_trade_calendar",
        "staging_fetch_ledger",
        "d2_quality_summary",
    }
    missing = sorted(table for table in required if not table_exists(conn, table))
    if missing:
        raise D2T18DiagnosticsError(f"missing required tables: {missing}")


def load_quality_summary(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = rows_as_dicts(conn, "SELECT metric, value FROM d2_quality_summary")
    metrics: dict[str, int] = {}
    for row in rows:
        value = row["value"]
        try:
            metrics[str(row["metric"])] = int(value)
        except (TypeError, ValueError):
            continue
    return metrics


def quality_blockers(metrics: dict[str, int]) -> list[str]:
    blocker_map = {
        "listed_open_missing_daily_count": "listed_open_missing_daily_count",
        "unresolved_adjustment_factor_count": "unresolved_adjustment_factor_count",
        "unresolved_price_limit_status_count": "unresolved_price_limit_status_count",
        "price_limit_daily_dependency_missing_count": (
            "price_limit_daily_dependency_missing_count"
        ),
        "unmapped_security_count": "unmapped_security_count",
        "provider_error_count": "provider_error_count",
        "rate_limit_count": "rate_limit_count",
        "timeout_count": "timeout_count",
    }
    return [label for metric, label in blocker_map.items() if metrics.get(metric, 0)]


def d2_acceptance_observed(metrics: dict[str, int]) -> str:
    provider_blockers = [
        "listed_open_missing_daily_count",
        "unresolved_adjustment_factor_count",
        "unresolved_price_limit_status_count",
        "unmapped_security_count",
        "provider_error_count",
        "rate_limit_count",
        "timeout_count",
    ]
    quality_blockers = [
        "duplicate_daily_key_count",
        "duplicate_adj_factor_key_count",
        "duplicate_stk_limit_key_count",
        "duplicate_suspend_key_count",
        "null_ohlc_count",
        "non_positive_price_count",
        "high_low_violation_count",
    ]
    if any(metrics.get(key, 0) for key in provider_blockers):
        return "blocked_pending_provider_coverage"
    if any(metrics.get(key, 0) for key in quality_blockers):
        return "blocked_pending_quality_resolution"
    return "accepted_for_d3_candidate_generation"


def gap_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return rows_as_dicts(
        conn,
        """
        SELECT ts_code, trade_date, gap_type
        FROM d2_coverage_gaps
        ORDER BY gap_type, ts_code, trade_date
        """,
    )


def expected_date_index(conn: duckdb.DuckDBPyConnection) -> dict[str, dict[str, int]]:
    rows = rows_as_dicts(
        conn,
        """
        SELECT ts_code, trade_date
        FROM d2_expected_security_dates
        ORDER BY ts_code, trade_date
        """,
    )
    index: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        index[str(row["ts_code"])][str(row["trade_date"])] = len(
            index[str(row["ts_code"])]
        )
    return index


def compress_intervals(
    rows: list[dict[str, Any]], date_index: dict[str, dict[str, int]]
) -> list[GapInterval]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["ts_code"]), str(row["gap_type"]))].append(
            str(row["trade_date"])
        )
    intervals: list[GapInterval] = []
    for (ts_code, gap_type), dates in sorted(grouped.items()):
        unique_dates = sorted(set(dates))
        start = prev = unique_dates[0]
        length = 1
        for date in unique_dates[1:]:
            prev_idx = date_index.get(ts_code, {}).get(prev)
            date_idx = date_index.get(ts_code, {}).get(date)
            if prev_idx is not None and date_idx == prev_idx + 1:
                prev = date
                length += 1
                continue
            intervals.append(GapInterval(ts_code, gap_type, start, prev, length))
            start = prev = date
            length = 1
        intervals.append(GapInterval(ts_code, gap_type, start, prev, length))
    return intervals


def gap_counts_by_type(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(row["gap_type"]) for row in gaps)
    return [
        {"gap_type": gap_type, "row_count": row_count}
        for gap_type, row_count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]


def gap_counts_by_security(
    gaps: list[dict[str, Any]], intervals: list[GapInterval]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in gaps:
        grouped[(str(row["ts_code"]), str(row["gap_type"]))].append(
            str(row["trade_date"])
        )
    interval_stats: dict[tuple[str, str], list[GapInterval]] = defaultdict(list)
    for interval in intervals:
        interval_stats[(interval.ts_code, interval.gap_type)].append(interval)
    rows: list[dict[str, Any]] = []
    for key, dates in sorted(grouped.items()):
        ts_code, gap_type = key
        stats = interval_stats[key]
        rows.append(
            {
                "ts_code": ts_code,
                "gap_type": gap_type,
                "row_count": len(dates),
                "first_date": min(dates),
                "last_date": max(dates),
                "continuous_interval_count": len(stats),
                "max_continuous_interval_length": max(
                    (item.interval_length for item in stats), default=0
                ),
            }
        )
    return sorted(rows, key=lambda row: (row["ts_code"], row["gap_type"]))


def gap_counts_by_date(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((str(row["trade_date"]), str(row["gap_type"])) for row in gaps)
    return [
        {"trade_date": trade_date, "gap_type": gap_type, "row_count": row_count}
        for (trade_date, gap_type), row_count in sorted(counts.items())
    ]


def overlap_rows(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in gaps:
        grouped[(str(row["ts_code"]), str(row["trade_date"]))].add(str(row["gap_type"]))
    rows: list[dict[str, Any]] = []
    for (ts_code, trade_date), gap_types in sorted(grouped.items()):
        rows.append(
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "gap_types": "|".join(sorted(gap_types)),
                "gap_type_count": len(gap_types),
                "has_missing_daily": "listed_open_missing_daily" in gap_types,
                "has_daily_dependency_missing": "daily_dependency_missing" in gap_types,
                "has_stk_limit_missing": "stk_limit_missing" in gap_types,
                "has_missing_adj_factor": "unresolved_adjustment_factor" in gap_types,
            }
        )
    return rows


def has_row(value: Any) -> bool:
    return value not in (None, "")


def missing_daily_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = rows_as_dicts(
        conn,
        """
        SELECT g.ts_code,
               g.trade_date,
               s.trading_status,
               s.daily_status,
               s.price_limit_status,
               sd.suspend_type,
               b.ts_code AS stock_basic_ts_code,
               b.list_date,
               b.delist_date,
               c.is_open,
               a.ts_code AS adj_factor_ts_code,
               l.ts_code AS stk_limit_ts_code
        FROM d2_coverage_gaps g
        LEFT JOIN d2_source_status s
          ON s.ts_code = g.ts_code AND s.trade_date = g.trade_date
        LEFT JOIN staging_suspend_d sd
          ON sd.ts_code = g.ts_code AND sd.suspend_date = g.trade_date
        LEFT JOIN staging_stock_basic b
          ON b.ts_code = g.ts_code
        LEFT JOIN staging_trade_calendar c
          ON c.cal_date = g.trade_date
        LEFT JOIN staging_adj_factor a
          ON a.ts_code = g.ts_code AND a.trade_date = g.trade_date
        LEFT JOIN staging_stk_limit l
          ON l.ts_code = g.ts_code AND l.trade_date = g.trade_date
        WHERE g.gap_type = 'listed_open_missing_daily'
        ORDER BY g.ts_code, g.trade_date
        """,
    )
    diagnosed: list[dict[str, Any]] = []
    for row in rows:
        list_date = str(row.get("list_date") or "")
        delist_date = str(row.get("delist_date") or "")
        trade_date = str(row["trade_date"])
        is_before_list = bool(list_date and trade_date < list_date)
        is_after_delist = bool(delist_date and trade_date > delist_date)
        has_suspend = has_row(row.get("suspend_type"))
        if row.get("suspend_type") == "S":
            diagnosis = "suspend_semantics_gap"
            action = "classify_as_suspended_or_not_applicable"
        elif not has_row(row.get("stock_basic_ts_code")) or is_before_list:
            diagnosis = "stock_basic_boundary_gap"
            action = "adjust_stock_basic_boundary_policy"
        elif is_after_delist:
            diagnosis = "delist_boundary_gap"
            action = "adjust_stock_basic_boundary_policy"
        elif str(row.get("is_open") or "") != "1":
            diagnosis = "trade_calendar_boundary_gap"
            action = "investigate_trade_calendar"
        elif row.get("daily_status") == "missing":
            diagnosis = "provider_daily_missing"
            action = "targeted_daily_refetch"
        else:
            diagnosis = "unknown_missing_daily"
            action = "manual_review"
        diagnosed.append(
            {
                **row,
                "has_suspend_row": has_suspend,
                "has_stock_basic_row": has_row(row.get("stock_basic_ts_code")),
                "is_before_list_date": is_before_list,
                "is_after_delist_date": is_after_delist,
                "is_trade_calendar_open": str(row.get("is_open") or "") == "1",
                "has_adj_factor": has_row(row.get("adj_factor_ts_code")),
                "has_stk_limit": has_row(row.get("stk_limit_ts_code")),
                "diagnosis": diagnosis,
                "recommended_action": action,
            }
        )
    return diagnosed


def missing_adj_factor_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = rows_as_dicts(
        conn,
        """
        SELECT g.ts_code,
               g.trade_date,
               f.adjustment_factor_status,
               d.ts_code AS daily_ts_code,
               sd.suspend_type,
               (
                 SELECT max(a.trade_date)
                 FROM staging_adj_factor a
                 WHERE a.ts_code = g.ts_code AND a.trade_date < g.trade_date
               ) AS nearest_previous_adj_factor_date,
               (
                 SELECT min(a.trade_date)
                 FROM staging_adj_factor a
                 WHERE a.ts_code = g.ts_code AND a.trade_date > g.trade_date
               ) AS nearest_next_adj_factor_date
        FROM d2_coverage_gaps g
        LEFT JOIN d2_factor_evidence f
          ON f.ts_code = g.ts_code AND f.trade_date = g.trade_date
        LEFT JOIN staging_daily_raw d
          ON d.ts_code = g.ts_code AND d.trade_date = g.trade_date
        LEFT JOIN staging_suspend_d sd
          ON sd.ts_code = g.ts_code AND sd.suspend_date = g.trade_date
        WHERE g.gap_type = 'unresolved_adjustment_factor'
        ORDER BY g.ts_code, g.trade_date
        """,
    )
    diagnosed: list[dict[str, Any]] = []
    for row in rows:
        prev_date = str(row.get("nearest_previous_adj_factor_date") or "")
        next_date = str(row.get("nearest_next_adj_factor_date") or "")
        if row.get("suspend_type") == "S":
            diagnosis = "suspend_carry_forward_candidate"
            action = "allow_adj_factor_carry_forward_policy"
        elif prev_date:
            diagnosis = "carry_forward_candidate"
            action = "allow_adj_factor_carry_forward_policy"
        elif not row.get("daily_ts_code"):
            diagnosis = "boundary_gap"
            action = "manual_review"
        elif next_date:
            diagnosis = "provider_adj_factor_missing"
            action = "targeted_adj_factor_refetch"
        else:
            diagnosis = "unknown_adj_factor_gap"
            action = "manual_review"
        diagnosed.append(
            {
                **row,
                "has_daily": has_row(row.get("daily_ts_code")),
                "has_suspend_row": has_row(row.get("suspend_type")),
                "days_since_previous_adj_factor": _date_diff(
                    row["trade_date"], prev_date
                ),
                "days_to_next_adj_factor": _date_diff(next_date, row["trade_date"]),
                "diagnosis": diagnosis,
                "recommended_action": action,
            }
        )
    return diagnosed


def missing_stk_limit_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = rows_as_dicts(
        conn,
        """
        SELECT g.ts_code,
               g.trade_date,
               g.gap_type,
               s.trading_status,
               s.daily_status,
               s.price_limit_status,
               d.ts_code AS daily_ts_code,
               sd.suspend_type,
               l.ts_code AS stk_limit_ts_code
        FROM d2_coverage_gaps g
        LEFT JOIN d2_source_status s
          ON s.ts_code = g.ts_code AND s.trade_date = g.trade_date
        LEFT JOIN staging_daily_raw d
          ON d.ts_code = g.ts_code AND d.trade_date = g.trade_date
        LEFT JOIN staging_suspend_d sd
          ON sd.ts_code = g.ts_code AND sd.suspend_date = g.trade_date
        LEFT JOIN staging_stk_limit l
          ON l.ts_code = g.ts_code AND l.trade_date = g.trade_date
        WHERE g.gap_type IN ('daily_dependency_missing', 'stk_limit_missing')
        ORDER BY g.gap_type, g.ts_code, g.trade_date
        """,
    )
    diagnosed: list[dict[str, Any]] = []
    for row in rows:
        if row["gap_type"] == "daily_dependency_missing":
            diagnosis = "daily_dependency_missing"
            action = "depends_on_daily_repair"
        elif row.get("suspend_type") == "S":
            diagnosis = "price_limit_not_applicable_candidate"
            action = "classify_price_limit_not_applicable"
        elif not row.get("daily_ts_code"):
            diagnosis = "boundary_gap"
            action = "manual_review"
        elif row.get("price_limit_status") == "stk_limit_missing":
            diagnosis = "provider_stk_limit_missing"
            action = "targeted_stk_limit_refetch"
        else:
            diagnosis = "unknown_stk_limit_gap"
            action = "manual_review"
        diagnosed.append(
            {
                **row,
                "has_daily": has_row(row.get("daily_ts_code")),
                "has_suspend_row": has_row(row.get("suspend_type")),
                "has_stk_limit": has_row(row.get("stk_limit_ts_code")),
                "diagnosis": diagnosis,
                "recommended_action": action,
            }
        )
    return diagnosed


def _date_diff(later: Any, earlier: Any) -> int | str:
    if not later or not earlier:
        return ""
    left = str(later)
    right = str(earlier)
    try:
        return (
            datetime.strptime(left, "%Y%m%d") - datetime.strptime(right, "%Y%m%d")
        ).days
    except ValueError:
        return ""


def repair_candidates(
    intervals: list[GapInterval], missing_adj: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    adj_repair_dates = {
        (str(row["ts_code"]), str(row["trade_date"]))
        for row in missing_adj
        if row["recommended_action"] == "targeted_adj_factor_refetch"
    }
    rows: list[dict[str, Any]] = []
    for interval in intervals:
        endpoint = ""
        priority = ""
        reason = interval.gap_type
        if interval.gap_type == "listed_open_missing_daily":
            endpoint = "daily"
            priority = "P0"
        elif interval.gap_type == "stk_limit_missing":
            endpoint = "stk_limit"
            priority = "P1"
        elif interval.gap_type == "unresolved_adjustment_factor":
            has_provider_gap = any(
                ts_code == interval.ts_code
                and interval.interval_start <= trade_date <= interval.interval_end
                for ts_code, trade_date in adj_repair_dates
            )
            if not has_provider_gap:
                continue
            endpoint = "adj_factor"
            priority = "P2"
        elif interval.gap_type == "daily_dependency_missing":
            continue
        if endpoint:
            rows.append(
                {
                    "endpoint": endpoint,
                    "ts_code": interval.ts_code,
                    "start_date": interval.interval_start,
                    "end_date": interval.interval_end,
                    "reason": reason,
                    "gap_row_count": interval.interval_length,
                    "priority": priority,
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["priority"],
            row["endpoint"],
            row["ts_code"],
            row["start_date"],
        ),
    )


def policy_candidates(
    missing_daily: list[dict[str, Any]],
    missing_adj: list[dict[str, Any]],
    missing_stk: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, gap_type in (
        (missing_daily, "listed_open_missing_daily"),
        (missing_adj, "unresolved_adjustment_factor"),
        (missing_stk, "price_limit_gap"),
    ):
        grouped: Counter[tuple[str, str]] = Counter()
        for row in source:
            if str(row.get("recommended_action", "")).startswith("targeted_"):
                continue
            if row.get("recommended_action") == "depends_on_daily_repair":
                continue
            grouped[(str(row["ts_code"]), str(row["recommended_action"]))] += 1
        for (ts_code, action), count in sorted(grouped.items()):
            rows.append(
                {
                    "gap_type": gap_type,
                    "ts_code": ts_code,
                    "recommended_action": action,
                    "gap_row_count": count,
                    "policy_reason": "requires_D2_T19B_policy_decision",
                }
            )
    return rows


def security_level_diagnosis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row["ts_code"])][str(row["gap_type"])] += 1
    return [
        {
            "ts_code": ts_code,
            "listed_open_missing_daily": counts["listed_open_missing_daily"],
            "daily_dependency_missing": counts["daily_dependency_missing"],
            "stk_limit_missing": counts["stk_limit_missing"],
            "unresolved_adjustment_factor": counts["unresolved_adjustment_factor"],
            "total_gap_rows": sum(counts.values()),
        }
        for ts_code, counts in sorted(grouped.items())
    ]


def date_level_diagnosis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        grouped[str(row["trade_date"])][str(row["gap_type"])] += 1
    return [
        {
            "trade_date": trade_date,
            "listed_open_missing_daily": counts["listed_open_missing_daily"],
            "daily_dependency_missing": counts["daily_dependency_missing"],
            "stk_limit_missing": counts["stk_limit_missing"],
            "unresolved_adjustment_factor": counts["unresolved_adjustment_factor"],
            "total_gap_rows": sum(counts.values()),
        }
        for trade_date, counts in sorted(grouped.items())
    ]


def top_date(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    if not rows:
        return {}
    return max(rows, key=lambda row: (int(row.get(metric, 0)), str(row["trade_date"])))


def build_markdown(summary: dict[str, Any]) -> str:
    gap_counts = summary["gap_counts_by_type"]
    lines = [
        "# D2-T18 provider coverage blocker diagnostics",
        "",
        "1. 当前 D2 是否通过验收：否。",
        (
            "2. 为什么不是 runner 问题："
            f"blocking_fetch_status_count={summary['blocking_fetch_status_count']}，"
            f"provider_error_count={summary['provider_error_count']}，"
            f"timeout_count={summary['timeout_count']}。"
        ),
        f"3. 为什么是 coverage blocker：gap counts = {gap_counts}。",
        (
            "4. gap 是否集中："
            f"security_gap_group_count={summary['security_gap_group_count']}，"
            f"date_gap_group_count={summary['date_gap_group_count']}。"
        ),
        (
            "5. daily missing 的影响："
            "listed_open_missing_daily 同时导致 daily_dependency_missing 的行数为 "
            f"{summary['daily_missing_implies_price_limit_dependency_count']}。"
        ),
        ("6. 哪些可以 targeted repair：见 `d2_t18_targeted_repair_candidates.csv`。"),
        ("7. 哪些需要 policy decision：见 `d2_t18_gap_policy_candidates.csv`。"),
        "8. 下一步建议：",
        "   - D2-T19A targeted repair runner for daily/adj_factor/stk_limit candidates",
        "   - D2-T19B coverage policy decision for carry-forward/not-applicable cases",
        "9. 明确 D3/R0 仍 blocked。",
        "",
    ]
    return "\n".join(lines)


def write_sql_manifest(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "-- D2-T18 diagnostic SQL manifest",
                "SELECT gap_type, count(*) AS row_count "
                "FROM d2_coverage_gaps GROUP BY 1 ORDER BY row_count DESC;",
                "SELECT ts_code, trade_date, gap_type "
                "FROM d2_coverage_gaps ORDER BY gap_type, ts_code, trade_date;",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def run_diagnostics(
    *,
    duckdb_path: Path,
    output_dir: Path,
    top_n_securities: int = 50,
    top_n_dates: int = 50,
    sample_rows_per_gap_type: int = 100,
    fail_if_no_gaps: bool = False,
    write_sql: bool = False,
) -> dict[str, Any]:
    del top_n_securities, top_n_dates, sample_rows_per_gap_type
    guard_input_duckdb_path(duckdb_path)
    guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        require_tables(conn)
        metrics = load_quality_summary(conn)
        gaps = gap_rows(conn)
        if fail_if_no_gaps and not gaps:
            raise D2T18DiagnosticsError("no D2 coverage gaps found")
        date_index = expected_date_index(conn)
        intervals = compress_intervals(gaps, date_index)
        interval_rows = [interval.__dict__ for interval in intervals]
        missing_daily = missing_daily_rows(conn)
        missing_adj = missing_adj_factor_rows(conn)
        missing_stk = missing_stk_limit_rows(conn)
        overlaps = overlap_rows(gaps)
        security_rows = gap_counts_by_security(gaps, intervals)
        date_rows = gap_counts_by_date(gaps)
        security_diag = security_level_diagnosis(gaps)
        date_diag = date_level_diagnosis(gaps)
        policy_rows = policy_candidates(missing_daily, missing_adj, missing_stk)
        repair_rows = repair_candidates(intervals, missing_adj)
        type_rows = gap_counts_by_type(gaps)
        type_map = {row["gap_type"]: row["row_count"] for row in type_rows}
        blocking_fetch_status_count = int(
            conn.execute(
                """
                SELECT count(*)
                FROM staging_fetch_ledger
                WHERE error_category IN ('provider_error', 'timeout', 'rate_limit')
                   OR status IN ('failed', 'data_validation_error')
                """
            ).fetchone()[0]
            or 0
        )
    finally:
        conn.close()

    daily_dependency_overlap = sum(
        1
        for row in overlaps
        if row["has_missing_daily"] and row["has_daily_dependency_missing"]
    )
    summary = {
        "task_id": "D2-T18",
        "source_duckdb_path": str(duckdb_path),
        "d2_acceptance_observed": d2_acceptance_observed(metrics),
        "blocking_fetch_status_count": blocking_fetch_status_count,
        "provider_error_count": metrics.get("provider_error_count", 0),
        "timeout_count": metrics.get("timeout_count", 0),
        "rate_limit_count": metrics.get("rate_limit_count", 0),
        "quality_blockers_observed": quality_blockers(metrics),
        "gap_counts_by_type": type_map,
        "unique_gap_security_date_count": len(overlaps),
        "gap_type_row_count": len(gaps),
        "security_gap_group_count": len(security_rows),
        "date_gap_group_count": len(date_rows),
        "daily_missing_implies_price_limit_dependency_count": daily_dependency_overlap,
        "top_date_by_total_gap_count": top_date(date_diag, "total_gap_rows"),
        "top_date_by_missing_daily_count": top_date(
            date_diag, "listed_open_missing_daily"
        ),
        "top_date_by_adj_factor_missing_count": top_date(
            date_diag, "unresolved_adjustment_factor"
        ),
        "top_date_by_stk_limit_missing_count": top_date(date_diag, "stk_limit_missing"),
        "targeted_repair_candidate_count": len(repair_rows),
        "policy_candidate_count": len(policy_rows),
        "coverage_blockers_concentrated": len(security_rows) <= 10,
        "recommended_next_pr": "D2-T19 targeted repair or policy decision",
        "d3_generation_authorized": False,
        "r0_state_generated": False,
        "data_version_published": False,
    }

    interval_daily = [
        row for row in interval_rows if row["gap_type"] == "listed_open_missing_daily"
    ]
    interval_adj = [
        row
        for row in interval_rows
        if row["gap_type"] == "unresolved_adjustment_factor"
    ]
    interval_stk = [
        row
        for row in interval_rows
        if row["gap_type"] in {"stk_limit_missing", "daily_dependency_missing"}
    ]
    write_json(output_dir / "d2_t18_coverage_blocker_summary.json", summary)
    write_csv(
        output_dir / "d2_t18_gap_counts_by_type.csv",
        type_rows,
        ["gap_type", "row_count"],
    )
    write_csv(
        output_dir / "d2_t18_gap_counts_by_security.csv",
        security_rows,
        [
            "ts_code",
            "gap_type",
            "row_count",
            "first_date",
            "last_date",
            "continuous_interval_count",
            "max_continuous_interval_length",
        ],
    )
    write_csv(
        output_dir / "d2_t18_gap_counts_by_date.csv",
        date_rows,
        ["trade_date", "gap_type", "row_count"],
    )
    write_csv(
        output_dir / "d2_t18_gap_rows.csv", gaps, ["ts_code", "trade_date", "gap_type"]
    )
    write_csv(
        output_dir / "d2_t18_gap_overlap_by_security_date.csv",
        overlaps,
        [
            "ts_code",
            "trade_date",
            "gap_types",
            "gap_type_count",
            "has_missing_daily",
            "has_daily_dependency_missing",
            "has_stk_limit_missing",
            "has_missing_adj_factor",
        ],
    )
    write_csv(
        output_dir / "d2_t18_missing_daily_rows.csv",
        missing_daily,
        [
            "ts_code",
            "trade_date",
            "trading_status",
            "daily_status",
            "price_limit_status",
            "has_suspend_row",
            "suspend_type",
            "has_stock_basic_row",
            "list_date",
            "delist_date",
            "is_before_list_date",
            "is_after_delist_date",
            "is_trade_calendar_open",
            "has_adj_factor",
            "has_stk_limit",
            "diagnosis",
            "recommended_action",
        ],
    )
    write_csv(
        output_dir / "d2_t18_missing_adj_factor_rows.csv",
        missing_adj,
        [
            "ts_code",
            "trade_date",
            "adjustment_factor_status",
            "has_daily",
            "has_suspend_row",
            "suspend_type",
            "nearest_previous_adj_factor_date",
            "nearest_next_adj_factor_date",
            "days_since_previous_adj_factor",
            "days_to_next_adj_factor",
            "diagnosis",
            "recommended_action",
        ],
    )
    write_csv(
        output_dir / "d2_t18_missing_stk_limit_rows.csv",
        missing_stk,
        [
            "ts_code",
            "trade_date",
            "trading_status",
            "daily_status",
            "price_limit_status",
            "has_daily",
            "has_suspend_row",
            "has_stk_limit",
            "diagnosis",
            "recommended_action",
        ],
    )
    interval_columns = [
        "ts_code",
        "gap_type",
        "interval_start",
        "interval_end",
        "interval_length",
    ]
    write_csv(
        output_dir / "d2_t18_missing_daily_intervals.csv",
        interval_daily,
        interval_columns,
    )
    write_csv(
        output_dir / "d2_t18_missing_adj_factor_intervals.csv",
        interval_adj,
        interval_columns,
    )
    write_csv(
        output_dir / "d2_t18_missing_stk_limit_intervals.csv",
        interval_stk,
        interval_columns,
    )
    write_csv(
        output_dir / "d2_t18_security_level_diagnosis.csv",
        security_diag,
        [
            "ts_code",
            "listed_open_missing_daily",
            "daily_dependency_missing",
            "stk_limit_missing",
            "unresolved_adjustment_factor",
            "total_gap_rows",
        ],
    )
    write_csv(
        output_dir / "d2_t18_date_level_diagnosis.csv",
        date_diag,
        [
            "trade_date",
            "listed_open_missing_daily",
            "daily_dependency_missing",
            "stk_limit_missing",
            "unresolved_adjustment_factor",
            "total_gap_rows",
        ],
    )
    write_csv(
        output_dir / "d2_t18_gap_policy_candidates.csv",
        policy_rows,
        ["gap_type", "ts_code", "recommended_action", "gap_row_count", "policy_reason"],
    )
    write_csv(
        output_dir / "d2_t18_targeted_repair_candidates.csv",
        repair_rows,
        [
            "endpoint",
            "ts_code",
            "start_date",
            "end_date",
            "reason",
            "gap_row_count",
            "priority",
        ],
    )
    (output_dir / "d2_t18_recommended_actions.md").write_text(
        build_markdown(summary), encoding="utf-8"
    )
    sql_path = output_dir / "d2_t18_sql_manifest.sql"
    if write_sql:
        write_sql_manifest(sql_path)
    else:
        sql_path.write_text(
            "-- pass --write-sql to emit diagnostic SQL\n", encoding="utf-8"
        )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-n-securities", default=50, type=int)
    parser.add_argument("--top-n-dates", default=50, type=int)
    parser.add_argument("--sample-rows-per-gap-type", default=100, type=int)
    parser.add_argument("--fail-if-no-gaps", action="store_true")
    parser.add_argument("--write-sql", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = run_diagnostics(
        duckdb_path=args.duckdb_path,
        output_dir=args.output_dir,
        top_n_securities=args.top_n_securities,
        top_n_dates=args.top_n_dates,
        sample_rows_per_gap_type=args.sample_rows_per_gap_type,
        fail_if_no_gaps=args.fail_if_no_gaps,
        write_sql=args.write_sql,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
