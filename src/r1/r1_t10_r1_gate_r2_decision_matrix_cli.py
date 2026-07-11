from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t10_r1_gate_r2_decision_matrix import build


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".")
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", required=True)
    a = p.parse_args()
    result = build(Path(a.root).resolve(), Path(a.output).resolve(), a.run_id)
    print(f"R1-T10 built {len(result['matrix'])} rows: {result['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
