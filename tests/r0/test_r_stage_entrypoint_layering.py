import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_R_STAGE_ENTRYPOINT_LINES = 40
IMMUTABLE_FORMAL_ENTRYPOINT_EXCEPTIONS = {
    Path("scripts/r2/validate_r2_t02_repository_final_gate_handoff.py"): 51,
}

CORE_FUNCTION_PREFIXES = (
    "validate_materialization",
    "materialize_",
    "compute_",
    "_duckdb_stats",
    "_validate_shards",
    "_indicator_strict_past_stats",
)
FORBIDDEN_IMPORT_ROOTS = {"duckdb", "gzip"}
FORBIDDEN_CONSTANTS = {
    "FORBIDDEN_FIELDS",
    "LEGACY_V1_FIELD_NAMES",
    "ACTIVE_INDICATORS",
    "DIMENSION_COMPONENTS",
    "PERCENTILE_WINDOWS",
    "RAW_METRIC_IDS",
}
ALLOWED_SCRIPT_CONSTANTS = {"ROOT"}


class RStageEntrypointLayeringTest(unittest.TestCase):
    def test_r_stage_scripts_are_thin_wrappers(self) -> None:
        script_paths = sorted(
            path
            for stage in range(7)
            for path in (ROOT / f"scripts/r{stage}").glob("*.py")
        )
        self.assertTrue(script_paths)
        for path in script_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                lines = text.splitlines()
                relative = path.relative_to(ROOT)
                limit = IMMUTABLE_FORMAL_ENTRYPOINT_EXCEPTIONS.get(
                    relative, MAX_R_STAGE_ENTRYPOINT_LINES
                )
                self.assertLessEqual(len(lines), limit)

                tree = ast.parse(text, filename=str(path))
                function_names = [
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef)
                ]
                for name in function_names:
                    self.assertFalse(
                        name.startswith(CORE_FUNCTION_PREFIXES),
                        f"{path} defines core R-stage function {name}",
                    )

                imported_roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported_roots.update(
                            alias.name.split(".", maxsplit=1)[0] for alias in node.names
                        )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_roots.add(node.module.split(".", maxsplit=1)[0])
                self.assertFalse(imported_roots & FORBIDDEN_IMPORT_ROOTS)

                assigned_names = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                assigned_names.add(target.id)
                    elif isinstance(node, ast.AnnAssign) and isinstance(
                        node.target, ast.Name
                    ):
                        assigned_names.add(node.target.id)
                forbidden_constants = {
                    name
                    for name in assigned_names
                    if (
                        name in FORBIDDEN_CONSTANTS
                        or (name.isupper() and name not in ALLOWED_SCRIPT_CONSTANTS)
                    )
                }
                self.assertFalse(forbidden_constants)

    def test_r_stage_tests_and_contract_files_are_not_flattened(self) -> None:
        flat_r_stage_tests = [
            path.name
            for path in ROOT.glob("tests/test_r*.py")
            if path.name.startswith(tuple(f"test_r{stage}" for stage in range(7)))
        ]
        self.assertEqual([], flat_r_stage_tests)

        flat_r_stage_schemas = [
            path.name
            for path in ROOT.glob("schemas/r*.json")
            if path.name.startswith(tuple(f"r{stage}_" for stage in range(7)))
        ]
        flat_r_stage_configs = [
            path.name
            for path in ROOT.glob("configs/r*.json")
            if path.name.startswith(tuple(f"r{stage}_" for stage in range(7)))
        ]
        self.assertEqual([], flat_r_stage_schemas)
        self.assertEqual([], flat_r_stage_configs)


if __name__ == "__main__":
    unittest.main()
