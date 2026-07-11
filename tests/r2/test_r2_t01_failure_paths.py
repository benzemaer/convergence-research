import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t01_candidate_convergence_shortlist import build_run, load_config
from src.r2.r2_t01_candidate_convergence_shortlist_validator import validate_output

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"


class R2T01FailurePaths(unittest.TestCase):
    def test_missing_source_row_fails_builder_input_cardinality(self):
        base = ROOT / "data/generated/r2/r2_t01"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            cfg = load_config(CONFIG)
            source = ROOT / cfg["inputs"]["decision_matrix_path"]
            matrix = Path(tmp) / "matrix.csv"
            rows = _read(source)
            _write(matrix, rows[:-1])
            cfg["inputs"]["decision_matrix_path"] = str(
                matrix.resolve().relative_to(ROOT)
            ).replace("\\", "/")
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with self.assertRaises(Exception) as ctx:
                build_run(cfg_path, Path(tmp) / "R2-T01-20260711T0105Z")
            self.assertIn("input_matrix_cardinality_check", str(ctx.exception))

    def test_illegal_extra_future_field_fails_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "R2-T01-20260711T0104Z"
            build_run(CONFIG, out)
            path = out / "r2_t01_shortlist_registry.csv"
            rows = _read(path)
            rows[0]["future_return"] = "0.1"
            _write(path, rows)
            with self.assertRaises(RuntimeError) as ctx:
                validate_output(out, CONFIG)
            self.assertIn("schema", str(ctx.exception))


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
