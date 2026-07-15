"""Thin CLI for the future EXP-C01 formal run.

This entrypoint is intentionally fail-closed.  It requires an explicit reviewed
implementation SHA and ``--allow-formal-run``; implementation review never calls
this script against the repository's local-only DuckDB files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_c01_c_layer_ablation import (  # noqa: E402
    C1_ID,
    C2_ID,
    CSV_FIELDS,
    OUTPUT_FILES,
    TASK_ID,
    VARIANT_IDS,
    WEAK_DELTA,
    Q,
    W,
    build_profiles,
)
from src.sidecar.exp_c01_c_layer_ablation_validator import (  # noqa: E402
    EXPECTED_VARIANT_RULES,
    build_input_availability_summary,
    read_csv_artifact,
    scan_anomalies,
    validate_indicator_score_rows,
    validate_output_directory,
)

DEFAULT_CONFIG = (
    ROOT / "configs" / "sidecar" / "exp_c01_c_layer_indicator_ablation_w120.v1.json"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_formal(args)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"task_id": TASK_ID, "status": "failed", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


def run_formal(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_formal_run:
        raise RuntimeError("formal_run_not_allowed_without_--allow-formal-run")
    reviewed_sha = str(args.reviewed_implementation_sha or "")
    if not SHA_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError(
            "reviewed_implementation_sha must be an exact 40-character SHA"
        )

    config_path = Path(args.config).resolve()
    config = _load_json(config_path)
    _assert_config_scope(config)
    current_sha = _current_git_sha(config_path.parent)
    if current_sha != reviewed_sha:
        raise RuntimeError(
            "current HEAD does not equal reviewed_implementation_sha; "
            f"current={current_sha} reviewed={reviewed_sha}"
        )

    input_root_value = args.input_root or os.environ.get(
        "CONVERGENCE_RESEARCH_INPUT_ROOT"
    )
    if not input_root_value:
        raise RuntimeError(
            "--input-root or CONVERGENCE_RESEARCH_INPUT_ROOT is required"
        )
    input_root = Path(input_root_value).resolve()
    if not input_root.is_dir():
        raise RuntimeError(f"input root is not a directory: {input_root}")

    run_id = str(args.run_id)
    if not run_id or Path(run_id).name != run_id:
        raise RuntimeError("run-id must be a non-empty single path component")
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"output directory must be new and empty: {output_root}")

    started_at = _utc_now()
    paths, input_manifest = resolve_input_paths(
        input_root,
        config,
        manifest_path=Path(args.input_manifest).resolve()
        if args.input_manifest
        else None,
    )
    indicator_rows = load_indicator_rows(paths["indicator_score"], config)
    dimension_rows = load_dimension_score_rows(paths["dimension_score"], config)
    state_rows = load_dimension_state_rows(paths["dimension_state"], config)
    input_validation_errors = validate_indicator_score_rows(indicator_rows)
    if input_validation_errors:
        raise RuntimeError(
            "indicator score input validation failed: "
            + ", ".join(input_validation_errors[:20])
        )
    input_availability = build_input_availability_summary(indicator_rows)
    input_metadata = {
        key: {
            "path": str(path),
            "sha256": sha256_file(path),
            "row_count": len(rows),
        }
        for key, path, rows in (
            ("indicator_score", paths["indicator_score"], indicator_rows),
            ("dimension_score", paths["dimension_score"], dimension_rows),
            ("dimension_state", paths["dimension_state"], state_rows),
        )
    }

    profiles = build_profiles(
        indicator_rows,
        dimension_score_rows=dimension_rows,
        dimension_state_rows=state_rows,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    for key in CSV_FIELDS:
        write_csv(output_root / OUTPUT_FILES[key], CSV_FIELDS[key], profiles[key])

    # Read the just-written artifacts back before producing analysis.  This keeps
    # the result analysis tied to the actual files, not only in-memory objects.
    actual_artifacts = {
        key: read_csv_artifact(output_root / OUTPUT_FILES[key]) for key in CSV_FIELDS
    }
    write_text(
        output_root / OUTPUT_FILES["result_analysis"],
        build_result_analysis(actual_artifacts, validation_status="pending"),
    )
    manifest = build_manifest(
        output_root=output_root,
        run_id=run_id,
        config_path=config_path,
        config=config,
        input_manifest=input_manifest,
        input_metadata=input_metadata,
        input_availability=input_availability,
        reconciliation=profiles["baseline_reconciliation"],
        implementation_sha=reviewed_sha,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    write_json(output_root / OUTPUT_FILES["manifest"], manifest)

    first_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=False,
    )
    actual_artifacts = {
        key: read_csv_artifact(output_root / OUTPUT_FILES[key]) for key in CSV_FIELDS
    }
    write_text(
        output_root / OUTPUT_FILES["result_analysis"],
        build_result_analysis(
            actual_artifacts,
            validation_status=first_validation["status"],
        ),
    )
    manifest = build_manifest(
        output_root=output_root,
        run_id=run_id,
        config_path=config_path,
        config=config,
        input_manifest=input_manifest,
        input_metadata=input_metadata,
        input_availability=input_availability,
        reconciliation=profiles["baseline_reconciliation"],
        implementation_sha=reviewed_sha,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    write_json(output_root / OUTPUT_FILES["manifest"], manifest)
    validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=False,
    )
    anomaly_scan = scan_anomalies(actual_artifacts, manifest)
    write_json(output_root / OUTPUT_FILES["validator_result"], validation)
    write_json(output_root / OUTPUT_FILES["anomaly_scan"], anomaly_scan)
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": validation["status"],
        "output_root": str(output_root),
        "formal_run_executed": True,
        "anomaly_status": anomaly_scan["status"],
        "errors": validation["errors"],
    }


def resolve_input_paths(
    input_root: Path,
    config: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    manifest = (
        _load_json(manifest_path)
        if manifest_path
        else _find_input_manifest(input_root, config)
    )
    paths: dict[str, Path] = {}
    for name, artifact in config["input_contract"]["artifacts"].items():
        filename = str(artifact["filename"])
        from_manifest = _find_filename_in_json(manifest, filename) if manifest else None
        if from_manifest:
            candidate = Path(from_manifest)
            if not candidate.is_file():
                candidate = input_root / filename
        else:
            candidate = input_root / filename
        if not candidate.is_file():
            matches = sorted(input_root.rglob(filename))
            if len(matches) != 1:
                raise RuntimeError(
                    f"cannot resolve unique {name} input under {input_root}: "
                    f"{[str(item) for item in matches]}"
                )
            candidate = matches[0]
        paths[name] = candidate.resolve()
    return paths, manifest or {}


def load_indicator_rows(path: Path, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["indicator_score"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "indicator_id",
        "score",
        "eligible",
        "validity_status",
    )
    rows = _query_duckdb(
        path,
        artifact["table"],
        columns,
        "percentile_window_W = ? AND indicator_id IN (?, ?)",
        [W, C1_ID, C2_ID],
    )
    return rows


def load_dimension_score_rows(
    path: Path, config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["dimension_score"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "dimension",
        "score_dimension",
        "score_dimension_min",
        "eligible_dimension",
        "validity_status",
    )
    return _query_duckdb(
        path,
        artifact["table"],
        columns,
        "percentile_window_W = ? AND dimension = ?",
        [W, "C"],
    )


def load_dimension_state_rows(
    path: Path, config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["dimension_state"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "q",
        "weak_delta",
        "dimension",
        "dimension_active_weak",
        "validity_status",
    )
    return _query_duckdb(
        path,
        artifact["table"],
        columns,
        (
            "percentile_window_W = ? AND q = ? AND "
            "abs(weak_delta - ?) < 1e-12 AND dimension = ?"
        ),
        [W, Q, WEAK_DELTA, "C"],
    )


def build_manifest(
    *,
    output_root: Path,
    run_id: str,
    config_path: Path,
    config: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_metadata: Mapping[str, Mapping[str, Any]],
    input_availability: Mapping[str, Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
    implementation_sha: str,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    files = {}
    for key in (
        "variant_profile",
        "overlap_profile",
        "score_comparison",
        "year_profile",
        "security_profile",
        "availability_profile",
        "result_analysis",
    ):
        path = output_root / OUTPUT_FILES[key]
        files[path.name] = {
            "path": path.name,
            "sha256": sha256_file(path),
            "row_count": file_row_count(path),
        }
    return {
        "schema_version": "exp_c01_manifest.v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "implementation_sha": implementation_sha,
        "workflow_mode": "same_pr",
        "phase": "formal_run",
        "parameters": {"W": W, "q": Q, "weak_delta": WEAK_DELTA},
        "variants": list(VARIANT_IDS),
        "variant_rules": dict(EXPECTED_VARIANT_RULES),
        "denominator_scope": "pair_common_valid",
        "input_manifest": input_manifest,
        "input_artifacts": dict(input_metadata),
        "input_availability": dict(input_availability),
        "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
        "baseline_reconciliation": dict(reconciliation),
        "files": files,
        "execution": {
            "started_at": started_at,
            "finished_at": finished_at,
            "parallel_mode": "single_threaded",
            "worker_count": 1,
            "random_seed": None,
            "input_root": str(input_metadata["indicator_score"]["path"]),
            "config_version": config.get("config_version"),
        },
        "prohibited_outputs": [
            "future_return",
            "future_volatility",
            "future_direction",
            "release_label",
            "path_label",
            "backtest",
            "portfolio",
            "transaction_cost",
            "selected_indicator",
            "winner",
            "replacement_approved",
            "C_v2",
        ],
    }


def build_result_analysis(
    artifacts: Mapping[str, tuple[tuple[str, ...], list[dict[str, str]]]],
    *,
    validation_status: str,
) -> str:
    variant_rows = artifacts["variant_profile"][1]
    overlap_rows = artifacts["overlap_profile"][1]
    score_rows = artifacts["score_comparison"][1]
    availability_rows = artifacts["availability_profile"][1]
    lines = [
        "# EXP-C01 结果分析",
        "",
        (
            "本文件只允许描述当前 C1/C2 指标状态身份、可用性、持续性和稳定性；"
            "不作未来结果、交易表现或指标替换结论。"
        ),
        "",
        f"工程 validator 状态：`{validation_status}`。",
        "",
        "## 固定口径",
        "",
        (
            "W=120、q=0.20、weak_delta=0.10；主比较 denominator 为 "
            "`pair_common_valid`。三种 variant 固定为 `baseline_pair`、"
            "`c1_only`、`c2_only`。"
        ),
        "",
        "## Variant 概况",
        "",
    ]
    for row in variant_rows:
        lines.append(
            f"- `{row.get('variant_id')}`：valid rows={row.get('eligible_row_count')}，"
            f"active true={row.get('active_true_count')}，"
            f"active rate={row.get('active_rate')}，"
            f"segments={row.get('segment_count')}。"
        )
    lines.extend(["", "## 身份重合", ""])
    for row in overlap_rows:
        lines.append(
            f"- `{row.get('left_variant')}` vs `{row.get('right_variant')}`："
            f"Jaccard={row.get('jaccard')}，"
            f"baseline retention={row.get('baseline_retention')}，"
            f"candidate precision={row.get('candidate_precision')}，"
            f"symmetric difference rate={row.get('symmetric_difference_rate')}。"
        )
    lines.extend(["", "## 分数关系", ""])
    for row in score_rows:
        lines.append(
            f"- `{row.get('comparison_id')}`："
            f"pooled Spearman={row.get('pooled_spearman')}，"
            "median absolute difference="
            f"{row.get('median_absolute_score_difference')}。"
        )
    lines.extend(["", "## Availability sidecar", ""])
    for row in availability_rows:
        lines.append(
            f"- `{row.get('indicator_id')}`："
            f"native valid={row.get('native_valid_count')}，"
            f"pair common-valid={row.get('pair_common_valid_count')}，"
            f"gain vs pair={row.get('availability_gain_vs_pair')}。"
        )
    lines.extend(
        [
            "",
            "## 审阅边界",
            "",
            (
                "R1-T05 redundancy reference（pooled Spearman≥0.95、Jaccard≥0.90、"
                "双向条件重合下界≥0.95）只能作为描述性参照。runner 不选择 winner、"
                "不删除指标、不生成 C v2，也不推进主线任务。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_csv(
    path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip("\n") + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_row_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        _headers, rows = read_csv_artifact(path)
        return len(rows)
    return len(path.read_text(encoding="utf-8").splitlines())


def _query_duckdb(
    path: Path,
    table: str,
    columns: Sequence[str],
    where_clause: str,
    parameters: Sequence[Any],
) -> list[dict[str, Any]]:
    import duckdb

    _assert_identifier(table)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        query = (
            f"SELECT {quoted_columns} FROM {_quote_identifier(table)} "
            f"WHERE {where_clause} ORDER BY security_id, trading_date"
        )
        cursor = connection.execute(query, list(parameters))
        names = [str(item[0]) for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _find_input_manifest(
    input_root: Path, config: Mapping[str, Any]
) -> dict[str, Any] | None:
    names = config["input_contract"]["manifest_filenames"]
    candidates = [input_root / str(name) for name in names]
    for candidate in candidates:
        if candidate.is_file():
            return _load_json(candidate)
    for name in names:
        matches = sorted(input_root.rglob(str(name)))
        if len(matches) == 1:
            return _load_json(matches[0])
        if len(matches) > 1:
            raise RuntimeError(f"multiple input manifests found for {name}: {matches}")
    return None


def _find_filename_in_json(value: Any, filename: str) -> str | None:
    if isinstance(value, Mapping):
        for nested in value.values():
            found = _find_filename_in_json(nested, filename)
            if found:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for nested in value:
            found = _find_filename_in_json(nested, filename)
            if found:
                return found
    elif isinstance(value, str) and Path(value).name == filename:
        return value
    return None


def _assert_config_scope(config: Mapping[str, Any]) -> None:
    if config.get("task_id") != TASK_ID:
        raise RuntimeError("config task_id mismatch")
    parameters = config.get("parameters", {})
    if parameters.get("W") != W or float(parameters.get("q")) != Q:
        raise RuntimeError("config must be W=120 and q=0.20")
    if float(parameters.get("weak_delta")) != WEAK_DELTA:
        raise RuntimeError("config weak_delta must be 0.10")
    if config.get("variants") is None or [
        row.get("variant_id") for row in config["variants"]
    ] != list(VARIANT_IDS):
        raise RuntimeError("config variant set mismatch")


def _current_git_sha(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value


def _assert_identifier(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f"unsafe SQL identifier: {value}")


def _quote_identifier(value: str) -> str:
    _assert_identifier(value)
    return f'"{value}"'


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
