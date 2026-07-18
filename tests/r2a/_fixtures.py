from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
    securities = [
        {
            "security_id": security_id,
            "security_name": f"Synthetic {security_id}",
            "universe_id": "SYNTHETIC_R2A_T01",
        }
        for security_id in security_ids
    ]
    sessions = []
    spine = []
    components = []
    dimensions = []
    a_raw = []
    pcvt_dimensions = ("P", "C", "V", "T")
    for sequence in range(1, days + 1):
        trading_date = (start + timedelta(days=sequence - 1)).isoformat()
        sessions.append(
            {"trading_date": trading_date, "observation_sequence": sequence}
        )
        for security_offset, security_id in enumerate(security_ids):
            observation_status = (
                "listing_pause"
                if sequence == 50
                else "missing"
                if sequence == 60
                else "present"
            )
            spine.append(
                {
                    "security_id": security_id,
                    "trading_date": trading_date,
                    "observation_sequence": sequence,
                    "observation_status": observation_status,
                }
            )
            for indicator_offset, indicator_id in enumerate(
                COMPONENTS_BY_DIMENSION["A"]
            ):
                if observation_status == "present":
                    raw_value: float | None = float(
                        (sequence * (indicator_offset + 2) + security_offset) % 17
                    )
                    validity = "valid"
                    reasons = ["valid_no_blocker"]
                else:
                    raw_value = None
                    validity = "unknown"
                    reasons = ["listing_pause"]
                a_raw.append(
                    {
                        "security_id": security_id,
                        "trading_date": trading_date,
                        "observation_sequence": sequence,
                        "indicator_id": indicator_id,
                        "raw_value": raw_value,
                        "validity_status": validity,
                        "reason_codes": reasons,
                    }
                )
            if observation_status != "present":
                continue
            for dimension_offset, dimension_id in enumerate(pcvt_dimensions):
                component_scores = []
                for component_offset, indicator_id in enumerate(
                    COMPONENTS_BY_DIMENSION[dimension_id]
                ):
                    eligible = sequence >= 121
                    score = (
                        0.15
                        + 0.1 * dimension_offset
                        + 0.2 * component_offset
                        + 0.02 * (sequence - 121)
                        if eligible
                        else None
                    )
                    percentile = 1.0 - score if score is not None else None
                    component_scores.append(score)
                    components.append(
                        {
                            "security_id": security_id,
                            "trading_date": trading_date,
                            "indicator_id": indicator_id,
                            "percentile_window": 120,
                            "raw_value": float(sequence + component_offset),
                            "eligible": eligible,
                            "percentile": percentile,
                            "score": score,
                            "validity_status": "valid" if eligible else "unknown",
                            "reason_codes": [
                                "valid_no_blocker"
                                if eligible
                                else "insufficient_strict_past_history"
                            ],
                            "reference_observation_count": 120
                            if eligible
                            else sequence - 1,
                            "reference_sequence_start": 1 if eligible else None,
                            "reference_sequence_end": sequence - 1
                            if eligible
                            else None,
                            "source_release_id": "synthetic_r0_t05_w120",
                        }
                    )
                eligible = all(value is not None for value in component_scores)
                dimensions.append(
                    {
                        "security_id": security_id,
                        "trading_date": trading_date,
                        "dimension_id": dimension_id,
                        "percentile_window": 120,
                        "eligible_dimension": eligible,
                        "score_dimension": (
                            sum(component_scores) / 2 if eligible else None
                        ),
                        "score_dimension_min": (
                            min(component_scores) if eligible else None
                        ),
                        "validity_status": "valid" if eligible else "unknown",
                        "reason_codes": [
                            "valid_no_blocker"
                            if eligible
                            else "insufficient_strict_past_history"
                        ],
                        "source_release_id": "synthetic_r0_t05_w120",
                    }
                )

    payloads: dict[str, Any] = {
        "securities": securities,
        "trading_sessions": sessions,
        "security_observation_spine": spine,
        "pcvt_component_scores": components,
        "pcvt_dimension_scores": dimensions,
        "a_raw_observations": a_raw,
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
        score_release_id="R2A-T01-SYNTHETIC-RELEASE",
        worker_count=worker_count,
    )
    return package, manifest, paths
