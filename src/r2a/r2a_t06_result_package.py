"""Build the exact R2A-T06 scientific package from validated lifecycle rows."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any

import duckdb

from src.r2a.r2a_t06_formal_input_manifest import canonical_json_bytes, sha256_file

SCIENTIFIC_FILES = (
    "request_identity.json",
    "input_manifest.json",
    "run_summary.json",
    "validation_receipt.json",
    "result_analysis.md",
    "false_run_length_profile.csv",
    "recovery_hazard_profile.csv",
    "candidate_exit_summary.csv",
    "recognition_lag_profile.csv",
    "post_recognition_reentry.csv",
    "episode_fragmentation_profile.csv",
    "exit_type_margin_profile.csv",
    "cross_q_nesting_validation.csv",
    "year_profile.csv",
    "security_profile.csv",
    "deterministic_episode_samples.csv",
    "t06_detail.duckdb",
)
CONTROL_FILES = (
    "formal_authorization.json",
    "execution_log.jsonl",
    "artifact_manifest.json",
    "result_package.json",
    "anomaly_scan.json",
    "determinism_receipt.json",
)
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
REENTRY_HORIZONS = (
    ("raw_reentry", 1, "raw_state"),
    ("raw_reentry", 3, "raw_state"),
    ("raw_reentry", 5, "raw_state"),
    ("confirmed_reentry", 5, "confirmed_state_v1"),
    ("confirmed_reentry", 10, "confirmed_state_v1"),
)


class ResultPackageError(RuntimeError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


def _q_bp(name: str) -> int:
    try:
        return int(name.split("_q", 1)[1].split("_", 1)[0]) * 100
    except (IndexError, ValueError) as error:
        raise ResultPackageError("logical_request_name_invalid", name) from error


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip("\r\n") + "\n", encoding="utf-8", newline="\n")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fields:
                fields.append(key)
    if not fields:
        fields = ["empty"]
        materialized = []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {
                    key: (
                        json.dumps(
                            value, ensure_ascii=False, sort_keys=True, default=str
                        )
                        if isinstance(value, dict | list | tuple)
                        else _json_safe(value)
                    )
                    for key, value in row.items()
                }
            )


def _percentile(values: Sequence[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999))
    return float(ordered[index])


def _candidate_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    observations = list(result["observation_rows"])
    triggers = list(result["trigger_rows"])
    episodes = list(result["episode_rows"])
    dispositions = Counter(str(row["disposition"]) for row in triggers)
    recognized = [row for row in triggers if row["disposition"] == "EXIT_RECOGNIZED"]
    spans = [
        int(row["end_observation_sequence"])
        - int(row["start_observation_sequence"])
        + 1
        for row in episodes
    ]
    active_count = sum(
        row["lifecycle_state"] in {"ACTIVE", "EXIT_PENDING"} for row in observations
    )
    return {
        "logical_request_name": result["logical_request_name"],
        "q_bp": _q_bp(str(result["logical_request_name"])),
        "exit_confirmation_m": int(result["exit_confirmation_m"]),
        "provisional_exit_count": len(triggers),
        "recognized_exit_count": len(recognized),
        "cancelled_exit_count": dispositions["CANCELLED"],
        "quality_terminated_pending_count": dispositions["QUALITY_TERMINATED"],
        "pending_right_censored_count": dispositions["PENDING_RIGHT_CENSORED"],
        "cancel_rate": dispositions["CANCELLED"] / len(triggers) if triggers else None,
        "security_count": len({row["security_id"] for row in observations}),
        "recognized_security_count": len({row["security_id"] for row in recognized}),
        "episode_count": len(episodes),
        "active_observation_count": active_count,
        "bridged_false_observation_count": sum(
            int(row["bridged_false_observation_count"]) for row in episodes
        ),
        "median_episode_span": median(spans) if spans else None,
        "p90_episode_span": _percentile(spans, 0.90),
        "p95_episode_span": _percentile(spans, 0.95),
        "active_day_density": active_count / len(observations)
        if observations
        else None,
    }


def _false_run_tables(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profile: list[dict[str, Any]] = []
    hazard: list[dict[str, Any]] = []
    for result in candidates:
        name = str(result["logical_request_name"])
        inventory = list(result["false_run_inventory"])
        groups: Counter[tuple[str, int, str]] = Counter(
            (
                str(row["trigger_exit_type"]),
                int(row["false_run_length"]),
                str(row["run_end_class"]),
            )
            for row in inventory
        )
        for (exit_type, length, end_class), count in sorted(groups.items()):
            type_total = sum(
                value
                for (kind, _length, _end), value in groups.items()
                if kind == exit_type
            )
            profile.append(
                {
                    "q": name,
                    "exit_confirmation_m": result["exit_confirmation_m"],
                    "trigger_exit_type": exit_type,
                    "false_run_length": length,
                    "run_count": count,
                    "run_share": count / type_total if type_total else None,
                    "run_end_class": end_class,
                }
            )
        for exit_type in ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL"):
            selected = [
                row for row in inventory if row["trigger_exit_type"] == exit_type
            ]
            for streak in (1, 2, 3):
                denominator = sum(
                    int(row["false_run_length"]) > streak
                    or (
                        int(row["false_run_length"]) == streak
                        and row["run_end_class"] == "VALID_RAW_TRUE"
                    )
                    for row in selected
                )
                recovery = sum(
                    int(row["false_run_length"]) == streak
                    and row["run_end_class"] == "VALID_RAW_TRUE"
                    for row in selected
                )
                hazard.append(
                    {
                        "q": name,
                        "exit_confirmation_m": result["exit_confirmation_m"],
                        "trigger_exit_type": exit_type,
                        "false_streak": streak,
                        "observable_denominator": denominator,
                        "recovery_count": recovery,
                        "hazard": recovery / denominator if denominator else None,
                    }
                )
    return profile, hazard


def _recognition_lag(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for result in candidates:
        m = int(result["exit_confirmation_m"])
        recognized = [
            row
            for row in result["trigger_rows"]
            if row["disposition"] == "EXIT_RECOGNIZED"
        ]
        counts = Counter(int(row["recognition_lag"]) for row in recognized)
        for lag in sorted(set(counts) | {m - 1}):
            output.append(
                {
                    "logical_request_name": result["logical_request_name"],
                    "exit_confirmation_m": m,
                    "recognition_lag": lag,
                    "recognized_count": counts[lag],
                    "expected_lag": m - 1,
                    "anomaly_lag_count": sum(
                        count for value, count in counts.items() if value != m - 1
                    ),
                }
            )
    return output


def _post_recognition_outcomes(
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for result in candidates:
        by_security: dict[str, dict[int, Mapping[str, Any]]] = defaultdict(dict)
        for row in result["observation_rows"]:
            by_security[str(row["security_id"])][int(row["observation_sequence"])] = row
        for trigger in result["trigger_rows"]:
            if trigger["disposition"] != "EXIT_RECOGNIZED":
                continue
            recognition = int(trigger["exit_recognition_observation_sequence"])
            security = str(trigger["security_id"])
            rows = by_security[security]
            for metric, horizon, state_field in REENTRY_HORIZONS:
                outcome = "CLEAN_NOT_REENTERED"
                event_sequence: int | None = None
                observed_count = 0
                quality_reason: str | None = None
                for offset in range(1, horizon + 1):
                    expected_sequence = recognition + offset
                    row = rows.get(expected_sequence)
                    if row is None:
                        if any(value > expected_sequence for value in rows):
                            outcome = "QUALITY_INTERRUPTED"
                            quality_reason = "missing_observation_sequence"
                            event_sequence = expected_sequence
                        else:
                            outcome = "INPUT_END_CENSORED"
                        break
                    reason = row.get("quality_reason")
                    if reason or row.get("joint_ready") is not True:
                        outcome = "QUALITY_INTERRUPTED"
                        quality_reason = str(reason or "joint_not_ready")
                        event_sequence = expected_sequence
                        break
                    observed_count += 1
                    if row.get(state_field) is True:
                        outcome = "REENTERED"
                        event_sequence = expected_sequence
                        break
                outcomes.append(
                    {
                        "trigger_id": trigger["trigger_id"],
                        "episode_identity": trigger["episode_identity"],
                        "logical_request_name": result["logical_request_name"],
                        "exit_confirmation_m": int(result["exit_confirmation_m"]),
                        "security_id": security,
                        "recognition_sequence": recognition,
                        "metric": metric,
                        "horizon": horizon,
                        "outcome": outcome,
                        "event_sequence": event_sequence,
                        "observed_sequence_count": observed_count,
                        "quality_reason": quality_reason,
                    }
                )
    return outcomes


def _post_recognition(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    detailed = _post_recognition_outcomes(candidates)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for item in detailed:
        grouped[
            (str(item["logical_request_name"]), int(item["exit_confirmation_m"]))
        ].append(item)
    output: list[dict[str, Any]] = []
    for result in candidates:
        name = str(result["logical_request_name"])
        m = int(result["exit_confirmation_m"])
        records = grouped[(name, m)]
        row: dict[str, Any] = {
            "logical_request_name": name,
            "exit_confirmation_m": m,
            "recognized_count": sum(
                item["disposition"] == "EXIT_RECOGNIZED"
                for item in result["trigger_rows"]
            ),
        }
        for metric, horizon, _state_field in REENTRY_HORIZONS:
            key = f"{metric}_{horizon}"
            selected = [
                item
                for item in records
                if item["metric"] == metric and item["horizon"] == horizon
            ]
            counts = Counter(str(item["outcome"]) for item in selected)
            denominator = counts["REENTERED"] + counts["CLEAN_NOT_REENTERED"]
            row[f"{key}_reentered_count"] = counts["REENTERED"]
            row[f"{key}_clean_not_reentered_count"] = counts["CLEAN_NOT_REENTERED"]
            row[f"{key}_quality_interrupted_count"] = counts["QUALITY_INTERRUPTED"]
            row[f"{key}_input_end_censored_count"] = counts["INPUT_END_CENSORED"]
            row[f"{key}_clean_denominator"] = denominator
            row[f"{key}_rate"] = (
                counts["REENTERED"] / denominator if denominator else None
            )
        output.append(row)
    return output


def _fragmentation(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for result in candidates:
        spans = [
            int(row["end_observation_sequence"])
            - int(row["start_observation_sequence"])
            + 1
            for row in result["episode_rows"]
        ]
        output.append(
            {
                "logical_request_name": result["logical_request_name"],
                "exit_confirmation_m": result["exit_confirmation_m"],
                "episode_count": len(spans),
                "median_span": median(spans) if spans else None,
                "p90_span": _percentile(spans, 0.9),
                "p95_span": _percentile(spans, 0.95),
                "max_span": max(spans) if spans else None,
            }
        )
    return output


def _exit_margin(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for result in candidates:
        observations = {
            (row["security_id"], row["observation_sequence"]): row
            for row in result["observation_rows"]
        }
        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for trigger in result["trigger_rows"]:
            row = observations[
                (trigger["security_id"], trigger["exit_trigger_observation_sequence"])
            ]
            margins = row.get("dimension_margin", {})
            for dimension in ("C", "A"):
                value = margins.get(dimension) if isinstance(margins, Mapping) else None
                if isinstance(value, int | float) and not isinstance(value, bool):
                    grouped[(str(trigger["exit_type"]), dimension)].append(float(value))
        for exit_type in ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL"):
            for dimension in ("C", "A"):
                values = grouped[(exit_type, dimension)]
                output.append(
                    {
                        "logical_request_name": result["logical_request_name"],
                        "exit_confirmation_m": result["exit_confirmation_m"],
                        "trigger_exit_type": exit_type,
                        "dimension_id": dimension,
                        "observable_count": len(values),
                        "mean_margin": sum(values) / len(values) if values else None,
                        "min_margin": min(values) if values else None,
                        "max_margin": max(values) if values else None,
                    }
                )
    return output


def _year_security(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    years: Counter[tuple[str, int, str]] = Counter()
    securities: Counter[tuple[str, int, str]] = Counter()
    for result in candidates:
        name = str(result["logical_request_name"])
        m = int(result["exit_confirmation_m"])
        for row in result["trigger_rows"]:
            if row["disposition"] != "EXIT_RECOGNIZED":
                continue
            year = str(row.get("exit_recognition_time") or "UNKNOWN")[:4]
            years[(name, m, year)] += 1
            securities[(name, m, str(row["security_id"]))] += 1
    year_rows = [
        {
            "logical_request_name": key[0],
            "exit_confirmation_m": key[1],
            "year": key[2],
            "recognized_exit_count": count,
        }
        for key, count in sorted(years.items())
    ]
    security_rows = [
        {
            "logical_request_name": key[0],
            "exit_confirmation_m": key[1],
            "security_id": key[2],
            "recognized_exit_count": count,
        }
        for key, count in sorted(securities.items())
    ]
    return year_rows, security_rows


def _samples(
    candidates: Sequence[Mapping[str, Any]], limit: int = 100
) -> list[dict[str, Any]]:
    rows = []
    for result in candidates:
        for episode in result["episode_rows"]:
            token = "|".join(
                str(value)
                for value in (
                    result["logical_request_name"],
                    result["exit_confirmation_m"],
                    episode["episode_id"],
                )
            )
            rows.append(
                {
                    "logical_request_name": result["logical_request_name"],
                    "exit_confirmation_m": result["exit_confirmation_m"],
                    "security_id": episode["security_id"],
                    "episode_id": episode["episode_id"],
                    "episode_identity": episode["episode_identity"],
                    "sample_hash": hashlib.sha256(token.encode()).hexdigest(),
                }
            )
    return sorted(rows, key=lambda row: row["sample_hash"])[:limit]


def build_scientific_tables(
    candidate: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    candidates = list(candidate["candidates"])
    false_runs, hazards = _false_run_tables(candidates)
    years, securities = _year_security(candidates)
    return {
        "candidate_exit_summary.csv": [_candidate_summary(item) for item in candidates],
        "false_run_length_profile.csv": false_runs,
        "recovery_hazard_profile.csv": hazards,
        "recognition_lag_profile.csv": _recognition_lag(candidates),
        "post_recognition_reentry.csv": _post_recognition(candidates),
        "episode_fragmentation_profile.csv": _fragmentation(candidates),
        "exit_type_margin_profile.csv": _exit_margin(candidates),
        "cross_q_nesting_validation.csv": list(candidate["cross_q_nesting_validation"]),
        "year_profile.csv": years,
        "security_profile.csv": securities,
        "deterministic_episode_samples.csv": _samples(candidates),
    }


def _episode_memberships(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for episode in result["episode_rows"]:
        security = str(episode["security_id"])
        start = int(episode["start_observation_sequence"])
        end = int(episode["end_observation_sequence"])
        keys = {
            (security, int(row["observation_sequence"]))
            for row in result["observation_rows"]
            if str(row["security_id"]) == security
            and start <= int(row["observation_sequence"]) <= end
            and row["lifecycle_state"] in {"ACTIVE", "EXIT_PENDING"}
        }
        output.append({"episode": episode, "keys": keys})
    return output


def _cross_q_parent_mappings(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_key = {
        (
            str(result["logical_request_name"]),
            int(result["exit_confirmation_m"]),
        ): result
        for result in candidate["candidates"]
    }
    output = []
    for m in (1, 2, 3):
        for child, parent in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
            children = _episode_memberships(by_key[(child, m)])
            parents = _episode_memberships(by_key[(parent, m)])
            for item in children:
                containing = [
                    parent_item
                    for parent_item in parents
                    if item["keys"] and item["keys"] <= parent_item["keys"]
                ]
                if len(containing) != 1:
                    raise ResultPackageError("cross_q_parent_mapping_not_unique")
                output.append(
                    {
                        "exit_confirmation_m": m,
                        "child_request": child,
                        "parent_request": parent,
                        "child_episode_id": item["episode"]["episode_id"],
                        "child_episode_identity": item["episode"]["episode_identity"],
                        "parent_episode_id": containing[0]["episode"]["episode_id"],
                        "parent_episode_identity": containing[0]["episode"][
                            "episode_identity"
                        ],
                    }
                )
    return output


def _write_detail_database(path: Path, candidate: Mapping[str, Any]) -> None:
    rows_by_table: dict[str, list[dict[str, Any]]] = {
        "observations": [],
        "triggers": [],
        "episodes": [],
        "m_candidate_mapping": [],
        "cross_q_parent_mapping": _cross_q_parent_mappings(candidate),
        "post_recognition_outcomes": _post_recognition_outcomes(
            list(candidate["candidates"])
        ),
    }
    for result in candidate["candidates"]:
        prefix = {
            "logical_request_name": result["logical_request_name"],
            "exit_confirmation_m": result["exit_confirmation_m"],
        }
        for table, key in (
            ("observations", "observation_rows"),
            ("triggers", "trigger_rows"),
            ("episodes", "episode_rows"),
        ):
            rows_by_table[table].extend({**prefix, **dict(row)} for row in result[key])
        rows_by_table["m_candidate_mapping"].append(
            {
                **prefix,
                "observation_count": len(result["observation_rows"]),
                "trigger_count": len(result["trigger_rows"]),
                "episode_count": len(result["episode_rows"]),
            }
        )
    try:
        with duckdb.connect(str(path)) as connection:
            for table, rows in rows_by_table.items():
                connection.execute(f'CREATE TABLE "{table}" (payload JSON NOT NULL)')
                if rows:
                    connection.executemany(
                        f'INSERT INTO "{table}" VALUES (?)',
                        [
                            (
                                json.dumps(
                                    row,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    default=str,
                                ),
                            )
                            for row in rows
                        ],
                    )
            connection.execute("CHECKPOINT")
    except duckdb.Error as error:
        raise ResultPackageError("detail_database_write_failed") from error


def scientific_inventory(scientific_root: Path) -> list[dict[str, Any]]:
    actual = sorted(path.name for path in scientific_root.iterdir() if path.is_file())
    if actual != sorted(SCIENTIFIC_FILES):
        raise ResultPackageError("scientific_file_inventory_mismatch", str(actual))
    return [
        {
            "relative_path": name,
            "sha256": sha256_file(scientific_root / name),
            "byte_size": (scientific_root / name).stat().st_size,
            "storage_class": "repository_local_detail"
            if name.endswith(".duckdb")
            else "compact_review",
        }
        for name in SCIENTIFIC_FILES
    ]


def write_scientific_stage(
    stage_root: Path,
    *,
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run_summary: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
    result_analysis: str,
) -> Path:
    scientific = stage_root / "scientific"
    scientific.mkdir(parents=True, exist_ok=False)
    request_identity = {
        "task_id": "R2A-T06",
        "requests": manifest["requests"],
        "score_release_id": manifest["score_release"]["score_release_id"],
        "approved_implementation_sha": manifest["approved_implementation_sha"],
        "reviewed_formal_execution_sha": manifest["reviewed_formal_execution_sha"],
    }
    _write_json(scientific / "request_identity.json", request_identity)
    _write_json(scientific / "input_manifest.json", dict(manifest))
    _write_json(scientific / "run_summary.json", dict(run_summary))
    _write_json(scientific / "validation_receipt.json", dict(validation_receipt))
    _write_text(scientific / "result_analysis.md", result_analysis)
    for filename, rows in build_scientific_tables(candidate).items():
        _write_csv(scientific / filename, rows)
    _write_detail_database(scientific / "t06_detail.duckdb", candidate)
    scientific_inventory(scientific)
    return scientific


def artifact_manifest(stage_root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(stage_root.rglob("*")):
        if path.is_file() and path.name not in {
            "artifact_manifest.json",
            "result_package.json",
        }:
            records.append(
                {
                    "relative_path": path.relative_to(stage_root).as_posix(),
                    "sha256": sha256_file(path),
                    "byte_size": path.stat().st_size,
                }
            )
    return {"task_id": "R2A-T06", "files": records}


def verify_artifact_manifest(
    stage_root: Path, manifest: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Independently re-read every sealed artifact identity before publication."""

    loaded = (
        dict(manifest)
        if manifest is not None
        else json.loads(
            (stage_root / "artifact_manifest.json").read_text(encoding="utf-8")
        )
    )
    if loaded.get("task_id") != "R2A-T06" or not isinstance(loaded.get("files"), list):
        raise ResultPackageError("artifact_manifest_invalid")
    expected_paths = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file()
        and path.name not in {"artifact_manifest.json", "result_package.json"}
    }
    registered: dict[str, Mapping[str, Any]] = {}
    for item in loaded["files"]:
        if not isinstance(item, Mapping):
            raise ResultPackageError("artifact_manifest_record_invalid")
        relative = item.get("relative_path")
        if not isinstance(relative, str) or "\\" in relative:
            raise ResultPackageError("artifact_manifest_path_invalid")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ResultPackageError("artifact_manifest_path_invalid", relative)
        if relative in registered:
            raise ResultPackageError("artifact_manifest_duplicate_path", relative)
        registered[relative] = item
    if set(registered) != expected_paths:
        raise ResultPackageError("artifact_manifest_inventory_mismatch")
    for relative, item in registered.items():
        path = stage_root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise ResultPackageError("artifact_manifest_file_missing", relative)
        if path.stat().st_size != item.get("byte_size"):
            raise ResultPackageError("artifact_manifest_byte_size_mismatch", relative)
        if sha256_file(path) != item.get("sha256"):
            raise ResultPackageError("artifact_manifest_sha256_mismatch", relative)
    return {
        "status": "passed",
        "verified_file_count": len(registered),
        "artifact_manifest_sha256": sha256_file(stage_root / "artifact_manifest.json")
        if (stage_root / "artifact_manifest.json").is_file()
        else None,
    }


def publish_stage_atomic(stage_root: Path, final_root: Path) -> None:
    if final_root.exists():
        raise ResultPackageError("run_root_collision", str(final_root))
    if not stage_root.is_dir():
        raise ResultPackageError("staging_root_missing")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage_root, final_root)


def preserve_failed_stage(stage_root: Path) -> Path | None:
    if not stage_root.exists():
        return None
    failed = stage_root.with_name(stage_root.name + ".failed")
    if failed.exists():
        raise ResultPackageError("failed_stage_collision", str(failed))
    os.replace(stage_root, failed)
    return failed


def create_stage_root(parent: Path, run_id: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".{run_id}.staging-{uuid.uuid4().hex}"
    stage.mkdir()
    return stage


__all__ = [
    "CONTROL_FILES",
    "SCIENTIFIC_FILES",
    "ResultPackageError",
    "artifact_manifest",
    "build_scientific_tables",
    "create_stage_root",
    "preserve_failed_stage",
    "publish_stage_atomic",
    "scientific_inventory",
    "verify_artifact_manifest",
    "write_scientific_stage",
]
