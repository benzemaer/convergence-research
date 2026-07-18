"""Independent validation for R2A-T04 response and review artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2a.r2a_t04_charting import MANUAL_REVIEW_FIELDS

ROOT = Path(__file__).resolve().parents[2]
REVIEW_SCHEMA = ROOT / "schemas/r2a/r2a_t04_review_bundle.schema.json"


class R2AT04ValidationError(ValueError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")
        self.reason_code = reason_code


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["security_id"]), str(row["trading_date"])


def _true_sets(
    rows: Iterable[Mapping[str, Any]], field: str
) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        if row.get(field) is True:
            result[str(row["logical_request_name"])].add(_key(row))
    return result


def _assert_subset_chain(
    values: Mapping[str, set[tuple[str, str]]],
    names: Sequence[str],
    check_id: str,
) -> dict[str, Any]:
    strict = False
    for smaller, larger in zip(names, names[1:]):
        violation = values.get(smaller, set()) - values.get(larger, set())
        if violation:
            raise R2AT04ValidationError(
                check_id, f"{smaller}->{larger}:{len(violation)}"
            )
        strict = strict or values.get(smaller, set()) != values.get(larger, set())
    return {"check_id": check_id, "passed": True, "strict_change": strict}


def validate_response_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Independently validate q, K and dimension response set relations."""

    raw = _true_sets(rows, "raw_state")
    confirmed = _true_sets(rows, "confirmed_state")
    checks = [
        _assert_subset_chain(
            raw,
            (
                "Q01_PCAVT_q10_k3",
                "D05_PCAVT_q15_k3",
                "Q02_PCAVT_q20_k3",
                "Q03_PCAVT_q25_k3",
            ),
            "q_raw_subset",
        ),
        _assert_subset_chain(
            confirmed,
            (
                "Q01_PCAVT_q10_k3",
                "D05_PCAVT_q15_k3",
                "Q02_PCAVT_q20_k3",
                "Q03_PCAVT_q25_k3",
            ),
            "q_confirmed_subset",
        ),
        _assert_subset_chain(
            confirmed,
            (
                "K03_PCAVT_q15_k7",
                "K02_PCAVT_q15_k5",
                "D05_PCAVT_q15_k3",
                "K01_PCAVT_q15_k2",
            ),
            "k_confirmed_subset",
        ),
        _assert_subset_chain(
            raw,
            (
                "D05_PCAVT_q15_k3",
                "D04_PCAV_q15_k3",
                "D03_PCA_q15_k3",
                "D02_PA_q15_k3",
                "D01_P_q15_k3",
            ),
            "dimension_raw_subset",
        ),
        _assert_subset_chain(
            confirmed,
            (
                "D05_PCAVT_q15_k3",
                "D04_PCAV_q15_k3",
                "D03_PCA_q15_k3",
                "D02_PA_q15_k3",
                "D01_P_q15_k3",
            ),
            "dimension_confirmed_subset",
        ),
    ]
    by_name_key = {(str(row["logical_request_name"]), _key(row)): row for row in rows}
    k_names = (
        "K01_PCAVT_q15_k2",
        "D05_PCAVT_q15_k3",
        "K02_PCAVT_q15_k5",
        "K03_PCAVT_q15_k7",
    )
    baseline_keys = {key for name, key in by_name_key if name == "D05_PCAVT_q15_k3"}
    for name in k_names:
        actual = {key for candidate, key in by_name_key if candidate == name}
        if actual != baseline_keys:
            raise R2AT04ValidationError("k_key_set_mismatch", name)
        for key in baseline_keys:
            if by_name_key[(name, key)].get("raw_state") != by_name_key[
                ("D05_PCAVT_q15_k3", key)
            ].get("raw_state"):
                raise R2AT04ValidationError("k_raw_state_mismatch", f"{name}:{key}")
    if not all(check["strict_change"] for check in checks):
        missing = [check["check_id"] for check in checks if not check["strict_change"]]
        raise R2AT04ValidationError("response_degenerate", ",".join(missing))
    checks.append({"check_id": "k_raw_state_equality", "passed": True})
    return tuple(checks)


def validate_marginal_dimension_rows(
    baseline_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    target_dimension: str,
) -> dict[str, Any]:
    fields = (
        "q_bp",
        "main_threshold",
        "weak_threshold",
        "dimension_ready",
        "dimension_active",
    )
    baseline = {(_key(row), str(row["dimension_id"])): row for row in baseline_rows}
    candidate = {(_key(row), str(row["dimension_id"])): row for row in candidate_rows}
    if set(baseline) != set(candidate):
        raise R2AT04ValidationError("marginal_dimension_key_mismatch")
    for key, left in baseline.items():
        dimension = key[1]
        right = candidate[key]
        if dimension != target_dimension and any(
            left.get(field) != right.get(field) for field in fields
        ):
            raise R2AT04ValidationError("marginal_non_target_changed", str(key))
    baseline_active = {
        key[0]
        for key, row in baseline.items()
        if key[1] == target_dimension and row.get("dimension_active") is True
    }
    candidate_active = {
        key[0]
        for key, row in candidate.items()
        if key[1] == target_dimension and row.get("dimension_active") is True
    }
    if not baseline_active <= candidate_active:
        raise R2AT04ValidationError("marginal_target_active_not_superset")
    return {
        "check_id": f"marginal_{target_dimension}_invariance",
        "passed": True,
        "strict_target_expansion": baseline_active != candidate_active,
    }


def recompute_path_metrics(
    observations: Sequence[Mapping[str, Any]], *, anchor_index: int, horizon: int
) -> dict[str, Any]:
    """Independent observation-offset future path calculation."""

    if anchor_index < 0 or anchor_index >= len(observations) or horizon <= 0:
        raise R2AT04ValidationError("path_metric_argument_invalid")
    anchor = float(observations[anchor_index]["adj_close"])
    end = anchor_index + horizon
    if end >= len(observations):
        return {
            "horizon_available": False,
            "close_return": None,
            "mfe": None,
            "mae": None,
            "time_to_peak": None,
            "time_to_trough": None,
        }
    future = observations[anchor_index + 1 : end + 1]
    highs = [float(row["adj_high"]) for row in future]
    lows = [float(row["adj_low"]) for row in future]
    peak = max(range(len(highs)), key=lambda index: (highs[index], -index))
    trough = min(range(len(lows)), key=lambda index: (lows[index], index))
    return {
        "horizon_available": True,
        "close_return": float(observations[end]["adj_close"]) / anchor - 1.0,
        "mfe": highs[peak] / anchor - 1.0,
        "mae": lows[trough] / anchor - 1.0,
        "time_to_peak": peak + 1,
        "time_to_trough": trough + 1,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_review_bundle(bundle: Path) -> dict[str, Any]:
    """Validate the compact bundle without trusting production summaries."""

    if (bundle / "DONE").exists():
        raise R2AT04ValidationError("t04_done_forbidden")
    summary_path = bundle / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for item in summary.get("files", []):
        relative = str(item.get("relative_path", ""))
        if (
            re.match(r"^[A-Za-z]:[\\/]", relative)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise R2AT04ValidationError("absolute_path_in_bundle")
    schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(summary)
    total_bytes = 0
    for item in summary["files"]:
        relative = str(item["relative_path"])
        if re.match(r"^[A-Za-z]:[\\/]", relative) or Path(relative).is_absolute():
            raise R2AT04ValidationError("absolute_path_in_bundle")
        path = bundle / relative
        if not path.is_file() or path.stat().st_size != item["byte_size"]:
            raise R2AT04ValidationError("bundle_file_size_mismatch", relative)
        if _sha256(path) != item["sha256"]:
            raise R2AT04ValidationError("bundle_file_hash_mismatch", relative)
        total_bytes += path.stat().st_size
    if total_bytes > 60 * 1024 * 1024:
        raise R2AT04ValidationError("review_bundle_exceeds_60_mb")
    registry_path = bundle / "chart_sample_registry.csv"
    chart_rows = (
        list(csv.DictReader(registry_path.open(encoding="utf-8")))
        if registry_path.exists()
        else []
    )
    expected_chart_count = 48 if summary["bundle_mode"] == "formal_review" else None
    if expected_chart_count is not None and (
        len(chart_rows) != expected_chart_count
        or len({row["chart_path"] for row in chart_rows}) != expected_chart_count
    ):
        raise R2AT04ValidationError("chart_registry_count_mismatch")
    worksheet_path = bundle / "visual_review_worksheet.csv"
    worksheet = (
        list(csv.DictReader(worksheet_path.open(encoding="utf-8")))
        if worksheet_path.exists()
        else []
    )
    if summary["bundle_mode"] == "formal_review" and len(worksheet) != 48:
        raise R2AT04ValidationError("visual_worksheet_count_mismatch")
    for row in worksheet:
        if any(row.get(field, "") != "" for field in MANUAL_REVIEW_FIELDS):
            raise R2AT04ValidationError("manual_review_field_not_blank")
    if any(not (bundle / row["chart_path"]).is_file() for row in chart_rows):
        raise R2AT04ValidationError("chart_file_missing")
    return {
        "status": "passed",
        "file_count": len(summary["files"]),
        "chart_count": len(chart_rows),
        "total_bytes": total_bytes,
    }
