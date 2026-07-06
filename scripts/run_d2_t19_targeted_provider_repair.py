"""Run D2-T19 targeted provider repair and coverage policy evidence diagnostics.

D2-T19 copies a D2-T17/D2-T15 candidate DuckDB staging file into a new
candidate output directory, optionally runs only D2-T18 targeted repair tasks,
and writes policy evidence for unresolved adjustment-factor candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    SecurityMajorFetchTask,
    _task_hash,
    build_acceptance_reports,
    compute_quality_gate,
)
from scripts.run_d2_tnskhdata_security_major_provider_runner import (
    AdaptiveRequestLimiter,
    ProviderCallVariant,
    _classify_error,
    _frame_records,
    _redact_error,
    create_tnskhdata_client,
    validate_and_filter_rows,
)

FORBIDDEN_PATH_TOKENS = (
    "data/raw",
    "data\\raw",
    "data/external",
    "data\\external",
    "marketdb",
    ".day",
)
CANONICAL_DUCKDB_NAME = "d2_t15_tnskhdata_staging.duckdb"
REPAIR_PLAN_FILE = "d2_t19_repair_plan.jsonl"
REPAIR_LEDGER_FILE = "d2_t19_repair_ledger.jsonl"


class D2T19RepairError(ValueError):
    """Raised when D2-T19 repair inputs, outputs, or gates fail."""


@dataclass(frozen=True)
class D2T19RepairTask:
    repair_task_id: str
    endpoint: str
    ts_code: str
    start_date: str
    end_date: str
    reason: str
    priority: str
    source_gap_row_count: int
    param_strategy: str
    task_hash: str


@dataclass(frozen=True)
class D2T19LedgerEntry:
    run_id: str
    repair_task_id: str
    endpoint: str
    ts_code: str
    start_date: str
    end_date: str
    reason: str
    priority: str
    param_variant: str
    status: str
    attempt_count: int
    row_count: int
    accepted_row_count: int
    target_gap_row_count: int
    covered_gap_row_count_after_write: int
    remaining_gap_row_count_after_write: int
    error_category: str | None
    error_message_redacted: str | None
    started_at: str
    completed_at: str
    elapsed_seconds: float


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _has_forbidden_token(path: Path) -> bool:
    normalized = _norm(path)
    return any(
        token.replace("\\", "/") in normalized for token in FORBIDDEN_PATH_TOKENS
    )


def guard_source_duckdb(path: Path) -> None:
    normalized = _norm(path)
    if _has_forbidden_token(path):
        raise D2T19RepairError(f"forbidden source DuckDB path: {path}")
    if path.suffix.lower() != ".duckdb":
        raise D2T19RepairError(f"source must be a DuckDB file: {path}")
    if path.name != CANONICAL_DUCKDB_NAME:
        raise D2T19RepairError(f"source DuckDB must be named {CANONICAL_DUCKDB_NAME}")
    if "data/generated/d2/" not in normalized:
        raise D2T19RepairError("source DuckDB must be under data/generated/d2/")


def guard_d2_t18_dir(path: Path) -> None:
    normalized = _norm(path)
    if _has_forbidden_token(path):
        raise D2T19RepairError(f"forbidden D2-T18 diagnostics path: {path}")
    if "data/generated/d2/" not in normalized:
        raise D2T19RepairError(
            "D2-T18 diagnostics dir must be under data/generated/d2/"
        )


def guard_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if _has_forbidden_token(path):
        raise D2T19RepairError(f"forbidden output path: {path}")
    if ".duckdb" in normalized:
        raise D2T19RepairError("output-dir must not be a DuckDB path")
    if "data/generated/d2/" not in normalized:
        raise D2T19RepairError("output-dir must be under data/generated/d2/")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rows_as_dicts(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def build_repair_plan(d2_t18_dir: Path) -> list[D2T19RepairTask]:
    rows = _read_csv(d2_t18_dir / "d2_t18_targeted_repair_candidates.csv")
    tasks: list[D2T19RepairTask] = []
    for row in rows:
        endpoint = row["endpoint"]
        reason = row["reason"]
        if endpoint == "daily" and reason == "listed_open_missing_daily":
            param_strategy = "primary_ts_code_start_end_then_trade_date_fallback"
        elif endpoint == "stk_limit" and reason == "stk_limit_missing":
            param_strategy = (
                "primary_ts_code_start_end_then_date_range_fallback_filtered_to_ts_code"
            )
        else:
            continue
        payload = {
            "task_id": "D2-T19",
            "endpoint": endpoint,
            "ts_code": row["ts_code"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "reason": reason,
            "priority": row["priority"],
            "param_strategy": param_strategy,
        }
        task_hash = _task_hash(payload)
        tasks.append(
            D2T19RepairTask(
                repair_task_id=f"d2_t19:{endpoint}:{row['ts_code']}:{row['start_date']}:{row['end_date']}:{task_hash[:8]}",
                endpoint=endpoint,
                ts_code=row["ts_code"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                reason=reason,
                priority=row["priority"],
                source_gap_row_count=int(row.get("gap_row_count") or 0),
                param_strategy=param_strategy,
                task_hash=task_hash,
            )
        )
    return sorted(
        tasks,
        key=lambda task: (
            task.priority,
            task.endpoint,
            task.ts_code,
            task.start_date,
            task.end_date,
        ),
    )


def d2_t19_variants(task: D2T19RepairTask) -> list[ProviderCallVariant]:
    if task.endpoint == "daily":
        return [
            ProviderCallVariant(
                "ts_code_start_end",
                {
                    "ts_code": task.ts_code,
                    "start_date": task.start_date,
                    "end_date": task.end_date,
                },
            )
        ]
    if task.endpoint == "stk_limit":
        return [
            ProviderCallVariant(
                "ts_code_start_end",
                {
                    "ts_code": task.ts_code,
                    "start_date": task.start_date,
                    "end_date": task.end_date,
                },
            ),
            ProviderCallVariant(
                "date_range_fallback_filtered_to_ts_code",
                {"start_date": task.start_date, "end_date": task.end_date},
            ),
        ]
    raise D2T19RepairError(f"unsupported repair endpoint: {task.endpoint}")


def load_task_gap_dates(
    conn: duckdb.DuckDBPyConnection, task: D2T19RepairTask
) -> list[str]:
    rows = conn.execute(
        """
        SELECT trade_date
        FROM d2_coverage_gaps
        WHERE ts_code = ?
          AND gap_type = ?
          AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        [task.ts_code, task.reason, task.start_date, task.end_date],
    ).fetchall()
    return [str(row[0]) for row in rows]


def d2_t19_variants_for_dates(
    task: D2T19RepairTask, target_dates: list[str]
) -> list[ProviderCallVariant]:
    variants = d2_t19_variants(task)
    if task.endpoint == "daily":
        return variants[:1] + [
            ProviderCallVariant(
                "trade_date_fallback_filtered_to_ts_code", {"trade_date": date}
            )
            for date in target_dates
        ]
    if task.endpoint == "stk_limit":
        return variants[:2] + [
            ProviderCallVariant(
                "trade_date_fallback_filtered_to_ts_code", {"trade_date": date}
            )
            for date in target_dates
        ]
    return variants


def to_security_major_task(task: D2T19RepairTask) -> SecurityMajorFetchTask:
    return SecurityMajorFetchTask(
        task_id=task.repair_task_id,
        endpoint=task.endpoint,
        ts_code=task.ts_code,
        start_date=task.start_date,
        end_date=task.end_date,
        param_variant=task.param_strategy,
        task_hash=task.task_hash,
    )


def copy_source_duckdb(source_duckdb: Path, output_dir: Path) -> Path:
    guard_source_duckdb(source_duckdb)
    guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / CANONICAL_DUCKDB_NAME
    if source_duckdb.resolve() == target.resolve():
        raise D2T19RepairError("output DuckDB must not be the source DuckDB")
    shutil.copy2(source_duckdb, target)
    return target


def count_remaining_gap(conn: duckdb.DuckDBPyConnection, task: D2T19RepairTask) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM d2_coverage_gaps
        WHERE ts_code = ?
          AND gap_type = ?
          AND trade_date BETWEEN ? AND ?
        """,
        [task.ts_code, task.reason, task.start_date, task.end_date],
    ).fetchone()
    return int(row[0] or 0)


def fetch_and_write_repair_task(
    *,
    client: Any,
    writer: DuckDBStagingWriter,
    task: D2T19RepairTask,
    run_id: str,
    limiter: AdaptiveRequestLimiter,
    retry_max_attempts: int,
    retry_backoff_seconds: float,
    retry_jitter_ratio: float,
    sleeper: Any = time.sleep,
) -> D2T19LedgerEntry:
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    before = count_remaining_gap(writer.conn, task)
    security_task = to_security_major_task(task)
    variants = d2_t19_variants_for_dates(task, load_task_gap_dates(writer.conn, task))
    method = getattr(client, task.endpoint)
    attempt_count = 0
    all_rows: list[dict[str, Any]] = []
    row_count = 0
    accepted_count = 0
    last_variant = variants[0].param_variant
    last_error: Exception | None = None
    last_category: str | None = None
    unsupported_seen = False

    for variant in variants:
        last_variant = variant.param_variant
        for attempt in range(1, retry_max_attempts + 1):
            attempt_count += 1
            limiter.acquire()
            try:
                payload = method(**variant.params)
                rows = _frame_records(payload)
                accepted, _filtered = validate_and_filter_rows(
                    task.endpoint, rows, security_task
                )
                row_count += len(rows)
                if accepted:
                    all_rows.extend(accepted)
                    accepted_count += len(accepted)
                limiter.record_result(None)
                break
            except Exception as exc:
                last_error = exc
                last_category = _classify_error(exc)
                limiter.record_result(last_category)
                if last_category == "unsupported_param_variant":
                    unsupported_seen = True
                    break
                if (
                    last_category in {"rate_limit", "timeout", "provider_error"}
                    and attempt < retry_max_attempts
                ):
                    sleeper(
                        retry_backoff_seconds
                        * (2 ** (attempt - 1))
                        * (1 + retry_jitter_ratio)
                    )
                    continue
                return _ledger_from_result(
                    run_id=run_id,
                    task=task,
                    param_variant=variant.param_variant,
                    status=last_category or "failed",
                    attempt_count=attempt_count,
                    row_count=row_count,
                    accepted_row_count=accepted_count,
                    target_gap_row_count=before,
                    remaining_gap_row_count_after_write=before,
                    error_category=last_category or "failed",
                    error_message_redacted=_redact_error(exc),
                    started_at=started_at,
                    elapsed_seconds=time.monotonic() - started_monotonic,
                )
        if all_rows and accepted_count >= before:
            break

    if all_rows:
        writer.write_endpoint_task_rows(task.endpoint, security_task, all_rows)
        compute_quality_gate(writer.conn)
        after = count_remaining_gap(writer.conn, task)
        status = (
            "succeeded_after_fallback"
            if unsupported_seen or last_variant != "ts_code_start_end"
            else "succeeded"
        )
        return _ledger_from_result(
            run_id=run_id,
            task=task,
            param_variant=last_variant,
            status=status,
            attempt_count=attempt_count,
            row_count=row_count,
            accepted_row_count=len(all_rows),
            target_gap_row_count=before,
            remaining_gap_row_count_after_write=after,
            error_category=None,
            error_message_redacted=None,
            started_at=started_at,
            elapsed_seconds=time.monotonic() - started_monotonic,
        )

    status = "empty_after_all_variants"
    empty_error_category = (
        "provider_stk_limit_unavailable" if task.endpoint == "stk_limit" else None
    )
    if unsupported_seen and last_category == "unsupported_param_variant":
        status = "unsupported_param_variant"
    return _ledger_from_result(
        run_id=run_id,
        task=task,
        param_variant=last_variant,
        status=status,
        attempt_count=attempt_count,
        row_count=row_count,
        accepted_row_count=0,
        target_gap_row_count=before,
        remaining_gap_row_count_after_write=before,
        error_category=empty_error_category
        if status == "empty_after_all_variants"
        else last_category,
        error_message_redacted=_redact_error(last_error) if last_error else None,
        started_at=started_at,
        elapsed_seconds=time.monotonic() - started_monotonic,
    )


def _ledger_from_result(
    *,
    run_id: str,
    task: D2T19RepairTask,
    param_variant: str,
    status: str,
    attempt_count: int,
    row_count: int,
    accepted_row_count: int,
    target_gap_row_count: int,
    remaining_gap_row_count_after_write: int,
    error_category: str | None,
    error_message_redacted: str | None,
    started_at: str,
    elapsed_seconds: float,
) -> D2T19LedgerEntry:
    covered = max(0, target_gap_row_count - remaining_gap_row_count_after_write)
    return D2T19LedgerEntry(
        run_id=run_id,
        repair_task_id=task.repair_task_id,
        endpoint=task.endpoint,
        ts_code=task.ts_code,
        start_date=task.start_date,
        end_date=task.end_date,
        reason=task.reason,
        priority=task.priority,
        param_variant=param_variant,
        status=status,
        attempt_count=attempt_count,
        row_count=row_count,
        accepted_row_count=accepted_row_count,
        target_gap_row_count=target_gap_row_count,
        covered_gap_row_count_after_write=covered,
        remaining_gap_row_count_after_write=remaining_gap_row_count_after_write,
        error_category=error_category,
        error_message_redacted=error_message_redacted,
        started_at=started_at,
        completed_at=_utc_now(),
        elapsed_seconds=round(elapsed_seconds, 3),
    )


def quality_report(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    quality = compute_quality_gate(conn)
    return {"task_id": "D2-T19", "quality": quality}


def capped_acceptance_reports(
    quality: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    acceptance, handoff = build_acceptance_reports(quality)
    acceptance["task_id"] = "D2-T19"
    acceptance["source_task_id"] = "D2-T15"
    if acceptance["d2_acceptance_decision"] == "accepted_for_d3_candidate_generation":
        acceptance["underlying_quality_decision"] = acceptance["d2_acceptance_decision"]
        acceptance["d2_acceptance_decision"] = (
            "blocked_pending_d2_t20_acceptance_review"
        )
        acceptance.setdefault("quality_blockers", []).append(
            "d2_t19_does_not_authorize_acceptance"
        )
    handoff["task_id"] = "D2-T19"
    handoff["source_task_id"] = "D2-T15"
    handoff["d3_handoff_decision"] = "d3_candidate_generation_blocked"
    handoff["d3_generation_authorized"] = False
    handoff["r0_state_generated"] = False
    return acceptance, handoff


def repaired_gap_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    metrics = [
        "listed_open_missing_daily_count",
        "price_limit_daily_dependency_missing_count",
        "unresolved_adjustment_factor_count",
        "unresolved_price_limit_status_count",
        "daily_raw_row_count",
        "stk_limit_resolved_count",
        "adj_factor_resolved_count",
    ]
    return [
        {
            "metric": metric,
            "before_count": int(before.get(metric, 0)),
            "after_count": int(after.get(metric, 0)),
            "delta": int(after.get(metric, 0)) - int(before.get(metric, 0)),
        }
        for metric in metrics
    ]


def remaining_coverage_gaps(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return _rows_as_dicts(
        conn,
        """
        SELECT ts_code, trade_date, gap_type
        FROM d2_coverage_gaps
        ORDER BY gap_type, ts_code, trade_date
        """,
    )


def policy_evidence(
    conn: duckdb.DuckDBPyConnection,
    d2_t18_dir: Path,
    *,
    client: Any | None = None,
    allow_diagnostic_pro_bar: bool = False,
) -> list[dict[str, Any]]:
    candidates = _read_csv(d2_t18_dir / "d2_t18_gap_policy_candidates.csv")
    ts_codes = sorted(
        {
            row["ts_code"]
            for row in candidates
            if row.get("gap_type") == "unresolved_adjustment_factor"
        }
    )
    rows: list[dict[str, Any]] = []
    for ts_code in ts_codes:
        evidence = conn.execute(
            """
            SELECT
              b.list_date,
              b.delist_date,
              min(d.trade_date) AS first_daily_date,
              max(d.trade_date) AS last_daily_date,
              count(DISTINCT d.trade_date) AS daily_row_count,
              count(DISTINCT a.trade_date) AS adj_factor_row_count,
              min(a.trade_date) AS first_adj_factor_date,
              max(a.trade_date) AS last_adj_factor_date,
              (
                SELECT count(*)
                FROM d2_coverage_gaps g
                WHERE g.ts_code = ?
                  AND g.gap_type = 'unresolved_adjustment_factor'
              ) AS missing_adj_factor_gap_count
            FROM staging_stock_basic b
            LEFT JOIN staging_daily_raw d ON d.ts_code = b.ts_code
            LEFT JOIN staging_adj_factor a ON a.ts_code = b.ts_code
            WHERE b.ts_code = ?
            GROUP BY b.list_date, b.delist_date
            """,
            [ts_code, ts_code],
        ).fetchone()
        if not evidence:
            evidence = ("", "", "", "", 0, 0, "", "", 0)
        (
            list_date,
            delist_date,
            first_daily_date,
            last_daily_date,
            daily_row_count,
            adj_factor_row_count,
            first_adj_factor_date,
            last_adj_factor_date,
            missing_gap_count,
        ) = evidence
        diagnostic_pro_bar_available = False
        if (
            allow_diagnostic_pro_bar
            and client is not None
            and hasattr(client, "pro_bar")
        ):
            diagnostic_pro_bar_available = bool(
                _frame_records(
                    client.pro_bar(
                        ts_code=ts_code,
                        start_date=str(first_daily_date or list_date or ""),
                        end_date=str(last_daily_date or delist_date or ""),
                        adj="qfq",
                    )
                )
            )
        has_any_adj_factor = int(adj_factor_row_count or 0) > 0
        if not has_any_adj_factor and int(daily_row_count or 0) > 0:
            diagnosis = "listed_daily_exists_but_provider_adj_factor_absent"
            recommended_policy = "neutral_factor_1_policy_candidate"
        elif has_any_adj_factor and int(missing_gap_count or 0) > 0:
            diagnosis = "partial_adj_factor_coverage_requires_review"
            recommended_policy = "carry_forward_policy_candidate"
        elif diagnostic_pro_bar_available:
            diagnosis = "diagnostic_pro_bar_available_not_formal"
            recommended_policy = "manual_review_required"
        else:
            diagnosis = "policy_evidence_insufficient"
            recommended_policy = "keep_blocked"
        rows.append(
            {
                "ts_code": ts_code,
                "list_date": list_date or "",
                "delist_date": delist_date or "",
                "first_daily_date": first_daily_date or "",
                "last_daily_date": last_daily_date or "",
                "daily_row_count": int(daily_row_count or 0),
                "adj_factor_row_count": int(adj_factor_row_count or 0),
                "first_adj_factor_date": first_adj_factor_date or "",
                "last_adj_factor_date": last_adj_factor_date or "",
                "missing_adj_factor_gap_count": int(missing_gap_count or 0),
                "has_any_adj_factor": has_any_adj_factor,
                "nearest_provider_factor_evidence": (
                    first_adj_factor_date or last_adj_factor_date or ""
                ),
                "diagnostic_pro_bar_available": diagnostic_pro_bar_available,
                "diagnosis": diagnosis,
                "recommended_policy": recommended_policy,
            }
        )
    return rows


def write_policy_markdown(path: Path, evidence_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# D2-T19 coverage policy recommendations",
        "",
        "1. D2-T19 only records coverage policy evidence; "
        "it does not change D2 acceptance.",
    ]
    for row in evidence_rows:
        lines.append(
            f"2. `{row['ts_code']}` diagnosis: `{row['diagnosis']}`; "
            f"recommended_policy: `{row['recommended_policy']}`."
        )
    lines.append(
        "3. D3/R0 remain blocked until a later acceptance PR explicitly allows them."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_next_actions(
    path: Path,
    *,
    ledger_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    acceptance: dict[str, Any],
) -> None:
    statuses = Counter(row["status"] for row in ledger_rows)
    lines = [
        "# D2-T19 recommended next actions",
        "",
        f"1. Targeted repair statuses: `{dict(statuses)}`.",
        "2. Repaired gap deltas are recorded in `d2_t19_repaired_gap_delta.csv`.",
        "3. Remaining gaps are recorded in `d2_t19_remaining_coverage_gaps.csv`.",
        f"4. Policy evidence rows: `{len(evidence_rows)}`.",
        "5. D2-T20 should decide policy acceptance versus a second "
        "targeted repair pass.",
        f"6. Current acceptance candidate: `{acceptance['d2_acceptance_decision']}`.",
        "7. D3/R0 remain blocked.",
    ]
    for row in delta_rows:
        lines.append(
            f"- `{row['metric']}` before={row['before_count']} "
            f"after={row['after_count']} delta={row['delta']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_d2_t19_repair(
    *,
    source_duckdb: Path,
    d2_t18_dir: Path,
    output_dir: Path,
    env_file: Path | None = None,
    execute_provider_repair: bool = False,
    dry_run_plan: bool = False,
    no_remote_fetch: bool = False,
    max_workers: int = 2,
    initial_requests_per_minute: int = 50,
    max_requests_per_minute: int = 100,
    min_requests_per_minute: int = 20,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: float = 5.0,
    retry_jitter_ratio: float = 0.2,
    allow_diagnostic_pro_bar: bool = False,
    client: Any | None = None,
    sleeper: Any = time.sleep,
) -> dict[str, Any]:
    del max_workers
    guard_source_duckdb(source_duckdb)
    guard_d2_t18_dir(d2_t18_dir)
    guard_output_dir(output_dir)
    if execute_provider_repair and no_remote_fetch:
        raise D2T19RepairError(
            "--execute-provider-repair and --no-remote-fetch conflict"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_repair_plan(d2_t18_dir)
    _write_jsonl(output_dir / REPAIR_PLAN_FILE, [asdict(task) for task in plan])
    run_id = "D2-T19-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if dry_run_plan:
        summary = {
            "task_id": "D2-T19",
            "run_id": run_id,
            "dry_run_plan": True,
            "remote_provider_called": False,
            "repair_task_count": len(plan),
            "d3_generation_authorized": False,
            "r0_state_generated": False,
            "data_version_published": False,
        }
        _write_json(output_dir / "d2_t19_repair_run_summary.json", summary)
        return summary

    target_duckdb = copy_source_duckdb(source_duckdb, output_dir)
    conn = duckdb.connect(str(target_duckdb))
    before_quality = compute_quality_gate(conn)
    conn.close()
    ledger_entries: list[D2T19LedgerEntry] = []
    provider_called = False
    if execute_provider_repair:
        provider_called = True
        if client is None:
            client = create_tnskhdata_client(env_file)
        limiter = AdaptiveRequestLimiter(
            initial_requests_per_minute=initial_requests_per_minute,
            max_requests_per_minute=max_requests_per_minute,
            min_requests_per_minute=min_requests_per_minute,
        )
        writer = DuckDBStagingWriter(target_duckdb)
        try:
            for task in plan:
                ledger_entries.append(
                    fetch_and_write_repair_task(
                        client=client,
                        writer=writer,
                        task=task,
                        run_id=run_id,
                        limiter=limiter,
                        retry_max_attempts=retry_max_attempts,
                        retry_backoff_seconds=retry_backoff_seconds,
                        retry_jitter_ratio=retry_jitter_ratio,
                        sleeper=sleeper,
                    )
                )
            after_quality = compute_quality_gate(writer.conn)
            evidence_rows = policy_evidence(
                writer.conn,
                d2_t18_dir,
                client=client,
                allow_diagnostic_pro_bar=allow_diagnostic_pro_bar,
            )
        finally:
            writer.close()
    else:
        conn = duckdb.connect(str(target_duckdb))
        try:
            after_quality = compute_quality_gate(conn)
            evidence_rows = policy_evidence(conn, d2_t18_dir)
        finally:
            conn.close()

    conn = duckdb.connect(str(target_duckdb))
    try:
        remaining_rows = remaining_coverage_gaps(conn)
    finally:
        conn.close()

    ledger_rows = [asdict(entry) for entry in ledger_entries]
    delta_rows = repaired_gap_delta(before_quality, after_quality)
    conn = duckdb.connect(str(target_duckdb))
    try:
        quality_payload = quality_report(conn)
        quality_payload["quality"] = after_quality
    finally:
        conn.close()
    acceptance, handoff = capped_acceptance_reports(after_quality)
    _write_jsonl(output_dir / REPAIR_LEDGER_FILE, ledger_rows)
    _write_json(
        output_dir / "d2_t19_provider_error_summary.json",
        {
            "task_id": "D2-T19",
            "error_counts": dict(
                Counter(
                    row["error_category"]
                    for row in ledger_rows
                    if row.get("error_category")
                )
            ),
        },
    )
    _write_json(output_dir / "d2_t19_post_repair_quality_report.json", quality_payload)
    _write_json(
        output_dir / "d2_t19_post_repair_acceptance_candidate_report.json", acceptance
    )
    _write_json(
        output_dir / "d2_t19_post_repair_handoff_candidate_report.json", handoff
    )
    _write_csv(
        output_dir / "d2_t19_remaining_coverage_gaps.csv",
        remaining_rows,
        ["ts_code", "trade_date", "gap_type"],
    )
    _write_csv(
        output_dir / "d2_t19_repaired_gap_delta.csv",
        delta_rows,
        ["metric", "before_count", "after_count", "delta"],
    )
    _write_csv(
        output_dir / "d2_t19_policy_evidence.csv",
        evidence_rows,
        [
            "ts_code",
            "list_date",
            "delist_date",
            "first_daily_date",
            "last_daily_date",
            "daily_row_count",
            "adj_factor_row_count",
            "first_adj_factor_date",
            "last_adj_factor_date",
            "missing_adj_factor_gap_count",
            "has_any_adj_factor",
            "nearest_provider_factor_evidence",
            "diagnostic_pro_bar_available",
            "diagnosis",
            "recommended_policy",
        ],
    )
    write_policy_markdown(
        output_dir / "d2_t19_policy_recommendations.md", evidence_rows
    )
    write_next_actions(
        output_dir / "d2_t19_recommended_next_actions.md",
        ledger_rows=ledger_rows,
        delta_rows=delta_rows,
        evidence_rows=evidence_rows,
        acceptance=acceptance,
    )
    summary = {
        "task_id": "D2-T19",
        "run_id": run_id,
        "remote_provider_called": provider_called,
        "repair_task_count": len(plan),
        "repair_status_counts": dict(Counter(row["status"] for row in ledger_rows)),
        "policy_evidence_count": len(evidence_rows),
        "post_repair_acceptance_decision": acceptance["d2_acceptance_decision"],
        "d3_generation_authorized": False,
        "r0_state_generated": False,
        "pcvt_values_generated": False,
        "data_version_published": False,
    }
    _write_json(output_dir / "d2_t19_repair_run_summary.json", summary)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-duckdb", required=True, type=Path)
    parser.add_argument("--d2-t18-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--execute-provider-repair", action="store_true")
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--no-remote-fetch", action="store_true")
    parser.add_argument("--max-workers", default=2, type=int)
    parser.add_argument("--initial-requests-per-minute", default=50, type=int)
    parser.add_argument("--max-requests-per-minute", default=100, type=int)
    parser.add_argument("--min-requests-per-minute", default=20, type=int)
    parser.add_argument("--retry-max-attempts", default=3, type=int)
    parser.add_argument("--retry-backoff-seconds", default=5.0, type=float)
    parser.add_argument("--retry-jitter-ratio", default=0.2, type=float)
    parser.add_argument("--allow-diagnostic-pro-bar", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = run_d2_t19_repair(
        source_duckdb=args.source_duckdb,
        d2_t18_dir=args.d2_t18_dir,
        output_dir=args.output_dir,
        env_file=args.env_file,
        execute_provider_repair=args.execute_provider_repair,
        dry_run_plan=args.dry_run_plan,
        no_remote_fetch=args.no_remote_fetch,
        max_workers=args.max_workers,
        initial_requests_per_minute=args.initial_requests_per_minute,
        max_requests_per_minute=args.max_requests_per_minute,
        min_requests_per_minute=args.min_requests_per_minute,
        retry_max_attempts=args.retry_max_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
        retry_jitter_ratio=args.retry_jitter_ratio,
        allow_diagnostic_pro_bar=args.allow_diagnostic_pro_bar,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
