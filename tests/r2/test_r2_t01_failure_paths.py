import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t01_author_package import build_author_package
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

    def test_final_gate_package_hash_mismatch_fails_closed(self):
        base = ROOT / "data/generated/r2/r2_t01"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            cfg = load_config(CONFIG)
            final_validation = json.loads(
                (ROOT / cfg["inputs"]["final_gate_validation_path"]).read_text(
                    encoding="utf-8"
                )
            )
            final_validation["final_gate_package_sha256"] = "0" * 64
            validation_path = Path(tmp) / "final_validation.json"
            validation_path.write_text(
                json.dumps(final_validation, ensure_ascii=False),
                encoding="utf-8",
            )
            cfg["inputs"]["final_gate_validation_path"] = str(
                validation_path.resolve().relative_to(ROOT)
            ).replace("\\", "/")
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with self.assertRaises(Exception) as ctx:
                build_run(cfg_path, Path(tmp) / "R2-T01-20260711T0106Z")
            self.assertIn("input_final_gate_package_sha_check", str(ctx.exception))

    def test_handoff_matrix_hash_mismatch_fails_closed(self):
        base = ROOT / "data/generated/r2/r2_t01"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            cfg = load_config(CONFIG)
            handoff = json.loads(
                (ROOT / cfg["inputs"]["handoff_manifest_path"]).read_text(
                    encoding="utf-8"
                )
            )
            handoff["matrix_sha256"] = "0" * 64
            handoff_path = Path(tmp) / "handoff.json"
            handoff_path.write_text(
                json.dumps(handoff, ensure_ascii=False), encoding="utf-8"
            )
            cfg["inputs"]["handoff_manifest_path"] = str(
                handoff_path.resolve().relative_to(ROOT)
            ).replace("\\", "/")
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with self.assertRaises(Exception) as ctx:
                build_run(cfg_path, Path(tmp) / "R2-T01-20260711T0107Z")
            self.assertIn("input_handoff_matrix_sha_check", str(ctx.exception))

    def test_formal_evidence_records_config_hash(self):
        base = ROOT / "data/generated/r2/r2_t01"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            out = Path(tmp) / "R2-T01-20260711T0108Z"
            build_run(CONFIG, out)
            validate_output(out, CONFIG)
            build_author_package(out)
            evidence = (out / "r2_t01_evidence.md").read_text(encoding="utf-8")
        self.assertNotIn("config_hash`: None", evidence)
        self.assertIn("input_paths_and_hashes", evidence)
        self.assertIn("output_paths_and_hashes", evidence)


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
