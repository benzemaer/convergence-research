"""Run the R2A-T05 implementation candidate on a synthetic fixture only."""

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
    build_t05_candidate,
    candidate_to_json,
    load_t05_config,
)


def _manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise T05Error("synthetic_fixture_manifest_invalid", str(path)) from error
    if not isinstance(value, dict) or value.get("source_mode") != "synthetic_fixture":
        raise T05Error("formal_or_non_synthetic_source_rejected")
    return value


def _path(value: object, base: Path) -> Path:
    if not isinstance(value, str):
        raise T05Error("fixture_path_must_be_string")
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base / candidate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the R2A-T05 synthetic implementation candidate."
    )
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest_path = args.fixture_manifest.resolve()
        manifest = _manifest(manifest_path)
        request_values = manifest.get("request_outputs")
        if (
            not isinstance(request_values, dict)
            or tuple(request_values) != REQUEST_ORDER
        ):
            raise T05Error("synthetic_fixture_request_set_mismatch")
        request_sources = {
            name: _path(request_values[name], manifest_path.parent)
            for name in REQUEST_ORDER
        }
        score_source = _path(manifest.get("score_database"), manifest_path.parent)
        candidate = build_t05_candidate(
            request_sources=request_sources,
            score_source=score_source,
            config=load_t05_config(),
        )
        rendered = candidate_to_json(candidate)
        if args.candidate_output:
            args.candidate_output.parent.mkdir(parents=True, exist_ok=True)
            args.candidate_output.write_text(rendered + "\n", encoding="utf-8")
        if args.print_json or not args.candidate_output:
            print(rendered)
        return 0
    except T05Error as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
