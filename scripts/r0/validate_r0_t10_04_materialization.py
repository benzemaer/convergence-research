from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.r0.r0_t10_confirmation_interval_materialization_validator_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
