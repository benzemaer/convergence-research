from __future__ import annotations

import contextlib
import hashlib
import io
import json
import socket
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from scripts import validate_csi800_static_membership_materialization as validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"


def load_contract() -> dict[str, object]:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def csv_members(count: int, missing_column: str | None = None) -> str:
    headers = [
        "source_symbol",
        "ticker",
        "exchange",
        "security_id_mapping_reference",
    ]
    if missing_column:
        headers.remove(missing_column)
    rows = [",".join(headers)]
    for index in range(count):
        ticker = f"{index + 1:06d}"
        values = {
            "source_symbol": ticker if missing_column == "exchange" else f"{ticker}.SZ",
            "ticker": ticker,
            "exchange": "SZSE",
            "security_id_mapping_reference": "requires_d1_security_master_mapping",
        }
        rows.append(",".join(values[header] for header in headers))
    return "\n".join(rows) + "\n"


def contract_for_fixture(
    tmp_path: Path,
    evidence_path: Path,
    evidence_text: str,
    expected_count: int,
    sha_override: str | None = None,
) -> Path:
    contract = deepcopy(load_contract())
    relative_evidence = evidence_path.relative_to(ROOT).as_posix()
    contract["source_evidence"]["raw_evidence_path"] = relative_evidence
    contract["source_evidence"]["raw_evidence_sha256"] = (
        sha_override or hashlib.sha256(evidence_text.encode()).hexdigest()
    )
    contract["universe"]["expected_member_count"] = expected_count
    contract_path = tmp_path / "contract.json"
    write_json(contract_path, contract)
    return contract_path


class ValidateCSI800StaticMembershipMaterializationTest(unittest.TestCase):
    def test_missing_raw_evidence_fails_by_default(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "missing.csv"
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                "",
                expected_count=1,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_FAILED)
            self.assertIn("missing approved raw evidence", result.reason)

    def test_missing_raw_evidence_can_return_blocked_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "missing.csv"
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                "",
                expected_count=1,
            )
            result = validator.validate_materialization_inputs(
                contract_path,
                allow_missing_evidence=True,
            )
            self.assertEqual(result.status, validator.STATUS_BLOCKED)
            self.assertIn("missing approved raw evidence", result.reason)

    def test_synthetic_csv_fixture_passes_dry_run_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = csv_members(3)
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=3,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)
            self.assertEqual(result.member_count, 3)
            self.assertIn("security_id mapping remains required", result.reason)

    def test_html_table_fixture_can_be_parsed(self) -> None:
        html = """
        <table>
          <tr>
            <th>source_symbol</th>
            <th>ticker</th>
            <th>exchange</th>
            <th>security_id_mapping_reference</th>
          </tr>
          <tr>
            <td>600000.SH</td>
            <td>600000</td>
            <td>SSE</td>
            <td>requires_d1_security_master_mapping</td>
          </tr>
        </table>
        """
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.xls"
            evidence.write_bytes(html.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                html,
                expected_count=1,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)

    def test_sha256_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = csv_members(1)
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=1,
                sha_override="0" * 64,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_FAILED)
            self.assertIn("raw_evidence_sha256_mismatch", result.reason)

    def test_member_count_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = csv_members(2)
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=3,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_FAILED)
            self.assertIn("member_count_mismatch", result.reason)

    def test_missing_required_mapping_fields_fail(self) -> None:
        for missing_column in (
            "source_symbol",
            "ticker",
            "exchange",
            "security_id_mapping_reference",
        ):
            with self.subTest(missing_column=missing_column):
                with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    evidence = tmp_path / "members.csv"
                    evidence_text = csv_members(1, missing_column=missing_column)
                    evidence.write_bytes(evidence_text.encode())
                    contract_path = contract_for_fixture(
                        tmp_path,
                        evidence,
                        evidence_text,
                        expected_count=1,
                    )
                    result = validator.validate_materialization_inputs(contract_path)
                    self.assertEqual(result.status, validator.STATUS_FAILED)
                    self.assertIn(f"missing {missing_column}", result.reason)

    def test_cli_allow_missing_evidence_emits_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "missing.csv"
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                "",
                expected_count=1,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = validator.main(
                    [
                        "--contract",
                        str(contract_path),
                        "--allow-missing-evidence",
                    ]
                )
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], validator.STATUS_BLOCKED)

    def test_validator_does_not_access_network(self) -> None:
        def fail_network(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access attempted")

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = csv_members(1)
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=1,
            )
            with patch.object(socket, "create_connection", fail_network):
                result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)

    def test_validator_does_not_write_duckdb_or_membership_artifacts(self) -> None:
        before = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = csv_members(1)
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=1,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)
        after = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
