from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.configure_d2_source_env import check_env, configure_env_file

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/configure_d2_source_env.py"


class ConfigureD2SourceEnvTest(unittest.TestCase):
    def test_env_example_has_no_secret_values(self) -> None:
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertEqual(text, "HITHINK_API_KEY=\nTUSHARE_TOKEN=\n")
        self.assertNotIn("sk-", text)

    def test_write_fake_values_without_printing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env.local"
            with mock.patch.object(sys.stdin, "isatty", return_value=True):
                with mock.patch("getpass.getpass", side_effect=["fake-h", "fake-t"]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                        self.assertEqual(configure_env_file(path), 0)
            self.assertIn("HITHINK_API_KEY=fake-h", path.read_text())
            self.assertNotIn("fake-h", out.getvalue())

    def test_default_no_overwrite_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env.local"
            path.write_text("HITHINK_API_KEY=old\nTUSHARE_TOKEN=old\n")
            with mock.patch.object(sys.stdin, "isatty", return_value=True):
                with mock.patch("getpass.getpass", side_effect=AssertionError):
                    self.assertEqual(configure_env_file(path), 0)
            self.assertIn("old", path.read_text())
            with mock.patch.object(sys.stdin, "isatty", return_value=True):
                with mock.patch("getpass.getpass", side_effect=["new-h", "new-t"]):
                    self.assertEqual(configure_env_file(path, overwrite=True), 0)
            self.assertIn("new-h", path.read_text())

    def test_check_missing_returns_nonzero_and_noninteractive_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env.local"
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(check_env(path), 1)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--env-file", str(path)],
                check=False,
                capture_output=True,
                input="",
                text=True,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
