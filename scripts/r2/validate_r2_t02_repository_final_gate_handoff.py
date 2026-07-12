import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t02_repository_final_gate_handoff import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
