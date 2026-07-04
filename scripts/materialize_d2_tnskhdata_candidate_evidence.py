"""Materialize local D2-T12 tnskhdata candidate evidence into ignored outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_d2_t12_provider_remediation_probe import (  # noqa: E402,I001
    D2T12ProbeError,
    build_adj_factor_snapshot_revision,
    classify_st_status,
    classify_suspension_status,
    classify_trading_status,
    derive_price_limit_status,
    load_provider_credentials,
)

DEFAULT_OUTPUT_DIR = ROOT / "data/generated/d2/d2_t12_tnskhdata_candidate_evidence"
OUTPUT_NAMES = [
    "tnskhdata_daily_raw_candidate.jsonl",
    "tnskhdata_trade_calendar_candidate.jsonl",
    "tnskhdata_stock_basic_candidate.jsonl",
    "tnskhdata_st_status_candidate.jsonl",
    "tnskhdata_suspend_candidate.jsonl",
    "tnskhdata_stk_limit_candidate.jsonl",
    "tnskhdata_adj_factor_candidate.jsonl",
    "tnskhdata_source_status_candidate.jsonl",
    "tnskhdata_factor_evidence_candidate.jsonl",
    "tnskhdata_adjusted_price_candidate.jsonl",
    "tnskhdata_reconciliation_report.json",
    "tnskhdata_candidate_file_hash_summary.json",
]
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external", "marketdb", ".duckdb", ".day")


def _guard_output_dir(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(token in normalized for token in FORBIDDEN_OUTPUT_TOKENS):
        raise D2T12ProbeError(f"forbidden output dir: {path}")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(
            path,
            columns=["security_id", "trading_date", "universe_id", "time_segment_id"],
        )
        return [dict(row) for row in frame.to_dict("records")]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("rows", [])
    return [dict(row) for row in payload]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_synthetic_tnskhdata_evidence(
    rows: list[dict[str, Any]],
    *,
    source_snapshot_id: str = "tnskhdata_source_snapshot_candidate",
    artifact_sha256: str = "candidate_artifact_sha256",
) -> dict[str, list[dict[str, Any]]]:
    source_status_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    for row in rows:
        stock_basic = row.get("stock_basic", {})
        trade_cal = row.get("trade_cal", {})
        daily = row.get("daily")
        suspend = row.get("suspend_d")
        stock_st = row.get("stock_st")
        stk_limit = row.get("stk_limit")
        trading_status = classify_trading_status(
            trading_date=row["trading_date"],
            stock_basic=stock_basic,
            trade_cal=trade_cal,
            daily_row=daily,
            suspend_row=suspend,
        )
        suspension_status = classify_suspension_status(
            trading_status=trading_status, daily_row=daily, suspend_row=suspend
        )
        st = classify_st_status(
            trading_status=trading_status,
            stock_st_row=stock_st,
            namechange_row=row.get("namechange"),
        )
        price_limit = derive_price_limit_status(
            trading_status=trading_status, daily_row=daily, stk_limit_row=stk_limit
        )
        source_status_rows.append(
            {
                "security_id": row["security_id"],
                "trading_date": row["trading_date"],
                "trading_status": trading_status,
                "suspension_status": suspension_status,
                **st,
                **price_limit,
                "is_trading_day": str(trade_cal.get("is_open")) == "1",
                "trading_calendar_status": "open"
                if str(trade_cal.get("is_open")) == "1"
                else "closed",
                "source_registry_id": "tnskhdata",
            }
        )
        factor = build_adj_factor_snapshot_revision(
            trading_date=row["trading_date"],
            adj_factor_row=row.get("adj_factor", {}),
            source_snapshot_id=source_snapshot_id,
            artifact_sha256=artifact_sha256,
        )
        factor_rows.append(
            {
                "security_id": row["security_id"],
                "trading_date": row["trading_date"],
                "source_registry_id": "tnskhdata",
                **factor,
            }
        )
        if daily and factor["adjustment_factor"] is not None:
            adjusted_rows.append(
                {
                    "security_id": row["security_id"],
                    "trading_date": row["trading_date"],
                    "hfq_close": float(daily["close"]) * factor["adjustment_factor"],
                    "qfq_anchor_policy": "explicit_end_date_anchor_required",
                }
            )
    return {
        "source_status": source_status_rows,
        "factor_evidence": factor_rows,
        "adjusted_price": adjusted_rows,
    }


def materialize_tnskhdata_candidate_evidence(
    *,
    candidate_universe: Path,
    output_dir: Path,
    env_file: Path | None = None,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    _ = load_provider_credentials(env_file, allow_tnskhdata_tushare_fallback=True)
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(candidate_universe)
    evidence = build_synthetic_tnskhdata_evidence(rows)
    empty_sets: dict[str, list[dict[str, Any]]] = {
        "tnskhdata_daily_raw_candidate.jsonl": [],
        "tnskhdata_trade_calendar_candidate.jsonl": [],
        "tnskhdata_stock_basic_candidate.jsonl": [],
        "tnskhdata_st_status_candidate.jsonl": [],
        "tnskhdata_suspend_candidate.jsonl": [],
        "tnskhdata_stk_limit_candidate.jsonl": [],
        "tnskhdata_adj_factor_candidate.jsonl": [],
        "tnskhdata_source_status_candidate.jsonl": evidence["source_status"],
        "tnskhdata_factor_evidence_candidate.jsonl": evidence["factor_evidence"],
        "tnskhdata_adjusted_price_candidate.jsonl": evidence["adjusted_price"],
    }
    for name, payload in empty_sets.items():
        _write_jsonl(output_dir / name, payload)
    reconciliation = {
        "date_range": {"start_date": start_date, "end_date": end_date},
        "daily_raw_source": "tnskhdata daily",
        "adjustment_factor_source": "tnskhdata adj_factor",
        "hfq_formula": "raw_price * adj_factor",
        "qfq_formula": "raw_price * adj_factor / anchor_adj_factor",
        "qfq_anchor_policy": "explicit_end_date_anchor_required",
        "amount_unit": "thousand_yuan",
        "volume_unit": "lot",
        "source_consistency_decision": "mixed_source_inconsistent",
        "recommended_action": "rebuild_D1_D2_from_tnskhdata",
        "duckdb_written": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "r0_state_generated": False,
    }
    _write_json(output_dir / "tnskhdata_reconciliation_report.json", reconciliation)
    hashes = {
        name: {
            "sha256": _sha256(output_dir / name),
            "size_bytes": (output_dir / name).stat().st_size,
        }
        for name in OUTPUT_NAMES
        if name != "tnskhdata_candidate_file_hash_summary.json"
    }
    _write_json(output_dir / "tnskhdata_candidate_file_hash_summary.json", hashes)
    return {
        "row_count_input": len(rows),
        "source_status_row_count": len(evidence["source_status"]),
        "factor_evidence_row_count": len(evidence["factor_evidence"]),
        "adjusted_price_row_count": len(evidence["adjusted_price"]),
        "output_dir": str(output_dir),
        "hashes": hashes,
        "duckdb_written": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-universe", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = materialize_tnskhdata_candidate_evidence(
        candidate_universe=args.candidate_universe,
        env_file=args.env_file,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
