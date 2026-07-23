"""Preview R2A-T06 formal metadata; authoritative writes require owner evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_formal_input_manifest import (
    authorize_candidate_manifest,
    build_candidate_manifest,
    canonical_json_bytes,
    write_immutable_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    candidate = build_candidate_manifest()
    if args.authorization is None:
        if args.output is not None:
            parser.error("--output requires a future owner --authorization")
        print(canonical_json_bytes(candidate).decode("utf-8"), end="")
        return 0
    if args.output is None:
        parser.error("--authorization requires --output")
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    payload = authorize_candidate_manifest(
        candidate,
        reviewed_formal_execution_sha=authorization["reviewed_formal_execution_sha"],
        authorization_commit_sha=authorization["authorization_commit_sha"],
        authorization_revision=authorization["authorization_revision"],
        quality_evidence={
            "run_id": authorization["quality_run_id"],
            "sha": authorization["quality_sha"],
            "status": authorization["quality_status"],
            "conclusion": authorization["quality_conclusion"],
        },
    )
    identity = write_immutable_manifest(args.output, payload)
    print(json.dumps(identity, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
