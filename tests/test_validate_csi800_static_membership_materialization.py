from __future__ import annotations

import contextlib
import hashlib
import io
import json
import socket
import tempfile
import types
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
            "source_symbol": (
                "SZ"
                if missing_column == "ticker"
                else ticker
                if missing_column == "exchange"
                else f"{ticker}.SZ"
            ),
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


def contract_for_bytes_fixture(
    tmp_path: Path,
    evidence_path: Path,
    evidence_bytes: bytes,
    expected_count: int,
) -> Path:
    contract = deepcopy(load_contract())
    relative_evidence = evidence_path.relative_to(ROOT).as_posix()
    contract["source_evidence"]["raw_evidence_path"] = relative_evidence
    contract["source_evidence"]["raw_evidence_sha256"] = hashlib.sha256(
        evidence_bytes
    ).hexdigest()
    contract["universe"]["expected_member_count"] = expected_count
    contract_path = tmp_path / "contract.json"
    write_json(contract_path, contract)
    return contract_path


class FakeSheet:
    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max(len(row) for row in rows)

    def cell_value(self, row_index: int, column_index: int) -> object:
        row = self._rows[row_index]
        if column_index >= len(row):
            return ""
        return row[column_index]


class FakeWorkbook:
    def __init__(self, rows: list[list[object]]) -> None:
        self.nsheets = 1
        self._sheet = FakeSheet(rows)

    def sheet_by_index(self, index: int) -> FakeSheet:
        if index != 0:
            raise IndexError(index)
        return self._sheet


def fake_xlrd_module(rows: list[list[object]]) -> types.SimpleNamespace:
    return types.SimpleNamespace(open_workbook=lambda file_contents: FakeWorkbook(rows))


def binary_xls_bytes() -> bytes:
    return validator.OLE_COMPOUND_FILE_MAGIC + b"synthetic-xls"


def binary_rows(count: int, missing_column: str | None = None) -> list[list[object]]:
    headers: list[object] = [
        "source_symbol",
        "ticker",
        "exchange",
        "security_id_mapping_reference",
    ]
    if missing_column:
        headers.remove(missing_column)
    rows = [headers]
    for index in range(count):
        ticker = f"{index + 1:06d}"
        values: dict[str, object] = {
            "source_symbol": (
                "SH"
                if missing_column == "ticker"
                else ticker
                if missing_column == "exchange"
                else f"{ticker}.SH"
            ),
            "ticker": ticker,
            "exchange": "SSE",
            "security_id_mapping_reference": "requires_d1_security_master_mapping",
        }
        rows.append([values[header] for header in headers])
    return rows


def binary_rows_with_ticker(
    raw_ticker: object,
    source_symbol: str,
) -> list[list[object]]:
    return [
        [
            "source_symbol",
            "ticker",
            "exchange",
            "security_id_mapping_reference",
        ],
        [
            source_symbol,
            raw_ticker,
            "SSE",
            "requires_d1_security_master_mapping",
        ],
    ]


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

    def test_synthetic_json_fixture_passes_dry_run_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.json"
            members = [
                {
                    "source_symbol": "600000.SH",
                    "ticker": "600000",
                    "exchange": "SSE",
                    "security_id_mapping_reference": (
                        "requires_d1_security_master_mapping"
                    ),
                }
            ]
            evidence_text = json.dumps({"members": members})
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=1,
            )
            result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)
            self.assertEqual(result.member_count, 1)

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

    def test_binary_xls_fixture_passes_dry_run_validation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.xls"
            evidence_bytes = binary_xls_bytes()
            evidence.write_bytes(evidence_bytes)
            contract_path = contract_for_bytes_fixture(
                tmp_path,
                evidence,
                evidence_bytes,
                expected_count=3,
            )
            with patch.dict(
                "sys.modules",
                {"xlrd": fake_xlrd_module(binary_rows(3))},
            ):
                result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)
            self.assertEqual(result.member_count, 3)

    def test_binary_xls_numeric_ticker_can_use_source_symbol_code(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.xls"
            evidence_bytes = binary_xls_bytes()
            evidence.write_bytes(evidence_bytes)
            contract_path = contract_for_bytes_fixture(
                tmp_path,
                evidence,
                evidence_bytes,
                expected_count=1,
            )
            with patch.dict(
                "sys.modules",
                {"xlrd": fake_xlrd_module(binary_rows_with_ticker(1.0, "000001.SH"))},
            ):
                result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_PASSED)
            self.assertEqual(result.member_count, 1)

    def test_binary_xls_numeric_ticker_without_source_code_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.xls"
            evidence_bytes = binary_xls_bytes()
            evidence.write_bytes(evidence_bytes)
            contract_path = contract_for_bytes_fixture(
                tmp_path,
                evidence,
                evidence_bytes,
                expected_count=1,
            )
            with patch.dict(
                "sys.modules",
                {"xlrd": fake_xlrd_module(binary_rows_with_ticker(1.0, "SH"))},
            ):
                result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_FAILED)
            self.assertIn("invalid ticker", result.reason)

    def test_binary_xls_member_count_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.xls"
            evidence_bytes = binary_xls_bytes()
            evidence.write_bytes(evidence_bytes)
            contract_path = contract_for_bytes_fixture(
                tmp_path,
                evidence,
                evidence_bytes,
                expected_count=3,
            )
            with patch.dict(
                "sys.modules",
                {"xlrd": fake_xlrd_module(binary_rows(2))},
            ):
                result = validator.validate_materialization_inputs(contract_path)
            self.assertEqual(result.status, validator.STATUS_FAILED)
            self.assertIn("member_count_mismatch", result.reason)

    def test_binary_xls_missing_required_mapping_fields_fail(self) -> None:
        for missing_column in (
            "source_symbol",
            "ticker",
            "exchange",
            "security_id_mapping_reference",
        ):
            with self.subTest(missing_column=missing_column):
                with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    evidence = tmp_path / "members.xls"
                    evidence_bytes = binary_xls_bytes()
                    evidence.write_bytes(evidence_bytes)
                    contract_path = contract_for_bytes_fixture(
                        tmp_path,
                        evidence,
                        evidence_bytes,
                        expected_count=1,
                    )
                    with patch.dict(
                        "sys.modules",
                        {"xlrd": fake_xlrd_module(binary_rows(1, missing_column))},
                    ):
                        result = validator.validate_materialization_inputs(
                            contract_path
                        )
                    self.assertEqual(result.status, validator.STATUS_FAILED)
                    expected_reason = (
                        "invalid ticker"
                        if missing_column == "ticker"
                        else f"missing {missing_column}"
                    )
                    self.assertIn(expected_reason, result.reason)

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
                    expected_reason = (
                        "invalid ticker"
                        if missing_column == "ticker"
                        else f"missing {missing_column}"
                    )
                    self.assertIn(expected_reason, result.reason)

    def test_text_formats_reject_invalid_ticker_without_source_code(self) -> None:
        for suffix, evidence_text in (
            (
                ".csv",
                "source_symbol,ticker,exchange,security_id_mapping_reference\n"
                "SH,1,SSE,requires_d1_security_master_mapping\n",
            ),
            (
                ".json",
                json.dumps(
                    {
                        "members": [
                            {
                                "source_symbol": "SH",
                                "ticker": "ABC",
                                "exchange": "SSE",
                                "security_id_mapping_reference": (
                                    "requires_d1_security_master_mapping"
                                ),
                            }
                        ]
                    }
                ),
            ),
        ):
            with self.subTest(suffix=suffix):
                with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    evidence = tmp_path / f"members{suffix}"
                    evidence.write_bytes(evidence_text.encode())
                    contract_path = contract_for_fixture(
                        tmp_path,
                        evidence,
                        evidence_text,
                        expected_count=1,
                    )
                    result = validator.validate_materialization_inputs(contract_path)
                    self.assertEqual(result.status, validator.STATUS_FAILED)
                    self.assertIn("invalid ticker", result.reason)

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

    def test_cli_diagnose_fields_emits_only_aggregate_header_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = (
                "成份券代码Constituent Code,交易所Exchange\n000001.SZ,SZSE\n"
            )
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=1,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = validator.main(
                    ["--contract", str(contract_path), "--diagnose-fields"]
                )
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["member_count_observed"], 1)
            self.assertEqual(payload["observed_column_count"], 2)
            self.assertFalse(payload["row_level_detail_included"])
            self.assertFalse(payload["raw_bytes_committed"])
            self.assertFalse(payload["member_rows_committed"])
            self.assertIn(
                "security_id_mapping_reference",
                payload["missing_required_fields"],
            )
            self.assertIn(
                "成份券代码Constituent Code",
                payload["candidate_aliases_by_required_field"]["source_symbol"],
            )
            self.assertNotIn("000001.SZ", output.getvalue())
            self.assertNotIn("SZSE", output.getvalue())

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
