from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    module = import_module("src.r0.r0_t15_layer_q_vector_materialization_validator_cli")
    raise SystemExit(module.main())
