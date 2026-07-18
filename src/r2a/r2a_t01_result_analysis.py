"""Post-validation analysis for actual R2A-T01 release artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb


class ResultAnalysisError(RuntimeError):
    """Raised when analysis would be detached from validated actual results."""


def analyze_score_release(package_dir: str | Path) -> Path:
    """Reopen DuckDB, manifest, and receipt and write evidence-based Markdown."""

    package = Path(package_dir)
    manifest = _load_json(package / "manifest.json")
    receipt = _load_json(package / "validation_receipt.json")
    if receipt.get("status") != "passed":
        raise ResultAnalysisError("validation_receipt_not_passed")
    if receipt.get("run_id") != manifest.get("run_id"):
        raise ResultAnalysisError("receipt_manifest_run_mismatch")
    if receipt.get("score_release_id") != manifest.get("score_release_id"):
        raise ResultAnalysisError("receipt_manifest_release_mismatch")

    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        row_counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in manifest["row_counts"]
        }
        component_summary = connection.execute(
            "SELECT count(*) FILTER(WHERE eligible),min(score) FILTER(WHERE eligible),"
            "max(score) FILTER(WHERE eligible),avg(score) FILTER(WHERE eligible) "
            "FROM daily_component_scores"
        ).fetchone()
        dimension_summary = connection.execute(
            "SELECT count(*) FILTER(WHERE eligible_dimension),"
            "min(score_dimension) FILTER(WHERE eligible_dimension),"
            "max(score_dimension) FILTER(WHERE eligible_dimension),"
            "avg(score_dimension) FILTER(WHERE eligible_dimension) "
            "FROM daily_dimension_scores"
        ).fetchone()
        dimension_coverage = connection.execute(
            "SELECT dimension_id,count(*) total_rows,"
            "count(*) FILTER(WHERE eligible_dimension) eligible_rows "
            "FROM daily_dimension_scores GROUP BY dimension_id ORDER BY "
            "CASE dimension_id WHEN 'P' THEN 1 WHEN 'C' THEN 2 WHEN 'A' THEN 3 "
            "WHEN 'V' THEN 4 ELSE 5 END"
        ).fetchall()
        observation_status = connection.execute(
            "SELECT observation_status,count(*) FROM security_observation_spine "
            "GROUP BY observation_status ORDER BY observation_status"
        ).fetchall()

    lines = [
        "# R2A-T01 Score Release Result Analysis",
        "",
        "## Identity",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- score_release_id: `{manifest['score_release_id']}`",
        f"- synthetic_only: `{str(manifest['synthetic_only']).lower()}`",
        f"- validation_status: `{receipt['status']}`",
        "",
        "## Actual artifact inspection",
        "",
        "| table | rows |",
        "|---|---:|",
    ]
    lines.extend(f"| {table} | {count} |" for table, count in row_counts.items())
    lines.extend(
        [
            "",
            "## Score distributions",
            "",
            "| level | eligible rows | min | max | mean |",
            "|---|---:|---:|---:|---:|",
            _summary_row("component", component_summary),
            _summary_row("dimension", dimension_summary),
            "",
            "## Dimension coverage",
            "",
            "| dimension | total rows | eligible rows |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {dimension} | {total} | {eligible} |"
        for dimension, total, eligible in dimension_coverage
    )
    lines.extend(
        [
            "",
            "## Observation-status scan",
            "",
            "| observation status | rows |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| {status} | {count} |" for status, count in observation_status)
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This report is computed from the reopened DuckDB, manifest, and passed "
            "validation receipt. It does not authorize a formal run, accept R2A-T01, "
            "or advance R2A-T02.",
            "",
        ]
    )
    target = package / "result_analysis.md"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    temporary.replace(target)
    return target


def _summary_row(label: str, values: tuple[object, ...]) -> str:
    rendered = [str(values[0])]
    rendered.extend(
        "NULL" if value is None else f"{float(value):.12g}" for value in values[1:]
    )
    return f"| {label} | {' | '.join(rendered)} |"


def _load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ResultAnalysisError(f"missing_required_file:{path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResultAnalysisError(f"json_object_required:{path.name}")
    return payload
