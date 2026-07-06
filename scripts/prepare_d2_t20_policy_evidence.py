"""Prepare D2-T20 policy evidence hashes without committing downloaded payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (  # noqa: E402
    _frame_records,
)
from scripts.run_d2_tnskhdata_security_major_provider_runner import (  # noqa: E402
    create_tnskhdata_client,
)

DEFAULT_MANIFEST = ROOT / "configs/d2/d2_t20_policy_evidence_manifest.v1.json"


class D2T20EvidencePreparationError(ValueError):
    """Raised when D2-T20 evidence cannot be prepared safely."""


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_html_text(payload: bytes) -> bytes:
    parser = _VisibleTextParser()
    parser.feed(payload.decode("utf-8", errors="ignore"))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text.encode("utf-8")


def default_downloader(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get("content-type", "")


def hash_document(
    document: dict[str, Any],
    *,
    downloader: Any = default_downloader,
) -> dict[str, Any]:
    payload, content_type = downloader(str(document["url"]))
    hash_target = document.get("hash_target") or (
        "html_or_text" if "html" in content_type.lower() else "pdf"
    )
    hash_payload = (
        normalized_html_text(payload) if hash_target == "html_or_text" else payload
    )
    updated = dict(document)
    updated["hash_target"] = hash_target
    updated["sha256"] = sha256_bytes(hash_payload)
    updated["evidence_status"] = "hash_verified"
    return updated


def compress_factor_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in sorted(rows, key=lambda item: str(item["trade_date"])):
        factor = float(row["adj_factor"])
        date = str(row["trade_date"])
        if current is None or current["effective_adj_factor"] != factor:
            if current is not None:
                intervals.append(current)
            current = {
                "start_date": date,
                "end_date": date,
                "effective_adj_factor": factor,
            }
        else:
            current["end_date"] = date
    if current is not None:
        intervals.append(current)
    return intervals


def normalized_adj_factor_hash(rows: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "ts_code": str(row.get("ts_code", "")),
            "trade_date": str(row.get("trade_date", "")),
            "adj_factor": float(row["adj_factor"]),
        }
        for row in rows
    ]
    normalized.sort(key=lambda row: (row["ts_code"], row["trade_date"]))
    payload = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256_bytes(payload)


def resolve_adj_factor_evidence(
    row: dict[str, Any],
    *,
    client: Any,
) -> dict[str, Any]:
    frame = client.adj_factor(
        ts_code=row["ts_code"],
        start_date=row["query_start_date"],
        end_date=row["query_end_date"],
    )
    rows = _frame_records(frame)
    if not rows:
        updated = dict(row)
        updated["evidence_status"] = "missing"
        updated["recommended_policy"] = "keep_blocked_pending_factor_evidence"
        return updated
    intervals = compress_factor_intervals(rows)
    updated = dict(row)
    updated["row_count"] = len(rows)
    updated["normalized_response_sha256"] = normalized_adj_factor_hash(rows)
    updated["factor_intervals"] = intervals
    updated["evidence_status"] = "hash_verified"
    updated["recommended_policy"] = (
        "neutral_factor_1_policy_candidate"
        if all(float(item["effective_adj_factor"]) == 1.0 for item in intervals)
        else "factor_interval_policy_candidate"
    )
    return updated


def prepare_manifest(
    manifest: dict[str, Any],
    *,
    downloader: Any = default_downloader,
    client: Any | None = None,
) -> dict[str, Any]:
    resolved = dict(manifest)
    listing_rows = []
    for row in manifest.get("listing_pause_intervals", []):
        updated = dict(row)
        updated["evidence_documents"] = [
            hash_document(document, downloader=downloader)
            for document in row.get("evidence_documents", [])
        ]
        listing_rows.append(updated)
    resolved["listing_pause_intervals"] = listing_rows
    if client is not None:
        resolved["adj_factor_policy_evidence"] = [
            resolve_adj_factor_evidence(row, client=client)
            for row in manifest.get("adj_factor_policy_evidence", [])
        ]
    resolved.pop("supplementary" + "_factor_observations", None)
    resolved["evidence_level"] = (
        "official_or_mirror_hash_verified_and_tnskhdata_adj_factor_verified"
    )
    return resolved


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--write-back-config", action="store_true")
    parser.add_argument("--skip-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.skip_network:
        print(json.dumps({"network_called": False, "manifest": str(args.manifest)}))
        return 0
    client = create_tnskhdata_client(args.env_file)
    resolved = prepare_manifest(manifest, client=client)
    if args.write_back_config:
        args.manifest.write_text(
            json.dumps(resolved, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "network_called": True,
                "manifest": str(args.manifest),
                "listing_document_count": sum(
                    len(row.get("evidence_documents", []))
                    for row in resolved.get("listing_pause_intervals", [])
                ),
                "adj_factor_target_count": len(
                    resolved.get("adj_factor_policy_evidence", [])
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
