"""Independently validate an R2A-T05 synthetic candidate JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t05_ca_exit_decomposition import (  # noqa: E402
    REQUEST_ORDER,
    T05Error,
    load_t05_config,
)
from src.r2a.r2a_t05_validator import validate_t05_result_package  # noqa: E402


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise T05Error("candidate_json_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise T05Error("candidate_json_object_required")
    return value


def _source(value: object, base: Path) -> Path:
    if not isinstance(value, str):
        raise T05Error("fixture_path_must_be_string")
    path = Path(value)
    return path if path.is_absolute() else base / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently validate an R2A-T05 synthetic candidate."
    )
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = _json(args.fixture_manifest)
        if manifest.get("source_mode") != "synthetic_fixture":
            raise T05Error("formal_or_non_synthetic_source_rejected")
        request_values = manifest.get("request_outputs")
        if (
            not isinstance(request_values, dict)
            or tuple(request_values) != REQUEST_ORDER
        ):
            raise T05Error("synthetic_fixture_request_set_mismatch")
        sources = {
            name: _source(request_values[name], args.fixture_manifest.parent)
            for name in REQUEST_ORDER
        }
        score = _source(manifest.get("score_database"), args.fixture_manifest.parent)
        receipt = validate_t05_result_package(
            _json(args.candidate),
            request_sources=sources,
            score_source=score,
            config=load_t05_config(),
        )
        rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        if args.receipt_output:
            args.receipt_output.parent.mkdir(parents=True, exist_ok=True)
            args.receipt_output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0 if receipt["status"] == "passed" else 1
    except T05Error as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
