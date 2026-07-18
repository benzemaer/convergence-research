"""Post-validation scientific inspection for actual R2A-T01 package contents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb


class ResultAnalysisError(RuntimeError):
    """Raised only when the four readable package inputs do not exist or disagree."""


def analyze_score_release(package_dir: str | Path) -> Path:
    """Always write analysis for readable packages, including failed validation receipts."""

    package = Path(package_dir).resolve()
    required = (
        "score_data.duckdb",
        "manifest.json",
        "schema.json",
        "validation_receipt.json",
    )
    missing = [name for name in required if not (package / name).is_file()]
    if missing:
        raise ResultAnalysisError(f"missing_required_file:{','.join(missing)}")
    manifest = _load_json(package / "manifest.json")
    receipt = _load_json(package / "validation_receipt.json")
    _load_json(package / "schema.json")
    if receipt.get("score_release_id") != manifest.get("score_release_id"):
        raise ResultAnalysisError("receipt_manifest_release_id_mismatch")

    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        row_counts = {
            table: int(
                connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            )
            for table in (
                "securities",
                "trading_sessions",
                "security_observation_spine",
                "dimension_definitions",
                "dimension_components",
                "daily_component_scores",
                "daily_dimension_scores",
            )
        }
        coverage = connection.execute(
            "SELECT count(DISTINCT security_id),min(trading_date),max(trading_date) "
            "FROM security_observation_spine"
        ).fetchone()
        observation_status = connection.execute(
            "SELECT expected_observation_status,count(*) FROM security_observation_spine "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
        component_stats = connection.execute(
            "SELECT dimension_id,component_id,count(*),count(*) FILTER(WHERE eligible),"
            "count(*) FILTER(WHERE score IS NULL),"
            "count(*) FILTER(WHERE validity_status='valid'),"
            "count(*) FILTER(WHERE validity_status='unknown'),"
            "count(*) FILTER(WHERE validity_status='diagnostic_required'),"
            "count(*) FILTER(WHERE validity_status='blocked'),"
            "min(score) FILTER(WHERE validity_status='valid' AND score IS NOT NULL),"
            "max(score) FILTER(WHERE validity_status='valid' AND score IS NOT NULL),"
            "avg(score) FILTER(WHERE validity_status='valid' AND score IS NOT NULL) "
            "FROM daily_component_scores GROUP BY 1,2 ORDER BY 1,2"
        ).fetchall()
        dimension_stats = connection.execute(
            "SELECT dimension_id,count(*),count(*) FILTER(WHERE eligible_dimension),"
            "count(*) FILTER(WHERE score_dimension IS NULL),"
            "count(*) FILTER(WHERE validity_status='valid'),"
            "count(*) FILTER(WHERE validity_status='unknown'),"
            "count(*) FILTER(WHERE validity_status='diagnostic_required'),"
            "count(*) FILTER(WHERE validity_status='blocked'),"
            "min(score_dimension) FILTER(WHERE validity_status='valid' AND score_dimension IS NOT NULL),"
            "max(score_dimension) FILTER(WHERE validity_status='valid' AND score_dimension IS NOT NULL),"
            "avg(score_dimension) FILTER(WHERE validity_status='valid' AND score_dimension IS NOT NULL) "
            "FROM daily_dimension_scores "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
        yearly_coverage = connection.execute(
            "SELECT year(trading_date),count(*),count(*) FILTER(WHERE eligible),"
            "count(DISTINCT security_id) FROM daily_component_scores GROUP BY 1 ORDER BY 1"
        ).fetchall()
        mean_min_mismatches = int(
            connection.execute(
                "WITH r AS (SELECT score_release_id,security_id,trading_date,dimension_id,"
                "bool_and(eligible) ready,avg(score) mean_score,min(score) min_score "
                "FROM daily_component_scores GROUP BY 1,2,3,4) SELECT count(*) FROM "
                "daily_dimension_scores d JOIN r USING(score_release_id,security_id,"
                "trading_date,dimension_id) WHERE d.eligible_dimension<>r.ready OR "
                "(d.eligible_dimension AND (abs(d.score_dimension-r.mean_score)>1e-12 OR "
                "abs(d.score_dimension_min-r.min_score)>1e-12))"
            ).fetchone()[0]
        )
        availability_mismatches = int(
            connection.execute(
                "SELECT (SELECT count(*) FROM daily_component_scores c JOIN "
                "security_observation_spine s USING(score_release_id,security_id,trading_date) "
                "WHERE c.available_time<>s.observation_available_time) + "
                "(SELECT count(*) FROM daily_dimension_scores d JOIN "
                "security_observation_spine s USING(score_release_id,security_id,trading_date) "
                "WHERE d.available_time<>s.observation_available_time)"
            ).fetchone()[0]
        )
        expected_empty = connection.execute(
            "WITH expected AS (SELECT * FROM security_observation_spine WHERE "
            "expected_observation_status IN ('missing','listing_pause')) "
            "SELECT (SELECT count(*) FROM expected),"
            "(SELECT count(*) FROM daily_component_scores c JOIN expected e "
            "USING(score_release_id,security_id,trading_date) WHERE NOT eligible AND "
            "score IS NULL AND percentile IS NULL AND validity_status='blocked'),"
            "(SELECT count(*) FROM daily_dimension_scores d JOIN expected e "
            "USING(score_release_id,security_id,trading_date) WHERE NOT eligible_dimension "
            "AND score_dimension IS NULL AND score_dimension_min IS NULL "
            "AND validity_status='blocked')"
        ).fetchone()

    receipt_metrics = receipt.get("metrics", {})
    source_valid = int(receipt_metrics.get("pcvt_source_valid_rows", 0))
    output_valid = int(receipt_metrics.get("pcvt_output_valid_rows", 0))
    anomalies: list[tuple[str, str, str]] = []
    if receipt.get("status") != "passed":
        anomalies.append(
            (
                "validator_failed",
                "blocking",
                "Validation receipt failed; publication is prohibited until every failed check is explained and resolved.",
            )
        )
        for reason in receipt.get("reason_codes", []):
            anomalies.append(
                (
                    f"validator_failed:{reason}",
                    "blocking",
                    "This exact validator failure must be explained and resolved.",
                )
            )
    for row in component_stats:
        if row[4] == row[2]:
            anomalies.append(
                (
                    f"component_all_null:{row[1]}",
                    "blocking",
                    "The component has no non-NULL Score in the actual release.",
                )
            )
        if row[9] is not None and row[9] == row[10] == 0:
            anomalies.append(
                (
                    f"component_all_zero:{row[1]}",
                    "blocking",
                    "All valid scores are zero.",
                )
            )
        if row[9] is not None and row[9] == row[10] == 1:
            anomalies.append(
                (f"component_all_one:{row[1]}", "blocking", "All valid scores are one.")
            )
        if row[3] == 0:
            anomalies.append(
                (
                    f"component_eligible_zero:{row[1]}",
                    "blocking",
                    "The component has no eligible rows.",
                )
            )
        if row[5] == 0:
            anomalies.append(
                (
                    f"component_validity_no_valid:{row[1]}",
                    "blocking",
                    "The component validity distribution contains no valid rows.",
                )
            )
    for row in dimension_stats:
        if row[3] == row[1]:
            anomalies.append(
                (
                    f"dimension_all_null:{row[0]}",
                    "blocking",
                    "The dimension has no non-NULL Score in the actual release.",
                )
            )
        if row[8] is not None and row[8] == row[9] == 0:
            anomalies.append(
                (
                    f"dimension_all_zero:{row[0]}",
                    "blocking",
                    "All valid dimension scores are zero.",
                )
            )
        if row[8] is not None and row[8] == row[9] == 1:
            anomalies.append(
                (
                    f"dimension_all_one:{row[0]}",
                    "blocking",
                    "All valid dimension scores are one.",
                )
            )
        if row[2] == 0:
            anomalies.append(
                (
                    f"dimension_eligible_zero:{row[0]}",
                    "blocking",
                    "The dimension has no eligible rows.",
                )
            )
        if row[4] == 0:
            anomalies.append(
                (
                    f"dimension_validity_no_valid:{row[0]}",
                    "blocking",
                    "The dimension validity distribution contains no valid rows.",
                )
            )
    if mean_min_mismatches:
        anomalies.append(
            (
                "component_to_dimension_mismatch",
                "blocking",
                f"{mean_min_mismatches} dimension rows disagree with component mean/min.",
            )
        )
    if availability_mismatches:
        anomalies.append(
            (
                "availability_mismatch",
                "blocking",
                f"{availability_mismatches} Score rows disagree with spine availability.",
            )
        )
    if source_valid != output_valid:
        anomalies.append(
            (
                "source_coverage_drop",
                "blocking",
                f"Upstream valid PCVT rows={source_valid}, output valid rows={output_valid}.",
            )
        )
    if (
        expected_empty[1] != expected_empty[0] * 10
        or expected_empty[2] != expected_empty[0] * 5
    ):
        anomalies.append(
            (
                "expected_empty_mismatch",
                "blocking",
                "Expected-empty observations are not fully represented by blocked component and dimension rows.",
            )
        )

    analysis_status = "passed" if not anomalies else "blocked"
    recommendation = (
        "publish_candidate" if analysis_status == "passed" else "do_not_publish"
    )
    lines = [
        "# R2A-T01 result analysis",
        "",
        f"- analysis_status = `{analysis_status}`",
        f"- validator_status = `{receipt.get('status')}`",
        f"- release_recommendation = `{recommendation}`",
        f"- score_release_id = `{manifest['score_release_id']}`",
        f"- synthetic_only = `{str(manifest['synthetic_only']).lower()}`",
        "",
        "## Actual DuckDB artifact inspection",
        "",
        f"Security/date coverage: securities={coverage[0]}, date_min={coverage[1]}, date_max={coverage[2]}.",
        "",
        "### Seven-table row counts",
        "",
        "| table | rows |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {table} | {count} |" for table, count in row_counts.items())
    lines.extend(
        [
            "",
            "### Observation-status distribution",
            "",
            "| expected_observation_status | rows |",
            "| --- | ---: |",
        ]
    )
    lines.extend(f"| {status} | {count} |" for status, count in observation_status)
    lines.extend(
        [
            "",
            "### Component Score distributions",
            "",
            "| dimension | component | total_rows | eligible_rows | null_score_rows | valid_rows | unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_render_stat_row(row) for row in component_stats)
    lines.extend(
        [
            "",
            "### Dimension Score distributions",
            "",
            "| dimension | total_rows | eligible_rows | null_score_rows | valid_rows | unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_render_stat_row(row) for row in dimension_stats)
    lines.extend(
        [
            "",
            "### Yearly coverage",
            "",
            "| year | component rows | eligible rows | securities |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {year} | {rows} | {eligible} | {securities} |"
        for year, rows, eligible, securities in yearly_coverage
    )
    lines.extend(
        [
            "",
            "## Independent reconciliation evidence",
            "",
            f"- source reconciliation: PCVT source valid rows={source_valid}; output valid rows={output_valid}",
            f"- PCVT independent recomputation: samples={receipt_metrics.get('pcvt_independent_sample_count', 0)}; mismatches={receipt_metrics.get('pcvt_independent_mismatch_count', 0)}",
            f"- A independent recomputation: samples={receipt_metrics.get('a_independent_sample_count', 0)}; mismatches={receipt_metrics.get('a_independent_mismatch_count', 0)}",
            f"- component-to-dimension mean/min mismatch count: {mean_min_mismatches}",
            f"- availability mismatch count: {availability_mismatches}",
            f"- expected-empty observations={expected_empty[0]}; blocked component rows={expected_empty[1]}; blocked dimension rows={expected_empty[2]}",
            "",
            "## Anomaly register",
            "",
            "| anomaly | status | explanation |",
            "| --- | --- | --- |",
        ]
    )
    if anomalies:
        lines.extend(
            f"| {name} | {status} | {explanation} |"
            for name, status, explanation in anomalies
        )
    else:
        lines.append(
            "| none | explained | No blocking anomaly was found in the inspected package. |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Completion of the runner and validator does not complete R2A-T01. Any unexplained anomaly blocks publication, README gate advancement, formal acceptance, and R2A-T02. This analysis does not authorize a formal run.",
            "",
        ]
    )
    target = package / "result_analysis.md"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    temporary.replace(target)
    return target


def _render_stat_row(values: tuple[Any, ...]) -> str:
    return "| " + " | ".join(_render_value(value) for value in values) + " |"


def _render_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResultAnalysisError(f"json_object_required:{path.name}")
    return payload
