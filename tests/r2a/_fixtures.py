from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.r2a.r2a_t01_input_manifest import build_synthetic_input_manifest
from src.r2a.r2a_t01_score_release import materialize_score_release
from src.r2a.score_engine import COMPONENTS_BY_DIMENSION


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def synthetic_inputs(
    root: Path, *, security_ids: tuple[str, ...] = ("000001.SZ",), days: int = 123
) -> tuple[Path, dict[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    start = date(2020, 1, 1)
    last = start + timedelta(days=days - 1)
    securities = [
        {
            "security_id": security_id,
            "universe_id": "SYNTHETIC_R2A_T01",
            "first_expected_date": start.isoformat(),
            "last_expected_date": last.isoformat(),
            "expected_observation_count": days,
        }
        for security_id in security_ids
    ]
    sessions: list[dict[str, Any]] = []
    spine: list[dict[str, Any]] = []
    a_raw: list[dict[str, Any]] = []
    validation_raw: list[dict[str, Any]] = []
    raw_by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    all_components = tuple(
        component
        for dimension in ("P", "C", "V", "T")
        for component in COMPONENTS_BY_DIMENSION[dimension]
    )
    for sequence in range(days):
        trading_date = (start + timedelta(days=sequence)).isoformat()
        available = datetime.combine(
            date.fromisoformat(trading_date),
            time(15, 0),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).isoformat()
        session_present = 0 if sequence in (49, 59) else len(security_ids)
        sessions.append(
            {
                "trading_date": trading_date,
                "session_sequence": sequence,
                "expected_security_count": len(security_ids),
                "present_security_count": session_present,
                "available_time": available,
            }
        )
        for security_offset, security_id in enumerate(security_ids):
            observation_status = (
                "listing_pause"
                if sequence == 49
                else "missing"
                if sequence == 59
                else "present"
            )
            spine.append(
                {
                    "security_id": security_id,
                    "trading_date": trading_date,
                    "observation_sequence": sequence,
                    "expected_observation_status": observation_status,
                    "source_contract": "synthetic_authoritative_spine.v1",
                    "source_ref": f"synthetic:{security_id}:{trading_date}",
                    "observation_available_time": available,
                }
            )
            if observation_status != "present":
                continue
            for component_offset, component_id in enumerate(all_components):
                raw_value = float(
                    (sequence * (component_offset + 2) + security_offset) % 31
                )
                raw = {
                    "security_id": security_id,
                    "trading_date": trading_date,
                    "observation_sequence": sequence,
                    "dimension_id": next(
                        dimension
                        for dimension in ("P", "C", "V", "T")
                        if component_id in COMPONENTS_BY_DIMENSION[dimension]
                    ),
                    "component_id": component_id,
                    "raw_value": raw_value,
                    "validity_status": "valid",
                    "reason_codes": ["valid_no_blocker"],
                }
                validation_raw.append(dict(raw))
                raw_by_group[(security_id, component_id)].append(raw)
            for component_offset, component_id in enumerate(
                COMPONENTS_BY_DIMENSION["A"]
            ):
                a_raw.append(
                    {
                        "security_id": security_id,
                        "trading_date": trading_date,
                        "observation_sequence": sequence,
                        "component_id": component_id,
                        "raw_value": float(
                            (sequence * (component_offset + 3) + security_offset) % 29
                        ),
                        "validity_status": "valid",
                        "reason_codes": ["valid_no_blocker"],
                        "source_run_id": "synthetic_a_raw.v1",
                    }
                )

    components: list[dict[str, Any]] = []
    scores_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (security_id, component_id), rows in sorted(raw_by_group.items()):
        history: list[tuple[int, float]] = []
        dimension_id = str(rows[0]["dimension_id"])
        for row in rows:
            reference = history[-120:]
            raw_value = float(row["raw_value"])
            eligible = len(reference) == 120
            if eligible:
                less = sum(value < raw_value for _, value in reference)
                equal = sum(value == raw_value for _, value in reference)
                percentile = (less + 0.5 * equal) / 120
                score = 1 - percentile
                reasons = ["valid_no_blocker"]
            else:
                percentile = None
                score = None
                reasons = ["insufficient_strict_past_history"]
            output = {
                "security_id": security_id,
                "trading_date": row["trading_date"],
                "observation_sequence": row["observation_sequence"],
                "dimension_id": dimension_id,
                "component_id": component_id,
                "percentile_window_W": 120,
                "raw_value": raw_value,
                "percentile": percentile,
                "score": score,
                "eligible": eligible,
                "validity_status": "valid",
                "reason_codes": reasons,
                "reference_observation_count": len(reference),
                "reference_window_start": reference[0][0] if reference else None,
                "reference_window_end": reference[-1][0] if reference else None,
                "score_engine_version": "accepted_r0_t05_score_engine.v1",
                "source_run_id": "synthetic_r0_t05_w120",
            }
            components.append(output)
            scores_by_key[(security_id, str(row["trading_date"]), component_id)] = (
                output
            )
            history.append((int(row["observation_sequence"]), raw_value))

    for row in spine:
        if row["expected_observation_status"] == "present":
            continue
        reason = (
            "market_observation_missing"
            if row["expected_observation_status"] == "missing"
            else "security_listing_pause"
        )
        for dimension_id in ("P", "C", "V", "T"):
            for component_id in COMPONENTS_BY_DIMENSION[dimension_id]:
                components.append(
                    {
                        "security_id": row["security_id"],
                        "trading_date": row["trading_date"],
                        "observation_sequence": row["observation_sequence"],
                        "dimension_id": dimension_id,
                        "component_id": component_id,
                        "percentile_window_W": 120,
                        "raw_value": None,
                        "percentile": None,
                        "score": None,
                        "eligible": False,
                        "validity_status": "blocked",
                        "reason_codes": [reason],
                        "reference_observation_count": 0,
                        "reference_window_start": None,
                        "reference_window_end": None,
                        "score_engine_version": "accepted_r0_t05_score_engine.v1",
                        "source_run_id": "synthetic_r0_t05_w120",
                    }
                )

    dimensions: list[dict[str, Any]] = []
    for row in spine:
        if row["expected_observation_status"] != "present":
            reason = (
                "market_observation_missing"
                if row["expected_observation_status"] == "missing"
                else "security_listing_pause"
            )
            for dimension_id in ("P", "C", "V", "T"):
                dimensions.append(
                    {
                        "security_id": row["security_id"],
                        "trading_date": row["trading_date"],
                        "observation_sequence": row["observation_sequence"],
                        "dimension_id": dimension_id,
                        "percentile_window_W": 120,
                        "score_dimension": None,
                        "score_dimension_min": None,
                        "eligible_dimension": False,
                        "validity_status": "blocked",
                        "reason_codes": [reason, "component_score_missing"],
                        "score_engine_version": "accepted_r0_t05_score_engine.v1",
                    }
                )
            continue
        for dimension_id in ("P", "C", "V", "T"):
            component_rows = [
                scores_by_key[(row["security_id"], row["trading_date"], component_id)]
                for component_id in COMPONENTS_BY_DIMENSION[dimension_id]
            ]
            eligible = all(item["eligible"] for item in component_rows)
            values = [item["score"] for item in component_rows]
            dimensions.append(
                {
                    "security_id": row["security_id"],
                    "trading_date": row["trading_date"],
                    "observation_sequence": row["observation_sequence"],
                    "dimension_id": dimension_id,
                    "percentile_window_W": 120,
                    "score_dimension": sum(values) / 2 if eligible else None,
                    "score_dimension_min": min(values) if eligible else None,
                    "eligible_dimension": eligible,
                    "validity_status": "valid",
                    "reason_codes": (
                        ["valid_no_blocker"]
                        if eligible
                        else ["insufficient_strict_past_history"]
                    ),
                    "score_engine_version": "accepted_r0_t05_score_engine.v1",
                }
            )

    payloads: dict[str, Any] = {
        "securities": securities,
        "trading_sessions": sessions,
        "security_observation_spine": spine,
        "pcvt_component_scores": components,
        "pcvt_dimension_scores": dimensions,
        "a_raw_observations": a_raw,
        "pcvt_validation_raw": validation_raw,
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = root / f"{name}.json"
        write_json(path, payload)
        paths[name] = path
    manifest = root / "authorized_input_manifest.json"
    build_synthetic_input_manifest(
        output_path=manifest,
        run_id="R2A-T01-SYNTHETIC",
        synthetic_root=root,
        inputs=paths,
    )
    return manifest, paths


def build_package(
    root: Path,
    *,
    worker_count: int = 1,
    security_ids: tuple[str, ...] = ("000001.SZ",),
) -> tuple[Path, Path, dict[str, Path]]:
    manifest, paths = synthetic_inputs(root / "inputs", security_ids=security_ids)
    package = root / f"package-w{worker_count}"
    materialize_score_release(
        authorized_input_manifest=manifest,
        output_dir=package,
        run_id="R2A-T01-SYNTHETIC",
        worker_count=worker_count,
    )
    return package, manifest, paths
