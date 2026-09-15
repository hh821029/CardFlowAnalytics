# tests/test_etl_security.py
"""
CardFlow Analytics 帳單安全載入與 4 大防禦矩陣單元測試
依據 issues20260914.md 規範，完整驗證：
- 狀況一：未知銀行檔名 (UnmappedBankError)
- 狀況二：惡意代碼注入攻擊 (MaliciousPayloadDetectedError, DDE 轉義, ReDoS 截斷)
- 狀況三：Schema 結構錯位與 0 位元組空檔案 (InvalidBillFormatError)
- 狀況四：合法邊界消費防誤殺機制 (Disney+, LINE@, -120 等)
- 各 Parser bank_no 3 碼代號動態注入契約
"""

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

import const
from etl.extraction import get_bank_info, get_parser, extract_raw_data
from etl.exceptions import UnmappedBankError, InvalidBillFormatError, MaliciousPayloadDetectedError
from etl.sanitizer import BillSanitizer
from etl.parsers.cathay import CubeParser
from etl.parsers.esun import EsunParser
from etl.parsers.ctbc import CTBCParser
from etl.parsers.hncb import HNCBParser
from etl.parsers.sinopac import SinopacBillParser
from tests.fixtures.setup_fixtures import FIXTURES_DIR

FIXTURES_ERROR_DIR = os.path.join(FIXTURES_DIR, "error_cases")
FIXTURES_SECURITY_DIR = os.path.join(FIXTURES_DIR, "security")


class TestUnmappedBank:
    """狀況一：未知銀行檔名安全隔離測試"""

    def test_unmapped_bank_strict_raises_exception(self):
        file_path = os.path.join(FIXTURES_ERROR_DIR, "error_unmapped_bank_mock.csv")
        with pytest.raises(UnmappedBankError) as exc_info:
            get_bank_info(os.path.basename(file_path), strict=True)
        assert "error_unmapped_bank_mock.csv" in str(exc_info.value)

    def test_unmapped_bank_non_strict_returns_none(self):
        file_path = os.path.join(FIXTURES_ERROR_DIR, "error_unmapped_bank_mock.csv")
        result = get_bank_info(os.path.basename(file_path), strict=False)
        assert result is None

    def test_extract_raw_data_skips_unmapped_bank_gracefully(self, tmp_path):
        # 建立暫存目錄僅放置未知銀行檔案
        src = os.path.join(FIXTURES_ERROR_DIR, "error_unmapped_bank_mock.csv")
        dst = os.path.join(str(tmp_path), "error_unmapped_bank_mock.csv")
        with open(src, 'r', encoding='utf-8') as f_in, open(dst, 'w', encoding='utf-8') as f_out:
            f_out.write(f_in.read())

        result = extract_raw_data(force=True, input_dir=str(tmp_path))
        # 應優雅跳過，不噴未捕捉例外，並回傳 None
        assert result is None


class TestSchemaMismatchAndEmpty:
    """狀況三：Schema 錯位與空檔案測試"""

    def test_empty_bill_raises_invalid_format(self):
        empty_file = os.path.join(FIXTURES_ERROR_DIR, "error_empty_bill_mock.csv")
        parser = CubeParser(bank_id_or_keyword="cube")
        with pytest.raises(InvalidBillFormatError) as exc_info:
            parser.parse(empty_file)
        assert "0 位元組空檔案" in str(exc_info.value)

    def test_schema_mismatch_raises_invalid_format(self):
        mismatch_file = os.path.join(FIXTURES_ERROR_DIR, "error_schema_mismatch_mock.csv")
        parser = CubeParser(bank_id_or_keyword="cube")
        with pytest.raises(InvalidBillFormatError) as exc_info:
            parser.parse(mismatch_file)
        assert "缺少關鍵 Header" in str(exc_info.value)

    def test_extract_raw_data_skips_mismatch_and_empty(self, tmp_path):
        # 放置國泰世華名稱但內容錯位與空的檔案
        p1 = os.path.join(str(tmp_path), "202510國泰世華_mismatch.csv")
        with open(os.path.join(FIXTURES_ERROR_DIR, "error_schema_mismatch_mock.csv"), 'r', encoding='utf-8') as f_in, open(p1, 'w', encoding='utf-8') as f_out:
            f_out.write(f_in.read())

        p2 = os.path.join(str(tmp_path), "202510國泰世華_empty.csv")
        with open(p2, 'w', encoding='utf-8') as f_out:
            pass

        result = extract_raw_data(force=True, input_dir=str(tmp_path))
        assert result is None


class TestMaliciousPayloadSecurity:
    """狀況二：惡意代碼注入攻擊防禦測試"""

    def test_dde_formula_injection_sanitized(self):
        assert BillSanitizer.sanitize_text("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
        assert BillSanitizer.sanitize_text("@SUM(1+1)*cmd|' /C calc'!A0") == "'@SUM(1+1)*cmd|' /C calc'!A0"
        assert BillSanitizer.sanitize_text("-cmd|' /C calc'!A0") == "'-cmd|' /C calc'!A0"
        assert BillSanitizer.sanitize_text("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
        assert BillSanitizer.sanitize_text("=1+1") == "'=1+1"

    def test_lethal_payload_raises_malicious_error(self):
        with pytest.raises(MaliciousPayloadDetectedError):
            BillSanitizer.sanitize_text("<script>alert(1)</script>")

        with pytest.raises(MaliciousPayloadDetectedError):
            BillSanitizer.sanitize_text("__import__('os').system('calc')")

        with pytest.raises(MaliciousPayloadDetectedError):
            BillSanitizer.sanitize_text("'; DROP TABLE all_transactions; --")

        with pytest.raises(MaliciousPayloadDetectedError):
            BillSanitizer.sanitize_text("test'; DELETE FROM all_transactions; --")

    def test_redos_catastrophic_backtracking_prevented(self):
        long_str = "A" * 3000
        sanitized = BillSanitizer.sanitize_text(long_str)
        assert len(sanitized) == 255

    def test_null_byte_stripped(self):
        assert BillSanitizer.sanitize_text("safe\x00data\x00") == "safedata"


class TestFalsePositiveEdgeCases:
    """狀況四：合法邊界消費防誤殺機制測試"""

    def test_valid_plus_sign_merchants(self):
        assert BillSanitizer.sanitize_text("Disney+") == "Disney+"
        assert BillSanitizer.sanitize_text("Google +1") == "Google +1"
        assert BillSanitizer.sanitize_text("Apple Care+") == "Apple Care+"

    def test_valid_at_sign_merchants(self):
        assert BillSanitizer.sanitize_text("LINE@官方店家") == "LINE@官方店家"
        assert BillSanitizer.sanitize_text("FB@廣告投放") == "FB@廣告投放"

    def test_valid_negative_refunds_and_amounts(self):
        assert BillSanitizer.sanitize_text("-120") == "-120"
        assert BillSanitizer.sanitize_text("-120.50") == "-120.50"
        assert BillSanitizer.sanitize_text("+50") == "+50"
        assert BillSanitizer.sanitize_text("點數折抵＿新光三") == "點數折抵＿新光三"
        assert BillSanitizer.sanitize_text("e point 現金折抵") == "e point 現金折抵"

    def test_valid_special_characters(self):
        assert BillSanitizer.sanitize_text("連支＊統一超商") == "連支＊統一超商"
        assert BillSanitizer.sanitize_text("連加＊一般商品") == "連加＊一般商品"

    def test_valid_edge_cases_file_parsing(self):
        edge_file = os.path.join(FIXTURES_SECURITY_DIR, "valid_edge_cases_mock.csv")
        parser = CubeParser(bank_id_or_keyword="cube")
        df = parser.parse(edge_file)

        assert not df.empty, "合法邊界消費測資應成功解析"
        merchants = df[const.COL_MERCHANT].tolist()

        # 驗證所有特店名稱未被破壞或誤加引號
        assert "Disney+" in merchants
        assert "Google +1" in merchants
        assert "Apple Care+" in merchants
        assert "LINE@官方店家" in merchants
        assert "FB@廣告投放" in merchants
        assert "連支＊統一超商" in merchants
        assert "連加＊一般商品" in merchants

        # 驗證退款金額正確
        refund_row = df[df[const.COL_MERCHANT] == "特店退貨"]
        assert not refund_row.empty
        assert refund_row[const.COL_PAY_AMOUNT].iloc[0] == -120.0


class TestBankNoInjectionAcrossAllParsers:
    """驗證 5 大 Parser 均有注入 bank_no 且維持 3 碼固定長度"""

    def test_cube_parser_bank_no(self):
        parser = CubeParser(bank_id_or_keyword="cube")
        assert parser.bank_no == "013"

    def test_esun_parser_bank_no(self):
        parser = EsunParser(bank_id_or_keyword="esun")
        assert parser.bank_no == "808"

    def test_ctbc_parser_bank_no(self):
        parser = CTBCParser(bank_id_or_keyword="ctbc")
        assert parser.bank_no == "822"

    def test_hncb_parser_bank_no(self):
        parser = HNCBParser(bank_id_or_keyword="hncb")
        assert parser.bank_no == "008"

    def test_sinopac_parser_bank_no(self):
        parser = SinopacBillParser(bank_id_or_keyword="sinopac")
        assert parser.bank_no == "807"
