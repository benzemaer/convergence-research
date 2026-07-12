import json
import tempfile
import unittest
from pathlib import Path

from src.common.canonical_io import (
    TextContractError,
    canonical_json_sha256,
    validate_text_bytes,
    worktree_hash_for_formal_lineage_forbidden,
    write_csv,
    write_json,
)


class CanonicalTextContractTest(unittest.TestCase):
    def test_newline_failure_paths_are_explicit(self):
        self.assertEqual(validate_text_bytes(b"ok\n"), [])
        self.assertIn("formal_source_crlf", validate_text_bytes(b"bad\r\n"))
        self.assertIn("formal_source_bom", validate_text_bytes(b"\xef\xbb\xbfok\n"))
        self.assertIn("formal_source_bare_cr", validate_text_bytes(b"bad\ronly\n"))
        self.assertIn("formal_source_terminal_newline", validate_text_bytes(b"none"))
        self.assertIn("formal_source_terminal_newline", validate_text_bytes(b"two\n\n"))

    def test_json_canonical_hash_ignores_formatting_but_not_bytes(self):
        left = json.loads('{"b": 2, "a": 1}')
        right = json.loads('{\n  "a": 1,\n  "b": 2\n}')
        self.assertEqual(canonical_json_sha256(left), canonical_json_sha256(right))
        self.assertNotEqual(b'{"a":1,"b":2}\n', b'{\n  "a": 1,\n  "b": 2\n}\n')

    def test_writers_emit_lf_final_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "artifact.json"
            csv_path = root / "artifact.csv"
            write_json(json_path, {"b": 2, "a": 1})
            write_csv(csv_path, [{"a": 1, "b": 2}], ["a", "b"])
            self.assertEqual(validate_text_bytes(json_path.read_bytes()), [])
            self.assertEqual(validate_text_bytes(csv_path.read_bytes()), [])

    def test_worktree_formal_hash_is_forbidden(self):
        with self.assertRaises(TextContractError):
            worktree_hash_for_formal_lineage_forbidden(Path("config.json"))


if __name__ == "__main__":
    unittest.main()
