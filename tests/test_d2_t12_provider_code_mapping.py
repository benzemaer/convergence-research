from __future__ import annotations

import unittest

from scripts.resolve_security_provider_codes import resolve_security_provider_codes


class D2T12ProviderCodeMappingTest(unittest.TestCase):
    def test_common_security_id_formats_resolve(self) -> None:
        cases = {
            "XSHE.000001": ("SZSE", "000001.SZ", "sz.000001"),
            "SZSE.000001": ("SZSE", "000001.SZ", "sz.000001"),
            "CN.SZSE.000001": ("SZSE", "000001.SZ", "sz.000001"),
            "000001.SZ": ("SZSE", "000001.SZ", "sz.000001"),
            "sz.000001": ("SZSE", "000001.SZ", "sz.000001"),
            "XSHG.600000": ("SSE", "600000.SH", "sh.600000"),
            "SHSE.600000": ("SSE", "600000.SH", "sh.600000"),
            "CN.SSE.600000": ("SSE", "600000.SH", "sh.600000"),
            "600000.SH": ("SSE", "600000.SH", "sh.600000"),
            "sh.600000": ("SSE", "600000.SH", "sh.600000"),
        }
        for security_id, (exchange, ts_code, baostock_code) in cases.items():
            with self.subTest(security_id=security_id):
                resolved = resolve_security_provider_codes(security_id)
                self.assertEqual(resolved.mapping_status, "resolved")
                self.assertEqual(resolved.exchange, exchange)
                self.assertEqual(resolved.hithink_thscode, ts_code)
                self.assertEqual(resolved.tushare_ts_code, ts_code)
                self.assertEqual(resolved.tnskhdata_ts_code, ts_code)
                self.assertEqual(resolved.baostock_code, baostock_code)

    def test_unresolved_mapping_blocks_provider_query(self) -> None:
        resolved = resolve_security_provider_codes("BAD.CODE")
        self.assertEqual(resolved.mapping_status, "unresolved")
        self.assertIsNone(resolved.tushare_ts_code)
        self.assertIn(
            "unsupported_security_id_format", resolved.mapping_blocking_reasons
        )


if __name__ == "__main__":
    unittest.main()
