from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    module = import_module("src.r1.r1_t14_01_layer_q_response_diagnostic_validator_cli")
    raise SystemExit(module.main())
