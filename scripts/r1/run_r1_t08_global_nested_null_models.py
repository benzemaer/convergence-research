from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    return import_module("src.r1.r1_t08_global_nested_null_models_cli").main()


if __name__ == "__main__":
    raise SystemExit(main())
