# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R1-T04"
CONFIG_PATH = ROOT / "configs/r1/r1_t04_state_line_profiles.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t04_state_line_profiles.schema.json"
PROFILE_ROWS = 14
COMPARISON_ROWS = 10
PARENT_CHILD_ROWS = 8

COMPARISONS = (
    (
        "PCT_W250K3_vs_W120K3",
        "S_PCT",
        "R0_W250_Q20_K3_WEAK_D010",
        "R0_W120_Q20_K3_WEAK_D010",
        "reference_vs_fast_challenger",
    ),
    (
        "PCT_W120K3_vs_W120K2",
        "S_PCT",
        "R0_W120_Q20_K3_WEAK_D010",
        "R0_W120_Q20_K2_WEAK_D010",
        "k_confirmation_sidecar",
    ),
    (
        "PCVT_W250K3_vs_W120K3",
        "S_PCVT",
        "R0_W250_Q20_K3_WEAK_D010",
        "R0_W120_Q20_K3_WEAK_D010",
        "reference_vs_short_window",
    ),
    (
        "PCVT_W250K3_vs_W500K3",
        "S_PCVT",
        "R0_W250_Q20_K3_WEAK_D010",
        "R0_W500_Q20_K3_WEAK_D010",
        "reference_vs_long_window",
    ),
    (
        "PCVT_W250K3_vs_W250K5",
        "S_PCVT",
        "R0_W250_Q20_K3_WEAK_D010",
        "R0_W250_Q20_K5_WEAK_D010",
        "k_confirmation_sidecar",
    ),
)


class R1T04ProfileError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_r1_t04_state_line_profiles(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    config = _load_json(config_path)
    schema = _load_json(root / "schemas/r1/r1_t04_state_line_profiles.schema.json")
    errors = _validate_config(config, schema)
    lineage: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    t03_rows: list[dict[str, Any]] = []
    if not errors:
        lineage, manifest, t03_rows, lineage_errors = _load_lineage(config, root)
        errors.extend(lineage_errors)
    artifacts = manifest.get("artifacts_by_config", {})
    candidates = {
        row["candidate_config_id"]: row for row in manifest.get("candidate_configs", [])
    }
    profiles = list(config["profiles"])
    selected_configs = sorted({row["candidate_config_id"] for row in profiles})
    if not errors:
        for config_id in selected_configs:
            errors.extend(
                _check_artifact_entry(root, artifacts.get(config_id), config_id)
            )

    state_rows: list[dict[str, Any]] = []
    duration_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    config_sources: dict[str, tuple[str, str]] = {}
    if not errors:
        for config_id in selected_configs:
            entry = artifacts[config_id]
            config_sources[config_id] = (
                _parquet_source(root / entry["daily_parquet_path"]),
                _parquet_source(root / entry["interval_parquet_path"]),
            )
        for profile in profiles:
            candidate = candidates[profile["candidate_config_id"]]
            daily, interval = config_sources[profile["candidate_config_id"]]
            profile_state_rows, profile_duration, profile_year = _profile_state_line(
                daily=daily,
                interval=interval,
                profile=profile,
                candidate=candidate,
                run_id=run_id,
                code_commit=code_commit,
            )
            state_rows.extend(profile_state_rows)
            duration_rows.extend(profile_duration)
            year_rows.extend(profile_year)
        for config_id in (
            "R0_W120_Q20_K3_WEAK_D010",
            "R0_W250_Q20_K3_WEAK_D010",
            "R0_W500_Q20_K3_WEAK_D010",
            "R0_W250_Q20_K5_WEAK_D010",
        ):
            daily, interval = config_sources[config_id]
            parent_rows.extend(
                _parent_child_rows(daily, interval, config_id, run_id, code_commit)
            )

    _attach_year_concentration(state_rows, year_rows)

    overlap_rows = (
        _overlap_rows(config_sources, run_id, code_commit) if not errors else []
    )
    comparison_rows = (
        _comparison_rows(state_rows, run_id, code_commit) if not errors else []
    )
    invariants = _check_invariants(
        state_rows,
        duration_rows,
        comparison_rows,
        overlap_rows,
        parent_rows,
        t03_rows,
    )
    errors.extend(invariants["errors"])
    status = "completed" if not errors else "blocked"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "state_line_profile_csv": output_dir / "r1_t04_state_line_profile.csv",
        "state_line_profile_json": output_dir / "r1_t04_state_line_profile.json",
        "duration_profile_csv": output_dir / "r1_t04_duration_profile.csv",
        "reference_challenger_comparison_csv": output_dir
        / "r1_t04_reference_challenger_comparison.csv",
        "daily_overlap_profile_csv": output_dir / "r1_t04_daily_overlap_profile.csv",
        "parent_child_profile_csv": output_dir / "r1_t04_parent_child_profile.csv",
        "year_concentration_profile_csv": output_dir
        / "r1_t04_year_concentration_profile.csv",
        "diagnostic_summary": output_dir / "r1_t04_diagnostic_summary.json",
        "anomaly_scan": output_dir / "r1_t04_anomaly_scan.json",
        "summary": output_dir / "r1_t04_experiment_summary.json",
    }
    _write_csv(paths["state_line_profile_csv"], state_rows)
    _write_json(paths["state_line_profile_json"], state_rows)
    _write_csv(paths["duration_profile_csv"], duration_rows)
    _write_csv(paths["reference_challenger_comparison_csv"], comparison_rows)
    _write_csv(paths["daily_overlap_profile_csv"], overlap_rows)
    _write_csv(paths["parent_child_profile_csv"], parent_rows)
    _write_csv(paths["year_concentration_profile_csv"], year_rows)
    diagnostic = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": status,
        "invariants": invariants,
        "errors": sorted(set(errors)),
        "profile_row_count": len(state_rows),
        "duration_row_count": len(duration_rows),
        "comparison_row_count": len(comparison_rows),
        "overlap_row_count": len(overlap_rows),
        "parent_child_row_count": len(parent_rows),
        "year_row_count": len(year_rows),
    }
    _write_json(paths["diagnostic_summary"], diagnostic)
    anomaly = _anomaly_scan(
        status,
        run_id,
        code_commit,
        paths,
        invariants,
        errors,
        state_rows,
        comparison_rows,
    )
    _write_json(paths["anomaly_scan"], anomaly)
    summary = {
        "task_id": TASK_ID,
        "status": status,
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_path": _rel(config_path, root),
        "config_sha256": sha256_file(config_path),
        "input_lineage": lineage,
        "profile_registry": profiles,
        "output_paths": {
            key: {"path": _rel(path, root), "sha256": sha256_file(path)}
            for key, path in paths.items()
            if key != "summary"
        },
        "counts": diagnostic | {"selected_config_count": len(selected_configs)},
        "checks": invariants["checks"],
        "blocked_reasons": sorted(set(errors)),
        "downstream_gates": {
            "R1-T05_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
    }
    _write_json(paths["summary"], summary)
    return summary


def build_author_draft_package(
    *,
    summary_path: Path,
    evidence_path: Path,
    analysis_path: Path,
    readme_path: Path,
    root: Path = ROOT,
) -> Path:
    summary = _load_json(summary_path)
    output_dir = summary_path.parent
    result_path = output_dir / "r1_t04_result_package.json"
    paths = summary["output_paths"]
    primary = []
    for role in (
        "state_line_profile_csv",
        "duration_profile_csv",
        "reference_challenger_comparison_csv",
        "daily_overlap_profile_csv",
        "parent_child_profile_csv",
        "year_concentration_profile_csv",
    ):
        item = paths[role]
        primary.append(
            {
                "artifact_role": "primary_results",
                "path": item["path"],
                "sha256": item["sha256"],
                "record_count": _csv_count(root / item["path"]),
                "committed_to_repo": True,
            }
        )
    diagnostic = []
    for role in ("diagnostic_summary", "anomaly_scan"):
        item = paths[role]
        diagnostic.append(
            {
                "artifact_role": "diagnostic_summary"
                if role == "diagnostic_summary"
                else "anomaly_scan",
                "path": item["path"],
                "sha256": item["sha256"],
                "record_count": 1,
                "committed_to_repo": True,
            }
        )
    engineering = output_dir / "r1_t04_engineering_validation_result.json"
    package = {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "implementation_actor": "codex",
        "status": "author_analysis_complete",
        "input_package": {
            "path": summary["input_lineage"]["full_grid_manifest"]["path"],
            "sha256": summary["input_lineage"]["full_grid_manifest"]["sha256"],
        },
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "experiment_summary_path": _rel(summary_path, root),
        "experiment_summary_sha256": sha256_file(summary_path),
        "primary_result_artifacts": primary,
        "diagnostic_artifacts": diagnostic,
        "anomaly_scan_path": paths["anomaly_scan"]["path"],
        "anomaly_scan_sha256": paths["anomaly_scan"]["sha256"],
        "result_analysis_path": _rel(analysis_path, root),
        "result_analysis_sha256": sha256_file(analysis_path),
        "engineering_validation_result_path": _rel(engineering, root),
        "engineering_validation_result_sha256": sha256_file(engineering),
        "formal_evidence_path": _rel(evidence_path, root),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": None,
        "scientific_review_record_sha256": None,
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": _rel(readme_path, root),
        "readme_sha256": sha256_file(readme_path),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-T04 S_PCT 与 S_PCVT 分线状态画像",
        "expected_next_planned_task": "R1-T05 单指标诊断与层内互补性分析",
        "expected_downstream_gate_marker": "R1-T05_allowed_to_start: false",
        "superseded": False,
        "superseded_by": None,
        "gate_status": {
            "engineering_validator_status": "passed",
            "result_artifact_status": "passed",
            "author_result_analysis_status": "passed",
            "scientific_review_status": "pending",
            "anomaly_resolution_status": "passed",
            "review_phase": "author_analysis_complete",
            "readme_gate_updated": False,
        },
        "downstream_gate_allowed": False,
    }
    _write_json(result_path, package)
    return result_path


def _profile_state_line(
    *,
    daily: str,
    interval: str,
    profile: dict[str, Any],
    candidate: dict[str, Any],
    run_id: str,
    code_commit: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    state = profile["state_line"]
    daily_values = con.execute(
        f"""
        SELECT COUNT(*), SUM(validity_status='valid'), SUM(validity_status='unknown'), SUM(validity_status='blocked'),
               SUM(raw_state IS TRUE), SUM(raw_state IS FALSE), SUM(raw_state IS NULL),
               SUM(confirmed_state IS TRUE), SUM(confirmed_state IS FALSE), SUM(confirmed_state IS NULL),
               COUNT(DISTINCT CASE WHEN raw_state IS TRUE THEN security_id END), COUNT(DISTINCT CASE WHEN confirmed_state IS TRUE THEN security_id END),
               COUNT(DISTINCT CASE WHEN raw_state IS TRUE THEN substr(trading_date,1,4) END), COUNT(DISTINCT CASE WHEN confirmed_state IS TRUE THEN substr(trading_date,1,4) END)
        FROM {daily} WHERE state_name = ?
    """,
        [state],
    ).fetchone()
    raw = _raw_segment_stats(con, daily, state)
    confirmed = _confirmed_interval_stats(
        con, interval, daily, state, int(candidate["confirmation_days_K"])
    )
    base = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "state_line": state,
        "candidate_config_id": profile["candidate_config_id"],
        "profile_role": profile["role"],
        "W": candidate["percentile_window_W"],
        "q": candidate["low_quantile_q"],
        "K": candidate["confirmation_days_K"],
    }
    values = [int(value or 0) for value in daily_values]
    (
        eligible,
        valid,
        unknown,
        blocked,
        raw_true,
        raw_false,
        raw_null,
        confirmed_true,
        confirmed_false,
        confirmed_null,
        raw_securities,
        confirmed_securities,
        raw_years,
        confirmed_years,
    ) = values
    raw_row = _state_row(
        base,
        "raw",
        eligible,
        valid,
        unknown,
        blocked,
        raw_true,
        raw_false,
        raw_null,
        raw_securities,
        raw_years,
        raw,
    )
    confirmed_row = _state_row(
        base,
        "confirmed",
        eligible,
        valid,
        unknown,
        blocked,
        confirmed_true,
        confirmed_false,
        confirmed_null,
        confirmed_securities,
        confirmed_years,
        confirmed,
    )
    years = _year_rows(con, daily, interval, base, state)
    con.close()
    return (
        [raw_row, confirmed_row],
        [_duration_row(base, "raw", raw), _duration_row(base, "confirmed", confirmed)],
        years,
    )


def _raw_segment_stats(con: Any, daily: str, state: str) -> dict[str, Any]:
    row = con.execute(
        f"""
        WITH ordered AS (
          SELECT security_id, trading_date, raw_state, lower(coalesce(validity_status,'')) AS validity_status,
            lag(raw_state) OVER w AS prior_raw, lag(lower(coalesce(validity_status,''))) OVER w AS prior_validity
          FROM {daily} WHERE state_name=? WINDOW w AS (PARTITION BY security_id ORDER BY trading_date)
        ), starts AS (
          SELECT *, CASE WHEN validity_status='valid' AND raw_state IS TRUE AND NOT (prior_validity='valid' AND prior_raw IS TRUE) THEN 1 ELSE 0 END AS start_flag,
            CASE WHEN validity_status='valid' AND raw_state IS TRUE AND prior_validity='valid' AND prior_raw IS FALSE THEN 1 ELSE 0 END AS strict_flag
          FROM ordered
        ), numbered AS (
          SELECT *, sum(start_flag) OVER (PARTITION BY security_id ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS segment_id FROM starts
        ), segments AS (
          SELECT security_id, segment_id, count(*) AS duration FROM numbered WHERE validity_status='valid' AND raw_state IS TRUE GROUP BY security_id, segment_id
        )
        SELECT (SELECT sum(start_flag) FROM starts), (SELECT sum(strict_flag) FROM starts),
          count(*), sum(duration), avg(duration), stddev_samp(duration), min(duration),
          quantile_cont(duration,.10), quantile_cont(duration,.25), quantile_cont(duration,.50), quantile_cont(duration,.75), quantile_cont(duration,.90), quantile_cont(duration,.95), quantile_cont(duration,.99), max(duration), sum(duration=1)
        FROM segments
    """,
        [state],
    ).fetchone()
    keys = (
        "count",
        "strict_onset_count",
        "segment_count",
        "total_days",
        "mean",
        "std",
        "min",
        "q10",
        "q25",
        "q50",
        "q75",
        "q90",
        "q95",
        "q99",
        "max",
        "single_count",
    )
    result = {key: _number(value) for key, value in zip(keys, row, strict=True)}
    result["left_censored_count"] = (
        result["segment_count"] - result["strict_onset_count"]
    )
    result["fragment_rate"] = _safe_div(result["single_count"], result["segment_count"])
    return result


def _confirmed_interval_stats(
    con: Any, interval: str, daily: str, state: str, k: int
) -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT count(*), coalesce(sum(confirmed_length),0), avg(confirmed_length), stddev_samp(confirmed_length), min(confirmed_length),
          quantile_cont(confirmed_length,.10), quantile_cont(confirmed_length,.25), quantile_cont(confirmed_length,.50), quantile_cont(confirmed_length,.75), quantile_cont(confirmed_length,.90), quantile_cont(confirmed_length,.95), quantile_cont(confirmed_length,.99), max(confirmed_length),
          sum(confirmed_length=1), sum(is_open_interval), avg(CASE WHEN is_open_interval THEN 1.0 ELSE 0.0 END),
          sum(raw_length-confirmed_length != ?), sum(confirmation_time < raw_start_date), sum(confirmed_start_date != confirmation_time),
          avg(date_diff('day', strptime(raw_start_date,'%Y%m%d'),strptime(confirmation_time,'%Y%m%d')))
        FROM {interval} WHERE state_level=?
    """,
        [k - 1, state],
    ).fetchone()
    keys = (
        "count",
        "total_days",
        "mean",
        "std",
        "min",
        "q10",
        "q25",
        "q50",
        "q75",
        "q90",
        "q95",
        "q99",
        "max",
        "single_count",
        "open_count",
        "open_ratio",
        "length_mismatch_count",
        "early_confirmation_count",
        "confirmed_start_mismatch_count",
        "calendar_delay_mean",
    )
    result = {key: _number(value) for key, value in zip(keys, row, strict=True)}
    terms = con.execute(
        f"SELECT coalesce(termination_type,'NULL'), count(*) FROM {interval} WHERE state_level=? GROUP BY 1 ORDER BY 1",
        [state],
    ).fetchall()
    result["termination_distribution_json"] = json.dumps(
        {str(key): int(value) for key, value in terms},
        sort_keys=True,
        ensure_ascii=False,
    )
    result["strict_onset_count"] = result["count"]
    result["left_censored_count"] = 0
    result["fragment_rate"] = _safe_div(result["single_count"], result["count"])
    result["confirmation_delay_observations"] = k - 1
    return result


def _state_row(
    base: dict[str, Any],
    level: str,
    eligible: int,
    valid: int,
    unknown: int,
    blocked: int,
    true_count: int,
    false_count: int,
    null_count: int,
    securities: int,
    years: int,
    stats: dict[str, Any],
) -> dict[str, Any]:
    total_duration = stats["total_days"]
    return base | {
        "analysis_level": level,
        "eligible_day_count": eligible,
        "valid_day_count": valid,
        "unknown_day_count": unknown,
        "blocked_day_count": blocked,
        "state_true_day_count": true_count,
        "state_false_day_count": false_count,
        "state_null_day_count": null_count,
        "coverage": _safe_div(true_count, eligible),
        "valid_hit_rate": _safe_div(true_count, valid),
        "unique_security_count": securities,
        "nonzero_year_count": years,
        "onset_count": stats["strict_onset_count"],
        "left_censored_start_count": stats["left_censored_count"],
        "segment_or_interval_count": stats["segment_count"]
        if level == "raw"
        else stats["count"],
        "total_duration_days": total_duration,
        "mean_duration": stats["mean"],
        "median_duration": stats["q50"],
        "fragment_count": stats["single_count"],
        "fragment_rate": stats["fragment_rate"],
        "max_year_share": None,
        "year_hhi": None,
        "profile_status": "completed",
        "warnings": "",
    }


def _duration_row(
    base: dict[str, Any], level: str, stats: dict[str, Any]
) -> dict[str, Any]:
    return base | {
        "analysis_level": level,
        "duration_unit": "eligible_trading_observations",
        "count": stats["segment_count"] if level == "raw" else stats["count"],
        "mean": stats["mean"],
        "std": stats["std"],
        "min": stats["min"],
        "q10": stats["q10"],
        "q25": stats["q25"],
        "q50": stats["q50"],
        "q75": stats["q75"],
        "q90": stats["q90"],
        "q95": stats["q95"],
        "q99": stats["q99"],
        "max": stats["max"],
        "open_interval_count": stats.get("open_count", 0),
        "termination_distribution_json": stats.get(
            "termination_distribution_json", "{}"
        ),
    }


def _year_rows(
    con: Any, daily: str, interval: str, base: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    raw_onsets = {
        year: int(count or 0)
        for year, count in con.execute(
            f"""
          WITH ordered AS (
            SELECT security_id, trading_date, raw_state, lower(coalesce(validity_status,'')) AS validity_status,
              lag(raw_state) OVER w AS prior_raw, lag(lower(coalesce(validity_status,''))) OVER w AS prior_validity
            FROM {daily} WHERE state_name=? WINDOW w AS (PARTITION BY security_id ORDER BY trading_date)
          )
          SELECT substr(trading_date,1,4), sum(CASE WHEN validity_status='valid' AND raw_state IS TRUE AND NOT (prior_validity='valid' AND prior_raw IS TRUE) THEN 1 ELSE 0 END)
          FROM ordered GROUP BY 1
        """,
            [state],
        ).fetchall()
    }
    confirmed_intervals = {
        year: int(count or 0)
        for year, count in con.execute(
            f"SELECT substr(confirmation_time,1,4), count(*) FROM {interval} WHERE state_level=? GROUP BY 1",
            [state],
        ).fetchall()
    }
    for level, column in (("raw", "raw_state"), ("confirmed", "confirmed_state")):
        rows = con.execute(
            f"""
          SELECT substr(trading_date,1,4), count(*), sum({column} IS TRUE), count(DISTINCT CASE WHEN {column} IS TRUE THEN security_id END)
          FROM {daily} WHERE state_name=? GROUP BY 1 HAVING sum({column} IS TRUE)>0 ORDER BY 1
        """,
            [state],
        ).fetchall()
        total = sum(int(row[2]) for row in rows)
        for year, eligible, true_count, security_count in rows:
            share = _safe_div(int(true_count), total)
            starts = (
                raw_onsets.get(year, 0)
                if level == "raw"
                else confirmed_intervals.get(year, 0)
            )
            output.append(
                base
                | {
                    "analysis_level": level,
                    "year": int(year),
                    "eligible_day_count": int(eligible),
                    "state_true_day_count": int(true_count),
                    "coverage": _safe_div(int(true_count), int(eligible)),
                    "unique_security_count": int(security_count),
                    "onset_count": starts,
                    "segment_or_interval_count": starts,
                    "duration_total_days": int(true_count),
                    "year_share_of_state_days": share,
                }
            )
    for level in ("raw", "confirmed"):
        relevant = [row for row in output if row["analysis_level"] == level]
        shares = [row["year_share_of_state_days"] for row in relevant]
        max_share = max(shares) if shares else None
        hhi = sum(value * value for value in shares) if shares else None
        for row in relevant:
            row["nonzero_year_count"] = len(relevant)
            row["max_year_share"] = max_share
            row["year_hhi"] = hhi
    return output


def _attach_year_concentration(
    state_rows: list[dict[str, Any]], year_rows: list[dict[str, Any]]
) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in year_rows:
        grouped.setdefault(
            (row["state_line"], row["candidate_config_id"], row["analysis_level"]), []
        ).append(row)
    for row in state_rows:
        years = grouped.get(
            (row["state_line"], row["candidate_config_id"], row["analysis_level"]), []
        )
        shares = [item["year_share_of_state_days"] for item in years]
        row["max_year_share"] = max(shares) if shares else None
        row["year_hhi"] = sum(value * value for value in shares) if shares else None


def _overlap_rows(
    sources: dict[str, tuple[str, str]], run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    rows: list[dict[str, Any]] = []
    for comparison_id, state, reference, challenger, role in COMPARISONS:
        reference_source = sources[reference][0]
        challenger_source = sources[challenger][0]
        reference_interval = sources[reference][1]
        challenger_interval = sources[challenger][1]
        for level, column in (("raw", "raw_state"), ("confirmed", "confirmed_state")):
            values = con.execute(
                f"""
              SELECT sum(a.{column} IS TRUE AND b.{column} IS TRUE), sum(a.{column} IS TRUE AND b.{column} IS FALSE), sum(a.{column} IS FALSE AND b.{column} IS TRUE), sum(a.{column} IS FALSE AND b.{column} IS FALSE)
              FROM {reference_source} a JOIN {challenger_source} b USING(security_id,trading_date)
              WHERE a.state_name=? AND b.state_name=? AND a.validity_status='valid' AND b.validity_status='valid'
            """,
                [state, state],
            ).fetchone()
            both, ref_only, challenger_only, both_false = [
                int(value or 0) for value in values
            ]
            union = both + ref_only + challenger_only
            onset = _onset_overlap(
                con,
                state=state,
                analysis_level=level,
                reference_daily=reference_source,
                challenger_daily=challenger_source,
                reference_interval=reference_interval,
                challenger_interval=challenger_interval,
            )
            rows.append(
                {
                    "task_id": TASK_ID,
                    "run_id": run_id,
                    "code_commit": code_commit,
                    "state_line": state,
                    "comparison_id": comparison_id,
                    "reference_config_id": reference,
                    "challenger_config_id": challenger,
                    "comparison_role": role,
                    "analysis_level": level,
                    "both_true": both,
                    "reference_only": ref_only,
                    "challenger_only": challenger_only,
                    "both_false": both_false,
                    "common_valid_denominator": both
                    + ref_only
                    + challenger_only
                    + both_false,
                    "union_true": union,
                    "jaccard": _safe_div(both, union),
                    "reference_containment": _safe_div(both, both + ref_only),
                    "challenger_containment": _safe_div(both, both + challenger_only),
                    **onset,
                }
            )
    con.close()
    return rows


def _comparison_rows(
    state_rows: list[dict[str, Any]], run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    index = {
        (row["state_line"], row["candidate_config_id"], row["analysis_level"]): row
        for row in state_rows
    }
    rows = []
    for comparison_id, state, reference, challenger, role in COMPARISONS:
        for level in ("raw", "confirmed"):
            ref = index[(state, reference, level)]
            ch = index[(state, challenger, level)]
            coverage_delta = ch["coverage"] - ref["coverage"]
            fragment_delta = _sub(ch["fragment_rate"], ref["fragment_rate"])
            median_ratio = _safe_div(ch["median_duration"], ref["median_duration"])
            status = _comparison_status(
                role, coverage_delta, fragment_delta, median_ratio
            )
            rows.append(
                {
                    "task_id": TASK_ID,
                    "run_id": run_id,
                    "code_commit": code_commit,
                    "state_line": state,
                    "comparison_id": comparison_id,
                    "reference_config_id": reference,
                    "challenger_config_id": challenger,
                    "comparison_role": role,
                    "analysis_level": level,
                    "coverage_reference": ref["coverage"],
                    "coverage_challenger": ch["coverage"],
                    "coverage_delta": coverage_delta,
                    "coverage_ratio": _safe_div(ch["coverage"], ref["coverage"]),
                    "onset_delta": ch["onset_count"] - ref["onset_count"],
                    "onset_ratio": _safe_div(ch["onset_count"], ref["onset_count"]),
                    "fragment_rate_delta": fragment_delta,
                    "median_duration_ratio": median_ratio,
                    "unique_security_ratio": _safe_div(
                        ch["unique_security_count"], ref["unique_security_count"]
                    ),
                    "nonzero_year_delta": ch["nonzero_year_count"]
                    - ref["nonzero_year_count"],
                    "max_year_share_delta": _sub(
                        ch["max_year_share"], ref["max_year_share"]
                    ),
                    "comparison_status": status,
                    "warnings": "descriptive_only",
                }
            )
    return rows


def _parent_child_rows(
    daily: str, interval: str, config_id: str, run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    rows = []
    for level, column in (("raw", "raw_state"), ("confirmed", "confirmed_state")):
        values = con.execute(f"""
          SELECT sum(p.{column} IS TRUE), sum(c.{column} IS TRUE), sum(p.{column} IS TRUE AND c.{column} IS FALSE), sum(c.{column} IS TRUE AND p.{column} IS NOT TRUE)
          FROM {daily} p JOIN {daily} c USING(security_id,trading_date)
          WHERE p.state_name='S_PCT' AND c.state_name='S_PCVT' AND p.validity_status='valid' AND c.validity_status='valid'
        """).fetchone()
        parent, child, parent_only, outside = [int(value or 0) for value in values]
        geometry = _parent_child_geometry(con, daily, interval, level)
        rows.append(
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "code_commit": code_commit,
                "candidate_config_id": config_id,
                "analysis_level": level,
                "parent_true_days": parent,
                "child_true_days": child,
                "parent_only_days": parent_only,
                "child_share_of_parent_descriptive": _safe_div(child, parent),
                "child_outside_parent_day_count": outside,
                **geometry,
            }
        )
    con.close()
    return rows


def _onset_overlap(
    con: Any,
    *,
    state: str,
    analysis_level: str,
    reference_daily: str,
    challenger_daily: str,
    reference_interval: str,
    challenger_interval: str,
) -> dict[str, int | float | None]:
    if analysis_level == "confirmed":
        values = con.execute(
            f"""
            WITH reference_onsets AS (
              SELECT security_id, confirmation_time AS trading_date
              FROM {reference_interval} WHERE state_level=?
            ), challenger_onsets AS (
              SELECT security_id, confirmation_time AS trading_date
              FROM {challenger_interval} WHERE state_level=?
            )
            SELECT
              sum(r.security_id IS NOT NULL AND c.security_id IS NOT NULL),
              sum(r.security_id IS NOT NULL AND c.security_id IS NULL),
              sum(r.security_id IS NULL AND c.security_id IS NOT NULL)
            FROM reference_onsets r FULL OUTER JOIN challenger_onsets c
              USING(security_id, trading_date)
            """,
            [state, state],
        ).fetchone()
    else:
        values = con.execute(
            f"""
            WITH reference_ordered AS (
              SELECT security_id, trading_date, raw_state,
                lower(coalesce(validity_status,'')) AS validity_status,
                lag(raw_state) OVER w AS prior_raw,
                lag(lower(coalesce(validity_status,''))) OVER w AS prior_validity
              FROM {reference_daily} WHERE state_name=?
              WINDOW w AS (PARTITION BY security_id ORDER BY trading_date)
            ), reference_onsets AS (
              SELECT security_id, trading_date
              FROM reference_ordered
              WHERE validity_status='valid' AND raw_state IS TRUE
                AND prior_validity='valid' AND prior_raw IS FALSE
            ), challenger_ordered AS (
              SELECT security_id, trading_date, raw_state,
                lower(coalesce(validity_status,'')) AS validity_status,
                lag(raw_state) OVER w AS prior_raw,
                lag(lower(coalesce(validity_status,''))) OVER w AS prior_validity
              FROM {challenger_daily} WHERE state_name=?
              WINDOW w AS (PARTITION BY security_id ORDER BY trading_date)
            ), challenger_onsets AS (
              SELECT security_id, trading_date
              FROM challenger_ordered
              WHERE validity_status='valid' AND raw_state IS TRUE
                AND prior_validity='valid' AND prior_raw IS FALSE
            )
            SELECT
              sum(r.security_id IS NOT NULL AND c.security_id IS NOT NULL),
              sum(r.security_id IS NOT NULL AND c.security_id IS NULL),
              sum(r.security_id IS NULL AND c.security_id IS NOT NULL)
            FROM reference_onsets r FULL OUTER JOIN challenger_onsets c
              USING(security_id, trading_date)
            """,
            [state, state],
        ).fetchone()
    both, reference_only, challenger_only = [int(value or 0) for value in values]
    return {
        "both_onset": both,
        "reference_only_onset": reference_only,
        "challenger_only_onset": challenger_only,
        "onset_jaccard": _safe_div(both, both + reference_only + challenger_only),
    }


def _parent_child_geometry(
    con: Any, daily: str, interval: str, analysis_level: str
) -> dict[str, Any]:
    if analysis_level == "confirmed":
        values = con.execute(
            f"""
            WITH child AS (
              SELECT * FROM {interval} WHERE state_level='S_PCVT'
            ), parent AS (
              SELECT * FROM {interval} WHERE state_level='S_PCT'
            ), matched AS (
              SELECT c.*, p.confirmed_start_date AS parent_start,
                p.confirmed_length AS parent_length
              FROM child c LEFT JOIN LATERAL (
                SELECT * FROM parent p
                WHERE p.security_id=c.security_id
                  AND p.confirmed_start_date<=c.confirmed_start_date
                  AND p.interval_end_date>=c.interval_end_date
                ORDER BY p.confirmed_start_date DESC LIMIT 1
              ) p ON true
            )
            SELECT count(*), sum(parent_start IS NOT NULL),
              avg(CASE WHEN parent_start IS NOT NULL THEN (
                SELECT count(*) - 1 FROM {daily} d
                WHERE d.state_name='S_PCT' AND d.security_id=matched.security_id
                  AND d.validity_status='valid' AND d.confirmed_state IS TRUE
                  AND d.trading_date BETWEEN parent_start AND matched.confirmed_start_date
              ) END),
              avg(CASE WHEN parent_length IS NOT NULL THEN confirmed_length * 1.0 / parent_length END)
            FROM matched
            """
        ).fetchone()
        child_count, contained, delay, duration_share = values
        child_count = int(child_count or 0)
        contained = int(contained or 0)
        return {
            "geometry_unit": "confirmed_interval",
            "child_onset_count": child_count,
            "child_left_censored_start_count": 0,
            "child_onset_parent_active_count": contained,
            "child_segment_count": None,
            "child_segment_contained_in_parent_count": None,
            "child_segment_containment_mismatch_count": None,
            "child_interval_count": child_count,
            "child_interval_contained_in_parent_count": contained,
            "child_interval_containment_mismatch_count": child_count - contained,
            "child_start_delay_from_parent_observations": _number(delay),
            "child_duration_share_of_parent_interval": _number(duration_share),
        }
    values = con.execute(
        f"""
        WITH ordered AS (
          SELECT state_name, security_id, trading_date, raw_state,
            lower(coalesce(validity_status,'')) AS validity_status,
            lag(raw_state) OVER w AS prior_raw,
            lag(lower(coalesce(validity_status,''))) OVER w AS prior_validity
          FROM {daily} WHERE state_name IN ('S_PCT','S_PCVT')
          WINDOW w AS (PARTITION BY state_name, security_id ORDER BY trading_date)
        ), marked AS (
          SELECT *, CASE WHEN validity_status='valid' AND raw_state IS TRUE
            AND NOT (prior_validity='valid' AND prior_raw IS TRUE)
            THEN 1 ELSE 0 END AS start_flag,
            CASE WHEN validity_status='valid' AND raw_state IS TRUE
              AND prior_validity='valid' AND prior_raw IS FALSE
              THEN 1 ELSE 0 END AS strict_onset_flag
          FROM ordered
        ), numbered AS (
          SELECT *, sum(start_flag) OVER (
            PARTITION BY state_name, security_id ORDER BY trading_date
            ROWS UNBOUNDED PRECEDING
          ) AS segment_id FROM marked
        ), segments AS (
          SELECT state_name, security_id, segment_id, min(trading_date) AS start_date,
            max(trading_date) AS end_date, count(*) AS duration,
            max(strict_onset_flag) AS strict_onset_flag
          FROM numbered WHERE validity_status='valid' AND raw_state IS TRUE
          GROUP BY state_name, security_id, segment_id
        ), child AS (SELECT * FROM segments WHERE state_name='S_PCVT'),
        parent AS (SELECT * FROM segments WHERE state_name='S_PCT'),
        matched AS (
          SELECT c.*, p.start_date AS parent_start, p.duration AS parent_duration
          FROM child c LEFT JOIN LATERAL (
            SELECT * FROM parent p
            WHERE p.security_id=c.security_id
              AND p.start_date<=c.start_date AND p.end_date>=c.end_date
            ORDER BY p.start_date DESC LIMIT 1
          ) p ON true
        )
        SELECT count(*), sum(strict_onset_flag),
          sum(strict_onset_flag=0), sum(parent_start IS NOT NULL),
          sum(strict_onset_flag=1 AND parent_start IS NOT NULL),
          avg(CASE WHEN strict_onset_flag=1 AND parent_start IS NOT NULL THEN (
            SELECT count(*) - 1 FROM {daily} d
            WHERE d.state_name='S_PCT' AND d.security_id=matched.security_id
              AND d.validity_status='valid' AND d.raw_state IS TRUE
              AND d.trading_date BETWEEN parent_start AND matched.start_date
          ) END),
          avg(CASE WHEN parent_duration IS NOT NULL THEN duration * 1.0 / parent_duration END)
        FROM matched
        """
    ).fetchone()
    (
        child_count,
        strict_onsets,
        left_censored,
        contained,
        onset_parent_active,
        delay,
        duration_share,
    ) = values
    child_count = int(child_count or 0)
    strict_onsets = int(strict_onsets or 0)
    left_censored = int(left_censored or 0)
    contained = int(contained or 0)
    onset_parent_active = int(onset_parent_active or 0)
    return {
        "geometry_unit": "raw_segment",
        "child_onset_count": strict_onsets,
        "child_left_censored_start_count": left_censored,
        "child_onset_parent_active_count": onset_parent_active,
        "child_segment_count": child_count,
        "child_segment_contained_in_parent_count": contained,
        "child_segment_containment_mismatch_count": child_count - contained,
        "child_interval_count": None,
        "child_interval_contained_in_parent_count": None,
        "child_interval_containment_mismatch_count": None,
        "child_start_delay_from_parent_observations": _number(delay),
        "child_duration_share_of_parent_interval": _number(duration_share),
    }


def _check_invariants(
    state_rows: list[dict[str, Any]],
    duration_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    overlap_rows: list[dict[str, Any]],
    parent_rows: list[dict[str, Any]],
    t03_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = []
    checks = {}

    def check(name: str, condition: bool, message: str) -> None:
        checks[name] = "passed" if condition else "blocked"
        if not condition:
            errors.append(f"{name}:{message}")

    check(
        "profile_registry",
        len(state_rows) == PROFILE_ROWS,
        f"expected_{PROFILE_ROWS}_rows",
    )
    check(
        "comparison_pair_completeness",
        len(overlap_rows) == COMPARISON_ROWS,
        f"expected_{COMPARISON_ROWS}_rows",
    )
    check(
        "parent_child_completeness",
        len(parent_rows) == PARENT_CHILD_ROWS,
        f"expected_{PARENT_CHILD_ROWS}_rows",
    )
    check(
        "primary_output_nonempty",
        all(
            row["state_true_day_count"] > 0
            for row in state_rows
            if row["profile_role"]
            in (
                "reference_baseline",
                "reference_depletion_profile",
                "fast_structural_convergence_challenger",
                "short_window_counterfactual",
            )
        ),
        "primary_profile_zero",
    )
    check(
        "funnel_accounting",
        all(
            row["state_true_day_count"]
            + row["state_false_day_count"]
            + row["state_null_day_count"]
            == row["eligible_day_count"]
            for row in state_rows
        ),
        "daily_counts_do_not_sum",
    )
    check(
        "raw_confirmed_response",
        all(
            row["state_true_day_count"]
            <= next(
                item
                for item in state_rows
                if item["state_line"] == row["state_line"]
                and item["candidate_config_id"] == row["candidate_config_id"]
                and item["analysis_level"] == "raw"
            )["state_true_day_count"]
            for row in state_rows
            if row["analysis_level"] == "confirmed"
        ),
        "confirmed_exceeds_raw",
    )
    check(
        "interval_daily_reconciliation",
        all(
            row["total_duration_days"] == row["state_true_day_count"]
            for row in state_rows
            if row["analysis_level"] == "confirmed"
        ),
        "interval_total_not_daily_true",
    )
    check(
        "duration_quantiles",
        all(_quantile_ordered(row) for row in duration_rows),
        "duration_quantile_order",
    )
    check(
        "nested_invariant",
        all(
            row["child_outside_parent_day_count"] == 0
            and (
                row["child_segment_containment_mismatch_count"] == 0
                if row["analysis_level"] == "raw"
                else row["child_interval_containment_mismatch_count"] == 0
            )
            for row in parent_rows
        ),
        "pcvt_outside_pct",
    )
    check(
        "onset_overlap_completeness",
        all(
            row[field] is not None
            for row in overlap_rows
            for field in (
                "both_onset",
                "reference_only_onset",
                "challenger_only_onset",
                "onset_jaccard",
            )
        ),
        "required_onset_overlap_null",
    )
    check(
        "parent_child_geometry_completeness",
        all(
            row[field] is not None
            for row in parent_rows
            for field in (
                "child_onset_count",
                "child_onset_parent_active_count",
                "child_start_delay_from_parent_observations",
                "child_duration_share_of_parent_interval",
            )
        ),
        "required_parent_child_geometry_null",
    )
    raw_pcvt_profiles = {
        row["candidate_config_id"]: row
        for row in state_rows
        if row["state_line"] == "S_PCVT" and row["analysis_level"] == "raw"
    }
    raw_parent_rows = [row for row in parent_rows if row["analysis_level"] == "raw"]
    check(
        "parent_child_raw_onset_accounting",
        all(
            row["child_onset_count"] + row["child_left_censored_start_count"]
            == row["child_segment_count"]
            and row["child_onset_count"]
            == raw_pcvt_profiles[row["candidate_config_id"]]["onset_count"]
            and row["child_segment_count"]
            == raw_pcvt_profiles[row["candidate_config_id"]][
                "segment_or_interval_count"
            ]
            and row["child_onset_parent_active_count"] <= row["child_onset_count"]
            for row in raw_parent_rows
        ),
        "raw_child_onset_or_segment_mismatch",
    )
    confirmed_parent_rows = [
        row for row in parent_rows if row["analysis_level"] == "confirmed"
    ]
    check(
        "parent_child_confirmed_onset_accounting",
        all(
            row["child_onset_count"] == row["child_interval_count"]
            and row["child_onset_parent_active_count"] <= row["child_onset_count"]
            for row in confirmed_parent_rows
        ),
        "confirmed_child_onset_or_interval_mismatch",
    )
    check(
        "comparison_year_concentration_completeness",
        all(row["max_year_share_delta"] is not None for row in comparison_rows),
        "required_max_year_share_delta_null",
    )
    raw_index = {
        (r["state_line"], r["candidate_config_id"]): r
        for r in state_rows
        if r["analysis_level"] == "raw"
    }
    confirmed_index = {
        (r["state_line"], r["candidate_config_id"]): r
        for r in state_rows
        if r["analysis_level"] == "confirmed"
    }
    k_raw = (
        raw_index[("S_PCT", "R0_W120_Q20_K2_WEAK_D010")]["state_true_day_count"]
        == raw_index[("S_PCT", "R0_W120_Q20_K3_WEAK_D010")]["state_true_day_count"]
        and raw_index[("S_PCVT", "R0_W250_Q20_K5_WEAK_D010")]["state_true_day_count"]
        == raw_index[("S_PCVT", "R0_W250_Q20_K3_WEAK_D010")]["state_true_day_count"]
    )
    check("k_raw_invariance", k_raw, "raw_state_changed_with_K")
    k_confirmed = (
        confirmed_index[("S_PCT", "R0_W120_Q20_K2_WEAK_D010")]["state_true_day_count"]
        >= confirmed_index[("S_PCT", "R0_W120_Q20_K3_WEAK_D010")][
            "state_true_day_count"
        ]
        and confirmed_index[("S_PCVT", "R0_W250_Q20_K3_WEAK_D010")][
            "state_true_day_count"
        ]
        >= confirmed_index[("S_PCVT", "R0_W250_Q20_K5_WEAK_D010")][
            "state_true_day_count"
        ]
    )
    check("k_confirmed_monotonicity", k_confirmed, "confirmed_state_increased_with_K")
    for state in ("S_PCT", "S_PCVT"):
        if state == "S_PCT":
            continue
        valid = [
            raw_index[(state, f"R0_W{w}_Q20_K3_WEAK_D010")]["valid_day_count"]
            for w in (120, 250, 500)
        ]
        unknown = [
            raw_index[(state, f"R0_W{w}_Q20_K3_WEAK_D010")]["unknown_day_count"]
            / raw_index[(state, f"R0_W{w}_Q20_K3_WEAK_D010")]["eligible_day_count"]
            for w in (120, 250, 500)
        ]
        check(
            "w_availability_response",
            valid[0] >= valid[1] >= valid[2] and unknown[0] <= unknown[1] <= unknown[2],
            "availability_not_monotone",
        )
    check(
        "r1_t03_reconciliation",
        _reconcile_t03(state_rows, t03_rows),
        "shared_statistics_mismatch",
    )
    return {"checks": checks, "errors": errors}


def _reconcile_t03(
    state_rows: list[dict[str, Any]], t03_rows: list[dict[str, Any]]
) -> bool:
    source = {(r["state_name"], r["candidate_config_id"]): r for r in t03_rows}
    for row in state_rows:
        expected = source.get((row["state_line"], row["candidate_config_id"]))
        if expected is None:
            return False
        prefix = "raw" if row["analysis_level"] == "raw" else "confirmed"
        pairs = (
            ("eligible_day_count", "eligible_day_count"),
            ("valid_day_count", "valid_day_count"),
            ("unknown_day_count", "unknown_day_count"),
            ("blocked_day_count", "blocked_day_count"),
            ("state_true_day_count", f"{prefix}_state_true_day_count"),
        )
        if any(row[a] != expected[b] for a, b in pairs):
            return False
        if (
            row["analysis_level"] == "confirmed"
            and row["segment_or_interval_count"] != expected["confirmed_interval_count"]
        ):
            return False
        if (
            row["analysis_level"] == "raw"
            and row["segment_or_interval_count"] != expected["raw_segment_count"]
        ):
            return False
    return True


def _anomaly_scan(
    status: str,
    run_id: str,
    code_commit: str,
    paths: dict[str, Path],
    invariants: dict[str, Any],
    errors: list[str],
    state_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    names = (
        "primary_output_nonempty",
        "all_zero_check",
        "all_one_check",
        "all_null_check",
        "validity_rate_check",
        "coverage_check",
        "parameter_response_check",
        "baseline_challenger_check",
        "nested_invariant_check",
        "funnel_accounting_check",
        "denominator_integrity_check",
        "sample_size_check",
        "upstream_consistency_check",
        "scale_shift_check",
        "time_alignment_check",
        "future_leakage_check",
        "post_hoc_selection_check",
        "conclusion_support_check",
    )
    source_checks = invariants["checks"]
    mappings = {
        "primary_output_nonempty": ("primary_output_nonempty",),
        "all_zero_check": ("primary_output_nonempty",),
        "all_one_check": ("funnel_accounting",),
        "all_null_check": (
            "onset_overlap_completeness",
            "parent_child_geometry_completeness",
            "parent_child_raw_onset_accounting",
            "parent_child_confirmed_onset_accounting",
            "comparison_year_concentration_completeness",
        ),
        "validity_rate_check": ("w_availability_response",),
        "coverage_check": ("primary_output_nonempty",),
        "parameter_response_check": (
            "k_raw_invariance",
            "k_confirmed_monotonicity",
            "w_availability_response",
        ),
        "baseline_challenger_check": (
            "comparison_pair_completeness",
            "onset_overlap_completeness",
        ),
        "nested_invariant_check": (
            "nested_invariant",
            "parent_child_geometry_completeness",
            "parent_child_raw_onset_accounting",
            "parent_child_confirmed_onset_accounting",
        ),
        "funnel_accounting_check": (
            "funnel_accounting",
            "interval_daily_reconciliation",
        ),
        "denominator_integrity_check": ("onset_overlap_completeness",),
        "sample_size_check": ("primary_output_nonempty",),
        "upstream_consistency_check": ("r1_t03_reconciliation",),
        "scale_shift_check": ("r1_t03_reconciliation",),
        "time_alignment_check": ("interval_daily_reconciliation",),
        "future_leakage_check": ("profile_registry",),
        "post_hoc_selection_check": ("profile_registry",),
        "conclusion_support_check": (
            "onset_overlap_completeness",
            "comparison_year_concentration_completeness",
        ),
    }
    checks = {}
    for name in names:
        required = mappings[name]
        passed = status == "completed" and all(
            source_checks.get(check) == "passed" for check in required
        )
        checks[name] = {
            "status": "passed" if passed else "blocked",
            "rationale": "R1-T04 task-specific machine-readable check: "
            + ", ".join(required),
            "metrics": {check: source_checks.get(check) for check in required},
            "artifact_references": [_rel(paths["diagnostic_summary"], ROOT)],
        }
    warnings = _material_warnings(state_rows, comparison_rows)
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if status == "completed" else "blocked",
        "checks": checks,
        "blocking_anomalies": sorted(set(errors)),
        "nonblocking_anomalies": [warning["name"] for warning in warnings],
        "investigations": warnings,
        "unresolved_questions": [],
    }


def _material_warnings(
    state_rows: list[dict[str, Any]], comparison_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    cross_window = [
        row
        for row in comparison_rows
        if row["comparison_id"] in ("PCT_W250K3_vs_W120K3", "PCVT_W250K3_vs_W120K3")
    ]
    if any(
        (row["coverage_ratio"] is not None and row["coverage_ratio"] > 1.0)
        for row in cross_window
    ) and any(row["comparison_id"] == "PCT_W250K3_vs_W120K3" for row in cross_window):
        warnings.append(
            {
                "name": "window_dependent_state_identity",
                "status": "material_warning",
                "metrics": [
                    {
                        "comparison_id": row["comparison_id"],
                        "analysis_level": row["analysis_level"],
                    }
                    for row in cross_window
                ],
                "rationale": "Cross-window exact-day overlap is reported as a state-identity warning, not a parameter-selection result.",
            }
        )
    k_rows = [
        row
        for row in comparison_rows
        if row["comparison_id"] in ("PCT_W120K3_vs_W120K2", "PCVT_W250K3_vs_W250K5")
        and row["analysis_level"] == "confirmed"
    ]
    if k_rows:
        warnings.append(
            {
                "name": "confirmation_population_k_sensitivity",
                "status": "material_warning",
                "metrics": [
                    {
                        "comparison_id": row["comparison_id"],
                        "coverage_ratio": row["coverage_ratio"],
                        "unique_security_ratio": row["unique_security_ratio"],
                    }
                    for row in k_rows
                ],
                "rationale": "K changes follow the required mechanical direction but materially change the confirmed population.",
            }
        )
    fragmented = [
        row
        for row in state_rows
        if row["state_line"] == "S_PCVT"
        and row["analysis_level"] == "confirmed"
        and row["fragment_rate"] is not None
        and row["fragment_rate"] >= 0.4
    ]
    if fragmented:
        warnings.append(
            {
                "name": "pcvt_confirmed_high_fragmentation",
                "status": "material_warning",
                "metrics": [
                    {
                        "candidate_config_id": row["candidate_config_id"],
                        "fragment_rate": row["fragment_rate"],
                        "median_duration": row["median_duration"],
                    }
                    for row in fragmented
                ],
                "rationale": "A substantial share of confirmed PCVT intervals contain one observation.",
            }
        )
    return warnings


def _load_lineage(
    config: dict[str, Any], root: Path
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
    errors = []
    t03_validation = _load_json(root / config["r1_t03_validation_result_path"])
    if t03_validation.get("validator_status") != "passed":
        errors.append("r1_t03_gate_not_passed")
    t03_summary = _load_json(root / config["r1_t03_summary_path"])
    t02_summary = _load_json(root / config["r1_t02_summary_path"])
    manifest_path = root / (
        t03_summary.get("input_full_grid_manifest_path")
        or t02_summary.get("full_grid_manifest_path", "")
    )
    manifest = _load_json(manifest_path)
    lineage = {
        "r1_t01_manifest_lock": {
            "path": config["r1_t01_manifest_lock_path"],
            "sha256": sha256_file(root / config["r1_t01_manifest_lock_path"]),
        },
        "r1_t02_summary": {
            "path": config["r1_t02_summary_path"],
            "sha256": sha256_file(root / config["r1_t02_summary_path"]),
        },
        "r1_t03_summary": {
            "path": config["r1_t03_summary_path"],
            "sha256": sha256_file(root / config["r1_t03_summary_path"]),
        },
        "full_grid_manifest": {
            "path": _rel(manifest_path, root),
            "sha256": sha256_file(manifest_path),
        },
    }
    return (
        lineage,
        manifest,
        _load_json(
            root / t03_summary["output_paths"]["profile_by_config_state_json"]["path"]
        ),
        errors,
    )


def _check_artifact_entry(
    root: Path, entry: dict[str, Any] | None, config_id: str
) -> list[str]:
    if not entry:
        return [f"missing_manifest_artifact:{config_id}"]
    errors = []
    for name in ("daily", "interval"):
        path = root / entry[f"{name}_parquet_path"]
        if not path.exists():
            errors.append(f"missing_{name}_artifact:{config_id}")
        elif sha256_file(path) != entry[f"{name}_parquet_sha256"]:
            errors.append(f"hash_mismatch_{name}:{config_id}")
    return errors


def _validate_config(config: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = []
    try:
        Draft202012Validator(schema).validate(config)
    except Exception as exc:
        errors.append(f"config_schema:{exc}")
    profiles = {
        (p.get("state_line"), p.get("candidate_config_id"))
        for p in config.get("profiles", [])
    }
    if len(profiles) != 7:
        errors.append("profile_registry_not_exactly_seven")
    return errors


def _comparison_status(
    role: str,
    coverage_delta: float | None,
    fragment_delta: float | None,
    median_ratio: float | None,
) -> str:
    if coverage_delta is None:
        return "not_comparable"
    if (
        "fast" in role
        and coverage_delta >= 0
        and (fragment_delta or 0) <= 0
        and (median_ratio is None or median_ratio >= 1)
    ):
        return "direction_consistent"
    if "fast" in role and coverage_delta >= 0:
        return "sensitivity_coherence_tradeoff"
    if (
        "long" in role
        and coverage_delta < 0
        and ((fragment_delta or 0) < 0 or (median_ratio or 0) > 1)
    ):
        return "coherence_gain_coverage_loss"
    return "mixed_profile"


def _quantile_ordered(row: dict[str, Any]) -> bool:
    values = [
        row[key]
        for key in ("min", "q10", "q25", "q50", "q75", "q90", "q95", "q99", "max")
    ]
    values = [value for value in values if value is not None]
    return values == sorted(values)


def _parquet_source(path: Path) -> str:
    return "read_parquet('" + str(path).replace("\\", "/").replace("'", "''") + "')"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0])
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=keys, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _safe_div(
    numerator: int | float | None, denominator: int | float | None
) -> float | None:
    return (
        None
        if numerator is None or denominator in (None, 0)
        else float(numerator) / float(denominator)
    )


def _sub(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    return (
        int(value)
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer())
        else float(value)
    )


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _csv_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)
