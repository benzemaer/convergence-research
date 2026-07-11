import json
import unittest
from pathlib import Path

from src.r0.upstream_artifact_io import sha256_file

ROOT = Path(__file__).resolve().parents[2]


class InputChainTest(unittest.TestCase):
    def test_all_bound_bytes_match(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
            ).read_text()
        )
        for key, path in cfg["upstream"].items():
            if key.endswith("_path") and key[:-5] + "_sha256" in cfg["upstream"]:
                self.assertEqual(
                    sha256_file(ROOT / path), cfg["upstream"][key[:-5] + "_sha256"]
                )
        metric_source = cfg["metric_definition_source"]
        self.assertEqual(
            sha256_file(ROOT / metric_source["path"]), metric_source["sha256"]
        )


if __name__ == "__main__":
    unittest.main()
