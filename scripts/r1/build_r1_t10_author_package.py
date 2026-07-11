from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r1.r1_t10_author_package import build_author_package  # noqa: E402

if __name__ == "__main__":
    result = build_author_package(ROOT)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "passed" else 1)
