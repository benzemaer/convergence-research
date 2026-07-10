from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .r1_t08_global_nested_null_models import (
    CONFIG_PATH,
    ROOT,
    SCHEMA_PATH,
    _test_registry,
    sha256_file,
)
from .r1_t08_null_engine import (
    derived_seed,
    deterministic_offsets,
    extreme_count,
    offset_plan_hash,
    percentile_interval,
)


class R1T08ValidationError(RuntimeError):
    pass


def validate_r1_t08_global_nested_null_models(
    *,
    output_dir: Path,
    config_path: Path = CONFIG_PATH,
    output_path: Path | None = None,
    verify_offset_plans: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    config = _load_json(config_path)
    Draft202012Validator(_load_json(SCHEMA_PATH)).validate(config)
    summary = _load_json(output_dir / "r1_t08_experiment_summary.json")
    candidates = _read_csv(output_dir / "r1_t08_candidate_registry.csv")
    tests = _read_csv(output_dir / "r1_t08_test_registry.csv")
    reconciliation = _read_csv(output_dir / "r1_t08_observed_reconciliation.csv")
    blocks = _read_csv(output_dir / "r1_t08_block_diagnostics.csv")
    offsets = _read_csv(output_dir / "r1_t08_offset_plan_diagnostics.csv")
    replicates = _read_csv(output_dir / "r1_t08_null_replicate_metrics.csv")
    results = _read_csv(output_dir / "r1_t08_null_model_results.csv")

    _check_registry(config, candidates, tests, errors)
    n_perm = int(config["permutation"]["N_perm"])
    _check_replicates(tests, replicates, n_perm, errors)
    _check_results(tests, replicates, results, n_perm, errors)
    _check_reconciliation(reconciliation, errors)
    _check_blocks_and_offsets(blocks, offsets, n_perm, errors)
    if verify_offset_plans:
        _check_offset_plan_reproducibility(
            config, tests, blocks, offsets, replicates, errors
        )
    _check_summary(summary, output_dir, n_perm, replicates, results, errors)
    result = {
        "task_id": "R1-T08",
        "run_id": summary.get("run_id"),
        "code_commit": summary.get("code_commit"),
        "validator": "r1_t08_global_nested_null_models_validator",
        "validator_status": "passed" if not errors else "failed",
        "candidate_registry_exact": not any(
            value.startswith("candidate_registry") for value in errors
        ),
        "test_group_count": len({row["test_group_id"] for row in replicates}),
        "replicate_row_count": len(replicates),
        "result_row_count": len(results),
        "N_perm": n_perm,
        "failed_simulation_count": sum(
            _int(row["failed_flag"]) for row in replicates
        ),
        "offset_plan_reproducibility_checked": verify_offset_plans,
        "errors": errors,
    }
    target = output_path or output_dir / "r1_t08_engineering_validation_result.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if errors:
        raise R1T08ValidationError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _check_registry(
    config: Mapping[str, Any],
    candidates: Sequence[Mapping[str, str]],
    tests: Sequence[Mapping[str, str]],
    errors: list[str],
) -> None:
    expected_candidates = {
        (
            row["candidate_config_id"],
            row["state_line"],
            str(row["W"]),
            str(row["q"]),
            str(row["K"]),
            row["primary_role"],
            row["same_parameter_parent_config_id"],
            row["formal_or_sidecar"],
        )
        for row in config["candidate_registry"]
    }
    actual_candidates = {
        (
            row["candidate_config_id"],
            row["state_line"],
            row["W"],
            row["q"],
            row["K"],
            row["primary_role"],
            row["same_parameter_parent_config_id"],
            row["formal_or_sidecar"],
        )
        for row in candidates
    }
    if actual_candidates != expected_candidates:
        errors.append("candidate_registry_mismatch")
    expected_tests = {
        str(row["test_group_id"])
        for row in _test_registry(config["candidate_registry"])
    }
    actual_tests = {row["test_group_id"] for row in tests}
    if actual_tests != expected_tests or len(tests) != 10:
        errors.append("test_registry_mismatch")


def _check_replicates(
    tests: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, str]],
    n_perm: int,
    errors: list[str],
) -> None:
    expected_groups = {row["test_group_id"] for row in tests}
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["test_group_id"], []).append(row)
    if set(grouped) != expected_groups:
        errors.append("replicate_test_group_set_mismatch")
    if len(rows) != len(expected_groups) * n_perm:
        errors.append("replicate_row_count_mismatch")
    for group_id, group in grouped.items():
        ids = [_int(row["replicate_id"]) for row in group]
        if sorted(ids) != list(range(1, n_perm + 1)):
            errors.append(f"replicate_id_incomplete:{group_id}")
        if len(ids) != len(set(ids)):
            errors.append(f"replicate_id_duplicate:{group_id}")
        if any(_int(row["N_perm"]) != n_perm for row in group):
            errors.append(f"replicate_N_perm_mismatch:{group_id}")
        if any(_int(row["failed_flag"]) != 0 for row in group):
            errors.append(f"failed_replicate:{group_id}")
        if any(
            len(row["offset_plan_hash"]) != 64
            or set(row["offset_plan_hash"]) - set("0123456789abcdef")
            for row in group
        ):
            errors.append(f"offset_plan_hash_invalid:{group_id}")


def _check_results(
    tests: Sequence[Mapping[str, str]],
    replicates: Sequence[Mapping[str, str]],
    results: Sequence[Mapping[str, str]],
    n_perm: int,
    errors: list[str],
) -> None:
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in replicates:
        grouped.setdefault(row["test_group_id"], []).append(row)
    test_index = {row["test_group_id"]: row for row in tests}
    expected_row_count = sum(
        4 if row["null_model_role"] == "global_synchronization" else 1
        for row in tests
    )
    if len(results) != expected_row_count:
        errors.append("result_row_count_mismatch")
    seen: set[tuple[str, str]] = set()
    for result in results:
        group_id = result["test_group_id"]
        statistic = result["statistic_name"]
        key = (group_id, statistic)
        if key in seen:
            errors.append(f"result_duplicate:{group_id}:{statistic}")
        seen.add(key)
        if group_id not in grouped or group_id not in test_index:
            errors.append(f"result_unknown_group:{group_id}")
            continue
        expected_tail = "lower" if statistic == "fragment_rate" else "upper"
        if result["tail"] != expected_tail:
            errors.append(f"tail_mismatch:{group_id}:{statistic}")
        values = np.asarray(
            [_float(row[statistic]) for row in grouped[group_id]], dtype=float
        )
        observed = _float(result["observed_value"])
        mean = float(np.mean(values))
        median = float(np.median(values))
        low, high = percentile_interval(values)
        n_extreme = extreme_count(values, observed, expected_tail)
        empirical_p = (n_extreme + 1) / (n_perm + 1)
        ratio = None if mean == 0 else observed / mean
        difference = observed - mean
        sd = float(np.std(values, ddof=1))
        z_score = None if sd == 0 else difference / sd
        checks = {
            "null_mean": mean,
            "null_median": median,
            "null_interval_low": low,
            "null_interval_high": high,
            "observed_null_ratio": ratio,
            "observed_null_difference": difference,
            "empirical_p": empirical_p,
            "z_score_descriptive": z_score,
        }
        for field, expected in checks.items():
            if not _optional_close(result[field], expected):
                errors.append(f"result_recompute_mismatch:{group_id}:{statistic}:{field}")
        if _int(result["n_extreme"]) != n_extreme:
            errors.append(f"n_extreme_mismatch:{group_id}:{statistic}")
        if _int(result["failed_simulation_count"]) != 0:
            errors.append(f"result_failed_simulation:{group_id}:{statistic}")
        if not low <= median <= high:
            errors.append(f"interval_ordering_mismatch:{group_id}:{statistic}")


def _check_reconciliation(
    rows: Sequence[Mapping[str, str]], errors: list[str]
) -> None:
    if len(rows) != 4:
        errors.append("observed_reconciliation_row_count_mismatch")
    zero_fields = (
        "missing_key_count",
        "extra_key_count",
        "raw_state_mismatch_count",
        "confirmed_state_mismatch_count",
        "interval_mismatch_count",
        "upstream_profile_mismatch_count",
        "upstream_nested_mismatch_count",
    )
    for row in rows:
        key = f"{row.get('state_line')}:{row.get('W')}"
        if any(_int(row[field]) != 0 for field in zero_fields):
            errors.append(f"observed_reconciliation_mismatch:{key}")
        if row.get("confirmation_time_consistency") != "passed":
            errors.append(f"confirmation_time_mismatch:{key}")
        if (
            _int(row["raw_state_true_count"])
            + _int(row["raw_state_false_count"])
            + _int(row["raw_state_null_count"])
            != _int(row["key_count"])
        ):
            errors.append(f"observed_funnel_mismatch:{key}")
    index = {(row["W"], row["state_line"]): row for row in rows}
    for W in ("120", "250"):
        if _int(index[(W, "S_PCVT")]["raw_state_true_count"]) > _int(
            index[(W, "S_PCT")]["raw_state_true_count"]
        ):
            errors.append(f"parent_child_invariant_mismatch:W{W}")


def _check_blocks_and_offsets(
    blocks: Sequence[Mapping[str, str]],
    offsets: Sequence[Mapping[str, str]],
    n_perm: int,
    errors: list[str],
) -> None:
    if len(blocks) != 2:
        errors.append("block_diagnostics_row_count_mismatch")
    if len(offsets) != 10:
        errors.append("offset_diagnostics_row_count_mismatch")
    block_index = {row["W"]: row for row in blocks}
    for row in blocks:
        if any(
            _int(row[field])
            for field in (
                "cross_security_violation_count",
                "cross_year_violation_count",
                "calendar_gap_inside_block_count",
                "rows_unassigned_count",
            )
        ):
            errors.append(f"block_violation:W{row['W']}")
    for row in offsets:
        if any(
            _int(row[field])
            for field in (
                "shiftable_offset_zero_count",
                "out_of_range_offset_count",
                "preservation_violation_count",
            )
        ):
            errors.append(f"offset_violation:{row['test_group_id']}")
        block = block_index[row["W"]]
        expected = (
            n_perm
            * _int(row["shifted_layer_count"])
            * _int(block["block_count"])
        )
        if _int(row["planned_block_layer_shift_count"]) != expected:
            errors.append(f"offset_plan_count_mismatch:{row['test_group_id']}")


def _check_offset_plan_reproducibility(
    config: Mapping[str, Any],
    tests: Sequence[Mapping[str, str]],
    blocks: Sequence[Mapping[str, str]],
    offsets: Sequence[Mapping[str, str]],
    replicates: Sequence[Mapping[str, str]],
    errors: list[str],
) -> None:
    block_lengths_by_w = _load_block_lengths(config)
    replicate_index = {
        (row["test_group_id"], _int(row["replicate_id"])): row
        for row in replicates
    }
    offset_index = {row["test_group_id"]: row for row in offsets}
    root_seed = int(config["permutation"]["root_seed"])
    for test in tests:
        group_id = test["test_group_id"]
        lengths = block_lengths_by_w[_int(test["W"])]
        chain = sha256()
        for replicate_id in range(1, int(config["permutation"]["N_perm"]) + 1):
            plans = []
            for layer in test["shifted_layers"].split(","):
                seed = derived_seed(
                    root_seed,
                    test["candidate_config_id"],
                    test["null_model_id"],
                    replicate_id,
                    layer,
                )
                plan = deterministic_offsets(lengths, seed)
                if np.any((lengths > 1) & ((plan == 0) | (plan >= lengths))):
                    errors.append(f"recomputed_offset_invalid:{group_id}:{replicate_id}:{layer}")
                plans.append((layer, plan))
            plan_hash = offset_plan_hash(plans)
            chain.update(bytes.fromhex(plan_hash))
            recorded_hash = replicate_index[(group_id, replicate_id)][
                "offset_plan_hash"
            ]
            if recorded_hash != plan_hash:
                errors.append(f"offset_hash_mismatch:{group_id}:{replicate_id}")
        if offset_index[group_id]["offset_plan_chain_sha256"] != chain.hexdigest():
            errors.append(f"offset_chain_hash_mismatch:{group_id}")
    block_index = {int(row["W"]): row for row in blocks}
    for W, lengths in block_lengths_by_w.items():
        if len(lengths) != _int(block_index[W]["block_count"]):
            errors.append(f"recomputed_block_count_mismatch:W{W}")
        if np.count_nonzero(lengths == 1) != _int(
            block_index[W]["singleton_unshiftable_block_count"]
        ):
            errors.append(f"recomputed_singleton_count_mismatch:W{W}")


def _load_block_lengths(config: Mapping[str, Any]) -> dict[int, np.ndarray]:
    import duckdb  # noqa: PLC0415

    path = ROOT / config["input_artifacts"]["nested_daily_state"]["path"]
    con = duckdb.connect(str(path), read_only=True)
    output: dict[int, np.ndarray] = {}
    for W in (120, 250):
        lengths = con.execute(
            """
            WITH calendar AS (
              SELECT trading_date,
                row_number() OVER (ORDER BY trading_date) AS ordinal
              FROM (SELECT DISTINCT trading_date FROM r0_t06_nested_daily_state_results)
            ), base AS (
              SELECT n.security_id, n.trading_date,
                substr(n.trading_date,1,4) AS year, c.ordinal,
                lag(c.ordinal) OVER (
                  PARTITION BY n.security_id, substr(n.trading_date,1,4)
                  ORDER BY n.trading_date
                ) AS previous_ordinal
              FROM r0_t06_nested_daily_state_results n
              JOIN calendar c USING (trading_date)
              WHERE n.percentile_window_W=? AND abs(n.q-0.2)<1e-12
            ), marked AS (
              SELECT *, sum(CASE WHEN previous_ordinal IS NULL
                                  OR ordinal-previous_ordinal<>1 THEN 1 ELSE 0 END)
                OVER (PARTITION BY security_id, year ORDER BY trading_date)
                AS segment_id
              FROM base
            )
            SELECT count(*)::BIGINT AS block_length
            FROM marked
            GROUP BY security_id, year, segment_id
            ORDER BY security_id, year, segment_id
            """,
            [W],
        ).fetchnumpy()["block_length"]
        output[W] = np.asarray(lengths, dtype=np.int64)
    con.close()
    return output


def _check_summary(
    summary: Mapping[str, Any],
    output_dir: Path,
    n_perm: int,
    replicates: Sequence[Mapping[str, str]],
    results: Sequence[Mapping[str, str]],
    errors: list[str],
) -> None:
    if summary.get("task_id") != "R1-T08":
        errors.append("summary_task_id_mismatch")
    if _int(summary.get("N_perm")) != n_perm:
        errors.append("summary_N_perm_mismatch")
    if _int(summary.get("replicate_row_count")) != len(replicates):
        errors.append("summary_replicate_row_count_mismatch")
    if summary.get("root_seed") != 2026071008:
        errors.append("summary_root_seed_mismatch")
    versions = summary.get("runtime_dependency_versions", {})
    if not versions.get("numpy_version") or not versions.get("duckdb_version"):
        errors.append("summary_dependency_versions_missing")
    for item in summary.get("output_paths", {}).values():
        path = ROOT / item["path"]
        if not path.exists() or sha256_file(path) != item["sha256"]:
            errors.append(f"summary_output_hash_mismatch:{item.get('path')}")
    if len(results) != 22:
        errors.append("summary_expected_result_contract_mismatch")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise R1T08ValidationError(f"expected JSON object: {path}")
    return value


def _int(value: Any) -> int:
    return int(value)


def _float(value: Any) -> float:
    return float(value)


def _optional_close(
    value: Any, expected: float | None, tolerance: float = 1e-12
) -> bool:
    if expected is None:
        return value in (None, "")
    if value in (None, ""):
        return False
    return abs(float(value) - expected) <= tolerance
