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

from scripts import build_csi800_security_mapping_output as mapper

ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
FIELD_ALIASES_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)
REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
OUTPUT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json"
)
SECURITY_MASTER_CONTRACT_PATH = ROOT / "configs/d1/security_master_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def contract_for_fixture(
    tmp_path: Path,
    evidence_path: Path,
    evidence_text: str,
    expected_count: int,
) -> Path:
    contract = deepcopy(load_json(MEMBERSHIP_CONTRACT_PATH))
    contract["source_evidence"]["raw_evidence_path"] = evidence_path.relative_to(
        ROOT
    ).as_posix()
    contract["source_evidence"]["raw_evidence_sha256"] = hashlib.sha256(
        evidence_text.encode()
    ).hexdigest()
    contract["universe"]["expected_member_count"] = expected_count
    path = tmp_path / "membership_contract.json"
    write_json(path, contract)
    return path


def synthetic_evidence(rows: list[tuple[str, str]]) -> str:
    lines = ["成份券代码Constituent Code,交易所Exchange"]
    lines.extend(f"{source_symbol},{exchange}" for source_symbol, exchange in rows)
    return "\n".join(lines) + "\n"


def synthetic_800_member_rows() -> list[tuple[str, str]]:
    sz_rows = [(f"{index:06d}.SZ", "SZSE") for index in range(1, 401)]
    sh_rows = [(f"{600000 + index:06d}.SH", "SSE") for index in range(1, 401)]
    return sz_rows + sh_rows


class BuildCSI800SecurityMappingOutputTest(unittest.TestCase):
    def test_synthetic_evidence_maps_to_clean_aggregate_report(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = synthetic_evidence(synthetic_800_member_rows())
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(
                tmp_path,
                evidence,
                evidence_text,
                expected_count=800,
            )
            report = mapper.build_aggregate_report(
                contract_path=contract_path,
                field_aliases_path=FIELD_ALIASES_PATH,
                security_mapping_reference_contract_path=REFERENCE_CONTRACT_PATH,
                security_mapping_output_contract_path=OUTPUT_CONTRACT_PATH,
                security_master_contract_path=SECURITY_MASTER_CONTRACT_PATH,
            )
        self.assertEqual(report["report_status"], "passed")
        self.assertEqual(report["observed_row_count"], 800)
        self.assertEqual(report["mapped_row_count"], 800)
        self.assertEqual(report["unmapped_row_count"], 0)
        self.assertEqual(report["duplicate_membership_key_count"], 0)
        self.assertEqual(report["invalid_security_id_format_count"], 0)

    def test_mapping_preserves_leading_zero_and_security_id_format(self) -> None:
        members = [
            {
                "source_symbol": "000001.SZ",
                "ticker": "000001",
                "exchange": "SZSE",
            }
        ]
        rows = mapper.mapped_rows_from_members(
            members,
            load_json(MEMBERSHIP_CONTRACT_PATH),
            load_json(SECURITY_MASTER_CONTRACT_PATH),
        )
        self.assertEqual(rows[0]["ticker"], "000001")
        self.assertEqual(rows[0]["exchange"], "SZSE")
        self.assertEqual(rows[0]["security_id"], "CN.SZSE.000001")

    def test_duplicate_membership_key_is_counted(self) -> None:
        rows = [
            self.row("000001", "SZSE", "CN.SZSE.000001"),
            self.row("000001", "SZSE", "CN.SZSE.000001"),
        ]
        aggregate = self.aggregate(rows, expected_count=2)
        self.assertEqual(aggregate["duplicate_membership_key_count"], 1)
        self.assertEqual(aggregate["report_status"], "failed_duplicate_membership_key")

    def test_duplicate_security_id_is_counted(self) -> None:
        rows = [
            self.row("000001", "SZSE", "CN.SZSE.000001"),
            self.row("000002", "SZSE", "CN.SZSE.000001"),
        ]
        aggregate = self.aggregate(rows, expected_count=2)
        self.assertEqual(aggregate["duplicate_security_id_count"], 1)
        self.assertEqual(aggregate["report_status"], "failed_duplicate_security_id")

    def test_invalid_security_id_method_and_status_are_counted(self) -> None:
        rows = [
            self.row("000001", "SZSE", "bad-id"),
            self.row(
                "000002",
                "SZSE",
                "CN.SZSE.000002",
                mapping_method="manual",
            ),
            self.row(
                "000003",
                "SZSE",
                "CN.SZSE.000003",
                mapping_status="unmapped",
            ),
        ]
        aggregate = self.aggregate(rows, expected_count=3)
        self.assertEqual(aggregate["invalid_security_id_format_count"], 1)
        self.assertEqual(aggregate["invalid_mapping_method_count"], 1)
        self.assertEqual(aggregate["invalid_mapping_status_count"], 1)
        self.assertEqual(aggregate["unmapped_row_count"], 1)
        self.assertEqual(aggregate["report_status"], "failed_unmapped_rows")

    def test_no_approved_evidence_returns_blocked_report(self) -> None:
        before_duckdb = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        before_manifests = {
            path.resolve() for path in (ROOT / "manifests").rglob("*.json")
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            missing = tmp_path / "missing.csv"
            contract_path = contract_for_fixture(tmp_path, missing, "", 800)
            report = mapper.build_aggregate_report(
                contract_path=contract_path,
                field_aliases_path=FIELD_ALIASES_PATH,
                security_mapping_reference_contract_path=REFERENCE_CONTRACT_PATH,
                security_mapping_output_contract_path=OUTPUT_CONTRACT_PATH,
                security_master_contract_path=SECURITY_MASTER_CONTRACT_PATH,
            )
        self.assertEqual(
            report["report_status"],
            "blocked_missing_security_mapping_output",
        )
        self.assertEqual(
            report["security_mapping_output_contract_id"],
            "D1_T04_CSI800_STATIC_2026_06_SECURITY_MAPPING_OUTPUT_CONTRACT_V1",
        )
        self.assertEqual(report["expected_row_count"], 800)
        self.assertEqual(report["observed_row_count"], 0)
        self.assertEqual(report["mapped_row_count"], 0)
        self.assertEqual(report["unmapped_row_count"], 0)
        self.assertEqual(report["duplicate_membership_key_count"], 0)
        self.assertEqual(report["duplicate_security_id_count"], 0)
        self.assertEqual(report["invalid_security_id_format_count"], 0)
        self.assertEqual(report["invalid_mapping_method_count"], 0)
        self.assertEqual(report["invalid_mapping_status_count"], 0)
        for field in (
            "row_level_detail_included",
            "output_rows_committed",
            "security_id_mapping_output_committed",
            "raw_bytes_committed",
            "member_rows_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            with self.subTest(field=field):
                self.assertFalse(report[field])
        self.assertIn(
            "approved raw evidence is unavailable",
            report["validation_reason"],
        )
        self.assertIn(
            "no security_id was generated or inferred", report["validation_reason"]
        )
        self.assertIn(
            "aggregate security mapping output report only", report["report_boundary"]
        )
        after_duckdb = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        after_manifests = {
            path.resolve() for path in (ROOT / "manifests").rglob("*.json")
        }
        self.assertEqual(after_duckdb, before_duckdb)
        self.assertEqual(after_manifests, before_manifests)

    def test_cli_outputs_only_aggregate_values(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            tmp_path = Path(tmp_dir)
            evidence = tmp_path / "members.csv"
            evidence_text = synthetic_evidence(synthetic_800_member_rows())
            evidence.write_bytes(evidence_text.encode())
            contract_path = contract_for_fixture(tmp_path, evidence, evidence_text, 800)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = mapper.main(
                    [
                        "--contract",
                        str(contract_path),
                        "--field-aliases",
                        str(FIELD_ALIASES_PATH),
                        "--security-mapping-reference-contract",
                        str(REFERENCE_CONTRACT_PATH),
                        "--security-mapping-output-contract",
                        str(OUTPUT_CONTRACT_PATH),
                        "--security-master-contract",
                        str(SECURITY_MASTER_CONTRACT_PATH),
                        "--aggregate-only",
                    ]
                )
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["report_status"], "passed")
        self.assertNotIn("000001", output.getvalue())
        self.assertNotIn("000001.SZ", output.getvalue())
        self.assertNotIn("SZSE", output.getvalue())
        self.assertNotIn("SSE", output.getvalue())
        self.assertNotIn("CN.SZSE.000001", output.getvalue())

    def test_mapper_does_not_access_network(self) -> None:
        def fail_network(*args: object, **kwargs: object) -> None:
            raise AssertionError("network access attempted")

        with patch.object(socket, "create_connection", fail_network):
            aggregate = self.aggregate(
                [self.row("000001", "SZSE", "CN.SZSE.000001")],
                1,
            )
        self.assertEqual(aggregate["report_status"], "passed")

    def test_mapper_does_not_write_duckdb_or_manifests(self) -> None:
        before_duckdb = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        before_manifests = {
            path.resolve() for path in (ROOT / "manifests").rglob("*.json")
        }
        self.aggregate([self.row("000001", "SZSE", "CN.SZSE.000001")], 1)
        after_duckdb = {path.resolve() for path in ROOT.rglob("*.duckdb*")}
        after_manifests = {
            path.resolve() for path in (ROOT / "manifests").rglob("*.json")
        }
        self.assertEqual(after_duckdb, before_duckdb)
        self.assertEqual(after_manifests, before_manifests)

    @staticmethod
    def row(
        ticker: str,
        exchange: str,
        security_id: str,
        mapping_method: str = mapper.MAPPING_METHOD,
        mapping_status: str = mapper.MAPPING_STATUS,
    ) -> dict[str, str]:
        return {
            "ticker": ticker,
            "exchange": exchange,
            "membership_effective_date": "2026-06-12",
            "security_id": security_id,
            "mapping_method": mapping_method,
            "mapping_status": mapping_status,
        }

    @staticmethod
    def aggregate(
        rows: list[dict[str, str]],
        expected_count: int,
    ) -> dict[str, object]:
        output_contract = deepcopy(load_json(OUTPUT_CONTRACT_PATH))
        output_contract["expected_row_count"] = expected_count
        return mapper.aggregate_mapped_rows(
            rows,
            output_contract,
            load_json(SECURITY_MASTER_CONTRACT_PATH),
        )


if __name__ == "__main__":
    unittest.main()
