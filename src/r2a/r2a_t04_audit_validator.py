"""Independent validation for R2A-T04 Score-only review artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
REVIEW_SCHEMA = ROOT / "schemas/r2a/r2a_t04_review_bundle.schema.json"
REQUIRED_COMPACT_FILES = {
    "request_metrics.csv",
    "year_metrics.csv",
    "termination_metrics.csv",
    "response_checks.csv",
    "interval_structure_summary.csv",
    "interval_samples.csv",
    "score_dimension_endpoint_summary.csv",
    "score_component_endpoint_summary.csv",
    "request_output_profiles.json",
    "request_panel.json",
    "score_source_identity.json",
    "validation_receipt.json",
    "result_analysis.md",
}
FORBIDDEN_KEYS = {
    "market_source",
    "market_source_id",
    "chart_worker_count",
    "chart_count",
    "chart_path",
    "owner_visual_review",
    "future_horizons",
    "interval_path_metrics",
    "worksheet",
}


class R2AT04ValidationError(ValueError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")
        self.reason_code = reason_code


def recompute_path_metrics(*_args: object, **_kwargs: object) -> dict[str, Any]:
    """Fail closed for the superseded review CLI's legacy compatibility import."""

    raise R2AT04ValidationError("legacy_non_score_review_removed")


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
    """Independently validate q, K and dimension response relations."""

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
    baseline_keys = {key for name, key in by_name_key if name == k_names[1]}
    for name in k_names:
        actual = {key for candidate, key in by_name_key if candidate == name}
        if actual != baseline_keys:
            raise R2AT04ValidationError("k_key_set_mismatch", name)
        for key in baseline_keys:
            if by_name_key[(name, key)].get("raw_state") != by_name_key[
                (k_names[1], key)
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
        right = candidate[key]
        if key[1] != target_dimension and any(
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _has_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("/"))
    if isinstance(value, Mapping):
        return any(_has_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_absolute_path(item) for item in value)
    return False


def _forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in FORBIDDEN_KEYS:
                found.add(str(key))
            found.update(_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys(item))
    return found


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_review_bundle(bundle: Path) -> dict[str, Any]:
    """Validate exact file inventory, identities, samples and Score-only boundary."""

    if (bundle / "DONE").exists():
        raise R2AT04ValidationError("t04_done_forbidden")
    summary_path = bundle / "run_summary.json"
    if not summary_path.is_file():
        raise R2AT04ValidationError("run_summary_missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(summary)
    except ValidationError as error:
        raise R2AT04ValidationError("review_bundle_schema_invalid") from error
    if _has_absolute_path(summary):
        raise R2AT04ValidationError("absolute_path_in_bundle")
    forbidden = _forbidden_keys(summary)
    if forbidden:
        raise R2AT04ValidationError(
            "forbidden_score_bundle_field", ",".join(sorted(forbidden))
        )
    registry = summary["files"]
    registered = {str(item["relative_path"]) for item in registry}
    if registered != REQUIRED_COMPACT_FILES:
        raise R2AT04ValidationError("review_bundle_file_inventory_mismatch")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "run_summary.json"
    }
    if actual != REQUIRED_COMPACT_FILES:
        raise R2AT04ValidationError("review_bundle_actual_inventory_mismatch")
    total_bytes = summary_path.stat().st_size
    for item in registry:
        relative = str(item["relative_path"])
        path = bundle / relative
        if (
            not path.is_file()
            or path.stat().st_size != item["byte_size"]
            or _sha256(path) != item["sha256"]
        ):
            raise R2AT04ValidationError("review_bundle_file_identity_mismatch")
        if path.suffix == ".json":
            artifact = json.loads(path.read_text(encoding="utf-8"))
            artifact_forbidden = _forbidden_keys(artifact)
            if artifact_forbidden:
                raise R2AT04ValidationError(
                    "forbidden_score_bundle_field",
                    ",".join(sorted(artifact_forbidden)),
                )
            if _has_absolute_path(artifact):
                raise R2AT04ValidationError("absolute_path_in_bundle")
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                headers = set(csv.DictReader(handle).fieldnames or [])
            artifact_forbidden = headers & FORBIDDEN_KEYS
            if artifact_forbidden:
                raise R2AT04ValidationError(
                    "forbidden_score_bundle_field",
                    ",".join(sorted(artifact_forbidden)),
                )
        total_bytes += path.stat().st_size
    if total_bytes > 60 * 1024 * 1024:
        raise R2AT04ValidationError("review_bundle_exceeds_60_mb")
    profiles = json.loads(
        (bundle / "request_output_profiles.json").read_text(encoding="utf-8")
    )
    if not isinstance(profiles, dict) or len(profiles) != 16:
        raise R2AT04ValidationError("request_output_profiles_count_mismatch")
    sample_rows = _csv_rows(bundle / "interval_samples.csv")
    sample_counts = Counter(row["logical_request_name"] for row in sample_rows)
    if any(count > 20 for count in sample_counts.values()):
        raise R2AT04ValidationError("interval_sample_count_exceeded")
    for row in sample_rows:
        expected = hashlib.sha256(
            (
                f"{row['request_hash']}:{row['security_id']}:"
                f"{row['confirmation_date']}:{row['interval_ordinal']}"
            ).encode()
        ).hexdigest()
        if row["sample_hash"] != expected:
            raise R2AT04ValidationError("interval_sample_hash_mismatch")
    for filename, keys in (
        (
            "score_dimension_endpoint_summary.csv",
            ("logical_request_name", "anchor_type", "dimension_id"),
        ),
        (
            "score_component_endpoint_summary.csv",
            (
                "logical_request_name",
                "anchor_type",
                "dimension_id",
                "component_id",
            ),
        ),
    ):
        rows = _csv_rows(bundle / filename)
        identities = [tuple(row[key] for key in keys) for row in rows]
        if len(identities) != len(set(identities)):
            raise R2AT04ValidationError("score_endpoint_summary_key_not_unique")
    return {
        "status": "passed",
        "request_count": 16,
        "file_count": len(REQUIRED_COMPACT_FILES) + 1,
        "interval_sample_count": len(sample_rows),
        "total_bytes": total_bytes,
    }
