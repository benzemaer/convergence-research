from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/build_d2_csi800_membership_alignment.py"
SPEC = importlib.util.spec_from_file_location("build_d2_alignment", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class BuildD2CSI800MembershipAlignmentTest(unittest.TestCase):
    def test_builder_generates_committed_alignment_and_report(self) -> None:
        alignment = MODULE.build_alignment()
        report = MODULE.build_report(alignment)
        self.assertEqual(alignment, load(MODULE.DEFAULT_ALIGNMENT_PATH))
        self.assertEqual(report, load(MODULE.DEFAULT_REPORT_PATH))

    def test_check_mode_passes_for_committed_outputs(self) -> None:
        self.assertEqual(MODULE.main(["--check"]), 0)

    def test_check_mode_detects_tampered_alignment(self) -> None:
        alignment = MODULE.build_alignment()
        report = MODULE.build_report(alignment)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            altered_alignment = tmp / "alignment.json"
            report_path = tmp / "report.json"
            changed = json.loads(MODULE.dump_json(alignment))
            changed["rows"][0]["security_id"] = "CN.SSE.999999"
            altered_alignment.write_text(
                MODULE.dump_json(changed),
                encoding="utf-8",
            )
            report_path.write_text(MODULE.dump_json(report), encoding="utf-8")
            with (
                patch.object(MODULE, "DEFAULT_ALIGNMENT_PATH", altered_alignment),
                patch.object(MODULE, "DEFAULT_REPORT_PATH", report_path),
            ):
                with self.assertRaises(ValueError):
                    MODULE.main(["--check"])

    def test_builder_refuses_unapproved_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            disallowed = Path(tmpdir) / "alignment.json"
            with self.assertRaises(ValueError):
                MODULE.main(["--write-alignment", str(disallowed)])

    def test_builder_does_not_access_forbidden_paths(self) -> None:
        original_open = Path.open
        opened: list[Path] = []

        def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            resolved = path.resolve()
            text = str(resolved).lower()
            forbidden = (
                "data\\external",
                "data/external",
                ".duckdb",
                "marketdb",
                ".day",
            )
            if any(token in text for token in forbidden):
                raise AssertionError(f"forbidden path accessed: {resolved}")
            opened.append(resolved)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            alignment = MODULE.build_alignment()
            report = MODULE.build_report(alignment)
        self.assertEqual(len(alignment["rows"]), 800)
        self.assertEqual(report["member_count_observed"], 800)
        self.assertTrue(opened)
        self.assertFalse(any("data\\external" in str(path).lower() for path in opened))

    def test_builder_source_has_no_forbidden_storage_or_market_access(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("data/external", "marketdb", ".day"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
