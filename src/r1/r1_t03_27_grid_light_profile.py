from __future__ import annotations

import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

TASK_ID = "R1-T03"
STATE_NAMES = ("S_P", "S_PC", "S_PCT", "S_PCVT")
EXPECTED_W = [120, 250, 500]
EXPECTED_Q = [0.1, 0.2, 0.3]
EXPECTED_K = [2, 3, 5]
BASELINE_CONFIG_ID = "R0_W250_Q20_K3_WEAK_D010"
FORBIDDEN_TOKENS = (
    "future_return",
    "future_volatility",
    "release_direction",
    "breakout_direction",
    "backtest",
    "portfolio",
    "trade_signal",
    "trading_signal",
    "jointlift",
    "empirical_p",
    "z_score",
    "r2_decision_matrix",
    "freeze_candidate",
    "review_candidate",
    "do_not_freeze",
    "best_config",
    "winner",
    "optimized_config",
)


@dataclass
class ProfileContext:
    root: Path
    checks: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def pass_check(self, key: str) -> None:
        self.checks[key] = "passed"

    def fail_check(self, key: str, message: str) -> None:
        self.checks[key] = "blocked"
        self.errors.append(f"{key}:{message}")

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")


def run_r1_t03_27_grid_light_profile(
    *,
    config_path: Path,
    r1_t02_evidence_path: Path,
    r1_t02_summary_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    max_workers: int = 3,
    root: Path = ROOT,
) -> dict[str, Any]:
    ctx = ProfileContext(root=root)
    config = _load_json(config_path, ctx, "config_json")
    _check_config(ctx, config, max_workers)
    evidence = _parse_evidence(r1_t02_evidence_path)
    r1_t02_summary = _load_json(r1_t02_summary_path, ctx, "r1_t02_summary_json")
    validation_path = _resolve_path(
        root,
        evidence.get("validation_result_path")
        or config.get("r1_t02_validation_result_path", ""),
    )
    validation_result = _load_json(
        validation_path, ctx, "r1_t02_validation_result_json"
    )
    _check_r1_t02_gate(
        ctx,
        evidence,
        r1_t02_evidence_path,
        r1_t02_summary,
        r1_t02_summary_path,
        validation_result,
        validation_path,
    )
    full_grid_path = _resolve_path(
        root,
        r1_t02_summary.get("full_grid_manifest_path")
        or config.get("r0_full_grid_manifest_path", ""),
    )
    full_grid = _load_json(full_grid_path, ctx, "full_grid_manifest_json")
    _check_full_grid_manifest(ctx, full_grid, full_grid_path, config)

    output_dir.mkdir(parents=True, exist_ok=True)
    profile_rows: list[dict[str, Any]] = []
    retention_rows: list[dict[str, Any]] = []
    blocked_configs: list[dict[str, str]] = []
    if not ctx.errors:
        per_config = _run_config_profiles(
            full_grid,
            root=root,
            max_workers=max_workers,
            duckdb_threads=config.get("parallelism", {}).get(
                "duckdb_threads_per_worker", 1
            ),
        )
        for item in per_config:
            if item.get("status") != "completed":
                blocked_configs.append(
                    {
                        "candidate_config_id": str(item.get("candidate_config_id")),
                        "blocked_reason": str(item.get("blocked_reason")),
                    }
                )
                continue
            profile_rows.extend(item["profile_rows"])
            retention_rows.append(item["retention_profile"])
        if blocked_configs:
            ctx.fail_check("per_config_profile", "blocked_configs_present")
        else:
            ctx.pass_check("per_config_profile")

    relative_rows = _build_relative_to_baseline(profile_rows)
    _write_csv(output_dir / "r1_t03_light_profile_by_config_state.csv", profile_rows)
    _write_json(output_dir / "r1_t03_light_profile_by_config_state.json", profile_rows)
    _write_json(output_dir / "r1_t03_retention_profile_by_config.json", retention_rows)
    _write_json(output_dir / "r1_t03_relative_to_baseline_profile.json", relative_rows)

    output_paths = {
        "profile_by_config_state_csv": output_dir
        / "r1_t03_light_profile_by_config_state.csv",
        "profile_by_config_state_json": output_dir
        / "r1_t03_light_profile_by_config_state.json",
        "retention_profile": output_dir / "r1_t03_retention_profile_by_config.json",
        "relative_to_baseline_profile": output_dir
        / "r1_t03_relative_to_baseline_profile.json",
    }
    status = "completed" if not ctx.errors else "blocked"
    summary_path = output_dir / "r1_t03_27_grid_light_profile_summary.json"
    confirmed_interval_total = r1_t02_summary.get("counts", {}).get(
        "confirmed_interval_row_count_total"
    )
    summary = {
        "task_id": TASK_ID,
        "status": status,
        "run_id": run_id,
        "summary_path": ctx.relative(summary_path),
        "code_commit": code_commit,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_path": ctx.relative(config_path),
        "config_sha256": sha256_file(config_path) if config_path.exists() else None,
        "input_r1_t02_evidence_path": ctx.relative(r1_t02_evidence_path),
        "input_r1_t02_evidence_sha256": sha256_file(r1_t02_evidence_path)
        if r1_t02_evidence_path.exists()
        else None,
        "input_r1_t02_summary_path": ctx.relative(r1_t02_summary_path),
        "input_r1_t02_summary_sha256": sha256_file(r1_t02_summary_path)
        if r1_t02_summary_path.exists()
        else None,
        "input_r1_t02_validation_result_path": ctx.relative(validation_path),
        "input_r1_t02_validation_result_sha256": sha256_file(validation_path)
        if validation_path.exists()
        else None,
        "input_full_grid_manifest_path": ctx.relative(full_grid_path),
        "input_full_grid_manifest_sha256": sha256_file(full_grid_path)
        if full_grid_path.exists()
        else None,
        "max_workers": max_workers,
        "duckdb_threads_per_worker": config.get("parallelism", {}).get(
            "duckdb_threads_per_worker", 1
        ),
        "candidate_config_count": len(
            {row["candidate_config_id"] for row in profile_rows}
        ),
        "state_name_count": len({row["state_name"] for row in profile_rows}),
        "profile_row_count": len(profile_rows),
        "blocked_config_count": len(blocked_configs),
        "blocked_configs": blocked_configs,
        "confirmed_interval_row_count_total": confirmed_interval_total,
        "confirmed_interval_input_status": (
            "zero_confirmed_input_fact"
            if confirmed_interval_total == 0
            else "nonzero_confirmed_input_fact"
        ),
        "zero_confirmed_interval_acknowledged": r1_t02_summary.get("counts", {}).get(
            "confirmed_interval_row_count_total"
        )
        == 0,
        "output_paths": {
            key: {
                "path": ctx.relative(path),
                "sha256": sha256_file(path) if path.exists() else None,
            }
            for key, path in output_paths.items()
        },
        "checks": ctx.checks,
        "warnings": ctx.warnings,
        "blocked_reasons": ctx.errors,
        "row_payload_embedded": False,
        "downstream_gates": {
            "R1-T04_allowed_to_start": status == "completed",
            "R1-T07_allowed_to_start": False,
            "R2_allowed_to_start": False,
        },
    }
    _write_json(summary_path, summary)
    return summary


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_config_profiles(
    full_grid: dict[str, Any], *, root: Path, max_workers: int, duckdb_threads: int
) -> list[dict[str, Any]]:
    artifacts = full_grid.get("artifacts_by_config", {})
    candidates = {
        item["candidate_config_id"]: item
        for item in full_grid.get("candidate_configs", [])
    }
    tasks = [
        {
            "candidate": candidates[config_id],
            "artifact": artifacts[config_id],
            "root": str(root),
            "duckdb_threads": duckdb_threads,
        }
        for config_id in sorted(artifacts)
    ]
    if max_workers == 1:
        return [_profile_one_config(task) for task in tasks]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_profile_one_config, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: str(item.get("candidate_config_id")))


def _profile_one_config(task: dict[str, Any]) -> dict[str, Any]:
    try:
        import duckdb

        candidate = task["candidate"]
        artifact = task["artifact"]
        root = Path(task["root"])
        config_id = candidate["candidate_config_id"]
        daily_path = _artifact_path(
            root, artifact, "daily_parquet_path", "daily_duckdb_path"
        )
        interval_path = _artifact_path(
            root, artifact, "interval_parquet_path", "interval_duckdb_path"
        )
        con = duckdb.connect()
        con.execute(f"PRAGMA threads={int(task['duckdb_threads'])}")
        daily_source = _duckdb_source(daily_path)
        interval_source = _duckdb_source(interval_path)
        profile_rows = _daily_profile_rows(con, daily_source, candidate)
        segment_rows = _raw_segment_rows(con, daily_source)
        interval_rows = _interval_rows(con, interval_source)
        _merge_segment_and_interval(profile_rows, segment_rows, interval_rows)
        retention_profile = _retention_profile(config_id, profile_rows)
        con.close()
        return {
            "status": "completed",
            "candidate_config_id": config_id,
            "profile_rows": profile_rows,
            "retention_profile": retention_profile,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "blocked",
            "candidate_config_id": task.get("candidate", {}).get(
                "candidate_config_id", "unknown"
            ),
            "blocked_reason": str(exc),
        }


def _daily_profile_rows(
    con: Any, source_sql: str, candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    query = f"""
    WITH base AS (
      SELECT
        state_name,
        security_id,
        trading_date,
        raw_state,
        confirmed_state,
        lower(coalesce(validity_status, '')) AS validity_status,
        substr(trading_date, 1, 4) AS year
      FROM {source_sql}
    ),
    year_base AS (
      SELECT COUNT(DISTINCT year) AS total_years FROM base
    )
    SELECT
      b.state_name,
      COUNT(*) AS eligible_day_count,
      SUM(CASE WHEN validity_status = 'valid' THEN 1 ELSE 0 END) AS valid_day_count,
      SUM(CASE WHEN validity_status = 'unknown' THEN 1 ELSE 0 END) AS unknown_day_count,
      SUM(CASE WHEN validity_status = 'blocked' THEN 1 ELSE 0 END) AS blocked_day_count,
      SUM(CASE
        WHEN validity_status = 'diagnostic_required' THEN 1 ELSE 0
      END) AS diagnostic_required_day_count,
      SUM(CASE WHEN raw_state IS TRUE THEN 1 ELSE 0 END) AS raw_state_true_day_count,
      SUM(CASE WHEN raw_state IS FALSE THEN 1 ELSE 0 END) AS raw_state_false_day_count,
      SUM(CASE WHEN raw_state IS NULL THEN 1 ELSE 0 END) AS raw_state_null_day_count,
      SUM(CASE
        WHEN confirmed_state IS TRUE THEN 1 ELSE 0
      END) AS confirmed_state_true_day_count,
      SUM(CASE
        WHEN confirmed_state IS FALSE THEN 1 ELSE 0
      END) AS confirmed_state_false_day_count,
      SUM(CASE
        WHEN confirmed_state IS NULL THEN 1 ELSE 0
      END) AS confirmed_state_null_day_count,
      COUNT(DISTINCT CASE
        WHEN raw_state IS TRUE THEN security_id
      END) AS unique_security_count_raw_true,
      COUNT(DISTINCT CASE
        WHEN confirmed_state IS TRUE THEN security_id
      END) AS unique_security_count_confirmed_true,
      COUNT(DISTINCT CASE
        WHEN raw_state IS TRUE THEN year
      END) AS nonzero_year_count_raw,
      COUNT(DISTINCT CASE
        WHEN confirmed_state IS TRUE THEN year
      END) AS nonzero_year_count_confirmed,
      max(y.total_years) AS total_year_count
    FROM base b CROSS JOIN year_base y
    GROUP BY b.state_name
    ORDER BY b.state_name
    """
    rows = []
    for item in con.execute(query).fetchall():
        row = _daily_tuple_to_row(item, candidate)
        rows.append(row)
    by_state = {row["state_name"]: row for row in rows}
    return [
        by_state.get(state) or _empty_state_row(candidate, state)
        for state in STATE_NAMES
    ]


def _daily_tuple_to_row(
    item: tuple[Any, ...], candidate: dict[str, Any]
) -> dict[str, Any]:
    keys = (
        "state_name",
        "eligible_day_count",
        "valid_day_count",
        "unknown_day_count",
        "blocked_day_count",
        "diagnostic_required_day_count",
        "raw_state_true_day_count",
        "raw_state_false_day_count",
        "raw_state_null_day_count",
        "confirmed_state_true_day_count",
        "confirmed_state_false_day_count",
        "confirmed_state_null_day_count",
        "unique_security_count_raw_true",
        "unique_security_count_confirmed_true",
        "nonzero_year_count_raw",
        "nonzero_year_count_confirmed",
        "total_year_count",
    )
    row = dict(zip(keys, item, strict=True))
    row.update(_candidate_fields(candidate))
    _finalize_daily_ratios(row)
    return row


def _empty_state_row(candidate: dict[str, Any], state: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "state_name": state,
        "eligible_day_count": 0,
        "valid_day_count": 0,
        "unknown_day_count": 0,
        "blocked_day_count": 0,
        "diagnostic_required_day_count": 0,
        "raw_state_true_day_count": 0,
        "raw_state_false_day_count": 0,
        "raw_state_null_day_count": 0,
        "confirmed_state_true_day_count": 0,
        "confirmed_state_false_day_count": 0,
        "confirmed_state_null_day_count": 0,
        "unique_security_count_raw_true": 0,
        "unique_security_count_confirmed_true": 0,
        "nonzero_year_count_raw": 0,
        "nonzero_year_count_confirmed": 0,
        "total_year_count": 0,
    }
    row.update(_candidate_fields(candidate))
    _finalize_daily_ratios(row)
    return row


def _candidate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_config_id": candidate["candidate_config_id"],
        "W": candidate["percentile_window_W"],
        "q": candidate["low_quantile_q"],
        "K": candidate["confirmation_days_K"],
    }


def _finalize_daily_ratios(row: dict[str, Any]) -> None:
    eligible = row["eligible_day_count"]
    total_years = row.pop("total_year_count")
    row["raw_coverage"] = _safe_div(row["raw_state_true_day_count"], eligible)
    row["confirmed_coverage"] = _safe_div(
        row["confirmed_state_true_day_count"], eligible
    )
    row["year_coverage_raw"] = _safe_div(row["nonzero_year_count_raw"], total_years)
    row["year_coverage_confirmed"] = _safe_div(
        row["nonzero_year_count_confirmed"], total_years
    )
    row["unknown_ratio"] = _safe_div(row["unknown_day_count"], eligible)
    row["blocked_ratio"] = _safe_div(row["blocked_day_count"], eligible)
    row["diagnostic_required_ratio"] = _safe_div(
        row["diagnostic_required_day_count"], eligible
    )


def _raw_segment_rows(con: Any, source_sql: str) -> dict[str, dict[str, Any]]:
    query = f"""
    WITH ordered AS (
      SELECT
        state_name,
        security_id,
        trading_date,
        raw_state,
        lag(coalesce(raw_state, false)) OVER (
          PARTITION BY state_name, security_id ORDER BY trading_date
        ) AS previous_raw_state
      FROM {source_sql}
    )
    SELECT
      state_name,
      SUM(CASE
        WHEN raw_state IS TRUE
          AND coalesce(previous_raw_state, false) IS FALSE
        THEN 1 ELSE 0
      END) AS raw_segment_count
    FROM ordered
    GROUP BY state_name
    """
    return {
        state: {"raw_segment_count": int(count or 0)}
        for state, count in con.execute(query).fetchall()
    }


def _interval_rows(con: Any, source_sql: str) -> dict[str, dict[str, Any]]:
    count = con.execute(f"SELECT COUNT(*) FROM {source_sql}").fetchone()[0]
    if count == 0:
        return {
            state: {
                "confirmed_interval_count": 0,
                "confirmed_interval_total_days": 0,
                "confirmed_interval_average_duration": None,
                "unique_security_count_confirmed_interval": 0,
                "nonzero_year_count_confirmed_interval": 0,
                "confirmed_interval_status": "zero_confirmed_input_fact",
            }
            for state in STATE_NAMES
        }
    query = f"""
    SELECT
      state_level AS state_name,
      COUNT(*) AS confirmed_interval_count,
      SUM(confirmed_length) AS confirmed_interval_total_days,
      AVG(confirmed_length) AS confirmed_interval_average_duration,
      COUNT(DISTINCT security_id) AS unique_security_count_confirmed_interval,
      COUNT(DISTINCT substr(confirmation_time, 1, 4))
        AS nonzero_year_count_confirmed_interval
    FROM {source_sql}
    GROUP BY state_level
    """
    rows = {}
    for row in con.execute(query).fetchall():
        state = row[0]
        rows[state] = {
            "confirmed_interval_count": row[1],
            "confirmed_interval_total_days": row[2],
            "confirmed_interval_average_duration": row[3],
            "unique_security_count_confirmed_interval": row[4],
            "nonzero_year_count_confirmed_interval": row[5],
            "confirmed_interval_status": "computed",
        }
    for state in STATE_NAMES:
        rows.setdefault(
            state,
            {
                "confirmed_interval_count": 0,
                "confirmed_interval_total_days": 0,
                "confirmed_interval_average_duration": None,
                "unique_security_count_confirmed_interval": 0,
                "nonzero_year_count_confirmed_interval": 0,
                "confirmed_interval_status": "no_confirmed_interval_for_state",
            },
        )
    return rows


def _merge_segment_and_interval(
    profile_rows: list[dict[str, Any]],
    segment_rows: dict[str, dict[str, Any]],
    interval_rows: dict[str, dict[str, Any]],
) -> None:
    for row in profile_rows:
        segment = segment_rows.get(row["state_name"], {"raw_segment_count": 0})
        row["raw_segment_count"] = segment["raw_segment_count"]
        row["raw_fragment_rate"] = _safe_div(
            row["raw_segment_count"], row["raw_state_true_day_count"]
        )
        row["raw_average_duration"] = _safe_div(
            row["raw_state_true_day_count"], row["raw_segment_count"]
        )
        row["raw_fragment_denominator_zero"] = row["raw_state_true_day_count"] == 0
        row["raw_duration_denominator_zero"] = row["raw_segment_count"] == 0
        row.update(interval_rows.get(row["state_name"], {}))


def _retention_profile(config_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_state = {row["state_name"]: row for row in rows}
    result = {"candidate_config_id": config_id}
    pairs = (
        ("C_given_P_raw", "S_PC", "S_P", "raw_state_true_day_count"),
        ("T_given_PC_raw", "S_PCT", "S_PC", "raw_state_true_day_count"),
        ("V_given_PCT_raw", "S_PCVT", "S_PCT", "raw_state_true_day_count"),
        ("C_given_P_confirmed", "S_PC", "S_P", "confirmed_state_true_day_count"),
        (
            "T_given_PC_confirmed",
            "S_PCT",
            "S_PC",
            "confirmed_state_true_day_count",
        ),
        (
            "V_given_PCT_confirmed",
            "S_PCVT",
            "S_PCT",
            "confirmed_state_true_day_count",
        ),
    )
    for name, numerator_state, denominator_state, count_field in pairs:
        numerator = by_state[numerator_state][count_field]
        denominator = by_state[denominator_state][count_field]
        result[name] = _safe_div(numerator, denominator)
        result[f"{name}_denominator_zero"] = denominator == 0
    return result


def _build_relative_to_baseline(
    profile_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics = (
        "raw_coverage",
        "confirmed_coverage",
        "raw_fragment_rate",
        "unknown_ratio",
        "blocked_ratio",
    )
    baseline = {
        (row["state_name"], metric): row.get(metric)
        for row in profile_rows
        if row["candidate_config_id"] == BASELINE_CONFIG_ID
        for metric in metrics
    }
    rows = []
    for row in profile_rows:
        out = {
            "candidate_config_id": row["candidate_config_id"],
            "state_name": row["state_name"],
        }
        for metric in metrics:
            base_value = baseline.get((row["state_name"], metric))
            value = row.get(metric)
            out[f"{metric}_delta_to_baseline"] = (
                None if value is None or base_value is None else value - base_value
            )
            out[f"{metric}_ratio_to_baseline"] = (
                None if value is None or base_value in (None, 0) else value / base_value
            )
        rows.append(out)
    return rows


def _safe_div(
    numerator: int | float | None, denominator: int | float | None
) -> float | None:
    if denominator in (None, 0) or numerator is None:
        return None
    return float(numerator) / float(denominator)


def _artifact_path(
    root: Path, artifact: dict[str, Any], parquet_key: str, duckdb_key: str
) -> Path:
    if artifact.get(parquet_key):
        return root / artifact[parquet_key]
    return root / artifact[duckdb_key]


def _duckdb_source(path: Path) -> str:
    safe = str(path).replace("\\", "/").replace("'", "''")
    if path.suffix == ".parquet":
        return f"read_parquet('{safe}')"
    return f"read_parquet('{safe}')"


def _load_json(path: Path, ctx: ProfileContext, check_key: str) -> dict[str, Any]:
    if not path.exists():
        ctx.fail_check(check_key, f"missing:{ctx.relative(path)}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        ctx.fail_check(check_key, str(exc))
        return {}
    if not isinstance(payload, dict):
        ctx.fail_check(check_key, "top_level_not_object")
        return {}
    ctx.pass_check(check_key)
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _parse_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        key = line[1:key_end].strip()
        value = line[key_end + 2 :].strip().replace("`", "")
        fields.setdefault(key, value)
    return fields


def _resolve_path(root: Path, text: str | Any) -> Path:
    return (root / str(text)).resolve()


def _check_config(
    ctx: ProfileContext, config: dict[str, Any], max_workers: int
) -> None:
    parallelism = config.get("parallelism", {})
    if max_workers < 1 or max_workers > 3:
        ctx.fail_check("parallelism_contract", "max_workers_out_of_range")
    elif parallelism.get("max_workers", 0) > 3:
        ctx.fail_check("parallelism_contract", "config_max_workers_gt_3")
    elif parallelism.get("duckdb_threads_per_worker") != 1:
        ctx.fail_check("parallelism_contract", "duckdb_threads_not_1")
    elif config.get("state_names") != list(STATE_NAMES):
        ctx.fail_check("config_contract", "state_names_mismatch")
    elif config.get("grid", {}).get("K") != EXPECTED_K:
        ctx.fail_check("config_contract", "K_grid_mismatch")
    else:
        ctx.pass_check("parallelism_contract")
        ctx.pass_check("config_contract")


def _check_r1_t02_gate(
    ctx: ProfileContext,
    evidence: dict[str, str],
    evidence_path: Path,
    summary: dict[str, Any],
    summary_path: Path,
    validation: dict[str, Any],
    validation_path: Path,
) -> None:
    if not evidence:
        ctx.fail_check("r1_t02_gate", "missing_evidence")
        return
    expected = {
        "task_id": "R1-T02",
        "status": "completed",
        "validator_status": "passed",
        "R1-T03_allowed_to_start": "true",
        "R1-T07_allowed_to_start": "false",
        "R2_allowed_to_start": "false",
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            ctx.fail_check("r1_t02_gate", f"{key}_mismatch")
            return
    if evidence.get("summary_path") != ctx.relative(summary_path):
        ctx.fail_check("r1_t02_gate", "summary_path_mismatch")
        return
    if evidence.get("summary_sha256") != sha256_file(summary_path):
        ctx.fail_check("r1_t02_gate", "summary_hash_mismatch")
        return
    if evidence.get("validation_result_path") != ctx.relative(validation_path):
        ctx.fail_check("r1_t02_gate", "validation_path_mismatch")
        return
    if evidence.get("validation_result_sha256") != sha256_file(validation_path):
        ctx.fail_check("r1_t02_gate", "validation_hash_mismatch")
        return
    if validation.get("validator_status") != "passed":
        ctx.fail_check("r1_t02_gate", "validation_not_passed")
        return
    if summary.get("status") != "completed":
        ctx.fail_check("r1_t02_gate", "summary_not_completed")
        return
    if sha256_file(evidence_path) is None:
        ctx.fail_check("r1_t02_gate", "unreachable")
        return
    ctx.pass_check("r1_t02_gate")


def _check_full_grid_manifest(
    ctx: ProfileContext, manifest: dict[str, Any], path: Path, config: dict[str, Any]
) -> None:
    errors: list[str] = []
    if manifest.get("manifest_type") != "r0_t10_05_full_grid_manifest":
        errors.append("manifest_type")
    if manifest.get("status") != "completed":
        errors.append("status")
    if manifest.get("row_payload_embedded") is not False:
        errors.append("row_payload")
    if manifest.get("selected_config_count") != 27:
        errors.append("selected_config_count")
    if (
        manifest.get("completed_config_count") != 27
        or manifest.get("failed_config_count") != 0
    ):
        errors.append("completion")
    if manifest.get("baseline_config_id") != BASELINE_CONFIG_ID:
        errors.append("baseline")
    candidates = manifest.get("candidate_configs", [])
    artifacts = manifest.get("artifacts_by_config", {})
    if len(candidates) != 27 or set(
        item["candidate_config_id"] for item in candidates
    ) != set(artifacts):
        errors.append("candidate_artifact_set")
    if _grid_values(candidates, "percentile_window_W") != EXPECTED_W:
        errors.append("W")
    if _grid_values(candidates, "low_quantile_q") != EXPECTED_Q:
        errors.append("q")
    if _grid_values(candidates, "confirmation_days_K") != EXPECTED_K:
        errors.append("K")
    if config.get("r0_full_grid_manifest_sha256") != sha256_file(path):
        errors.append("hash")
    forbidden = _find_forbidden_tokens(manifest)
    if forbidden:
        errors.append("forbidden:" + ",".join(sorted(forbidden)))
    if errors:
        ctx.fail_check("full_grid_manifest_contract", ",".join(errors))
    else:
        ctx.pass_check("full_grid_manifest_contract")


def _grid_values(candidates: list[dict[str, Any]], key: str) -> list[Any]:
    return sorted({item.get(key) for item in candidates})


def _find_forbidden_tokens(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            text = str(key).lower()
            for token in FORBIDDEN_TOKENS:
                if token in text:
                    found.add(token)
            found.update(_find_forbidden_tokens(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_tokens(item))
    elif isinstance(value, str):
        text = value.lower()
        for token in FORBIDDEN_TOKENS:
            if token in text:
                found.add(token)
    return found
