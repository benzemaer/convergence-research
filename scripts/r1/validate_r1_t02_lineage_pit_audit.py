from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r1.r1_t02_lineage_pit_audit_validator_cli import main  # noqa: E402

raise SystemExit(main())
