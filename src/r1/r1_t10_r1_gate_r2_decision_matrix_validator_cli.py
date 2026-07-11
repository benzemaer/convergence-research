from __future__ import annotations

import argparse
import json
from pathlib import Path

from .r1_t10_r1_gate_r2_decision_matrix import dump
from .r1_t10_r1_gate_r2_decision_matrix_validator import validate


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = Path(a.output).resolve()
    result = validate(out)
    dump(out / "r1_t10_engineering_validation_result.json", result)
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
