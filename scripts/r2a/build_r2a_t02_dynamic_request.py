"""Build one canonical R2A-T02 dynamic-state request envelope."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.r2a.r2a_t02_request_identity import (
        DynamicRequestError,
        build_canonical_request,
        load_request_spec,
        write_canonical_request,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        spec = load_request_spec(args.spec)
        envelope = build_canonical_request(spec)
        output = write_canonical_request(args.output, envelope)
    except DynamicRequestError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"request_id={envelope['request_id']}")
    print(f"request_hash={envelope['request_hash']}")
    print(f"canonical_output={Path(output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
