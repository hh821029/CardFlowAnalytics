import os
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

import etl.extraction as extraction
from etl.parsers.sinopac import SinopacBillParser
from etl.parsers.esun import EsunParser
from etl.parsers.cathay import CubeParser
from etl.parsers.ctbc import CTBCParser
from etl.parsers.hncb import HNCBParser

class TestGetBankInfo:
    """測試 get_bank_info 的所有邊界與分支"""

    def test_empty_or_none_filename(self):
        assert extraction.get_bank_info("") is None
        assert extraction.get_bank_info(None) is None

    def test_config_loader_none_fallback(self):
        with patch.object(extraction, "ConfigLoader", None):
            result = extraction.get_bank_info("202410_玉山銀行.csv")
            assert result is None

    def test_config_loader_exception(self):
        mock_loader = MagicMock()
        mock_loader.load_yaml.side_effect = RuntimeError("YAML 讀取失敗")
        with patch.object(extraction, "ConfigLoader", mock_loader):
            result = extraction.get_bank_info("202410_玉山銀行.csv")
            assert result is None

    def test_config_loader_non_dict(self):
        mock_loader = MagicMock()
        mock_loader.load_yaml.return_value = ["not_a_dict"]
        with patch.object(extraction, "ConfigLoader", mock_loader):
            result = extraction.get_bank_info("202410_玉山銀行.csv")
            assert result is None

    def test_match_by_bill_mapping_name(self):
        mock_loader = MagicMock()
        mock_loader.load_yaml.return_value = {
            "banks": [{"bank_id": "test_bank", "bill_mapping_name": "測試銀行", "keywords": []}]
        }
        with patch.object(extraction, "ConfigLoader", mock_loader):
            bank = extraction.get_bank_info("202410_測試銀行帳單.csv")
            assert bank is not None
            assert bank["bank_id"] == "test_bank"

    def test_match_by_keyword(self):
        mock_loader = MagicMock()
        mock_loader.load_yaml.return_value = {
            "banks": [{"bank_id": "test_kw", "keywords": ["SPECIAL_KEYWORD"]}]
        }
        with patch.object(extraction, "ConfigLoader", mock_loader):
            bank = extraction.get_bank_info("special_keyword_bill.csv")
            assert bank is not None
            assert bank["bank_id"] == "test_kw"

    def test_no_match_returns_none(self):
        bank = extraction.get_bank_info("unknown_random_file_2024.csv")
        assert bank is None


class TestGetParser:
    """測試 get_parser 的各銀行派發與無效副檔名防呆"""

    def test_no_bank_info_returns_none(self):
        assert extraction.get_parser("unknown_file.csv") is None

    def test_sinopac_pdf(self):
        parser = extraction.get_parser("202410_永豐銀行帳單.pdf")
        assert isinstance(parser, SinopacBillParser)

    def test_esun_csv(self):
        parser = extraction.get_parser("202410_玉山銀行帳單.csv")
        assert isinstance(parser, EsunParser)

    def test_cathay_cube_csv(self):
        parser = extraction.get_parser("202410_國泰世華_cube.csv")
        assert isinstance(parser, CubeParser)

    def test_ctbc_csv(self):
        parser = extraction.get_parser("202410_中國信託帳單.csv")
        assert isinstance(parser, CTBCParser)

    def test_hncb_xls_and_html(self):
        parser_xls = extraction.get_parser("202410_華南銀行帳單.xls")
        assert isinstance(parser_xls, HNCBParser)
        parser_html = extraction.get_parser("202410_華南銀行帳單.html")
        assert isinstance(parser_html, HNCBParser)

    def test_known_bank_unsupported_extension(self):
        # 玉山不支援 .pdf
        assert extraction.get_parser("202410_玉山銀行帳單.pdf") is None
        # 永豐不支援 .csv
        assert extraction.get_parser("202410_永豐銀行帳單.csv") is None
        # 華南不支援 .csv
        assert extraction.get_parser("202410_華南銀行帳單.csv") is None


class TestGetParserMapping:
    """測試 get_parser_mapping 返回完整支援之銀行映射字典"""

    def test_mapping_contains_all_banks(self):
        mapping = extraction.get_parser_mapping()
        assert set(mapping.keys()) == {"sinopac", "esun", "cathay", "ctbc", "hncb"}
        assert isinstance(mapping["sinopac"], SinopacBillParser)
        assert isinstance(mapping["esun"], EsunParser)
        assert isinstance(mapping["cathay"], CubeParser)
        assert isinstance(mapping["ctbc"], CTBCParser)
        assert isinstance(mapping["hncb"], HNCBParser)


class TestExtractRawData:
    """測試 extract_raw_data 完整的目錄掃描、去重、解析、例外處理與合併"""

    def test_nonexistent_directory(self):
        result = extraction.extract_raw_data(input_dir="/nonexistent/directory/path/here")
        assert result is None

    def test_empty_directory(self, tmp_path):
        result = extraction.extract_raw_data(input_dir=str(tmp_path))
        assert result is None

    def test_directory_with_subfolder_and_dotfiles(self, tmp_path):
        # 建立子資料夾與隱藏檔案
        (tmp_path / "subfolder").mkdir()
        (tmp_path / ".DS_Store").write_text("dummy", encoding="utf-8")
        result = extraction.extract_raw_data(input_dir=str(tmp_path))
        assert result is None

    def test_unsupported_file_skipped(self, tmp_path):
        # 建立未知或不支援的檔案
        (tmp_path / "unsupported_notes.txt").write_text("hello", encoding="utf-8")
        result = extraction.extract_raw_data(input_dir=str(tmp_path))
        assert result is None

    def test_force_false_skips_ingested_file(self, tmp_path):
        file_path = tmp_path / "202410_玉山銀行_test.csv"
        file_path.write_text("消費日\n2024/10/01", encoding="utf-8-sig")

        mock_registry = MagicMock()
        mock_registry.calculate_file_hash.return_value = "hash123456"
        mock_registry.is_file_ingested.return_value = True  # 模擬已入庫過

        with patch.object(extraction, "FileRegistryManager", return_value=mock_registry):
            result = extraction.extract_raw_data(force=False, input_dir=str(tmp_path))
            assert result is None
            mock_registry.is_file_ingested.assert_called_once_with("hash123456")

    def test_successful_parse_populates_missing_bank_name(self, tmp_path):
        file_path = tmp_path / "202410_玉山銀行_test.csv"
        file_path.write_text("dummy", encoding="utf-8")

        mock_df = pd.DataFrame([{"transaction_date": "2024-10-01", "payment_amount": 100}])
        # 無 bank_name 欄位
        assert "bank_name" not in mock_df.columns

        mock_parser = MagicMock()
        mock_parser.parse.return_value = mock_df

        mock_registry = MagicMock()
        mock_registry.calculate_file_hash.return_value = "hash_success"
        mock_registry.is_file_ingested.return_value = False

        with patch.object(extraction, "FileRegistryManager", return_value=mock_registry), \
             patch.object(extraction, "get_parser", return_value=mock_parser):
            
            result = extraction.extract_raw_data(force=True, input_dir=str(tmp_path))
            assert result is not None
            assert not result.empty
            assert result["bank_name"].iloc[0] == "玉山銀行"
            mock_registry.register_file.assert_called_once()
            call_kwargs = mock_registry.register_file.call_args[1]
            assert call_kwargs["status"] == "SUCCESS"
            assert call_kwargs["record_count"] == 1

    def test_successful_parse_replaces_empty_bank_name(self, tmp_path):
        file_path = tmp_path / "202410_玉山銀行_test.csv"
        file_path.write_text("dummy", encoding="utf-8")

        # 存在 bank_name 欄位但為空字串或 NaN
        mock_df = pd.DataFrame([{"transaction_date": "2024-10-01", "bank_name": ""}])

        mock_parser = MagicMock()
        mock_parser.parse.return_value = mock_df

        mock_registry = MagicMock()
        mock_registry.calculate_file_hash.return_value = "hash_empty_bank"

        with patch.object(extraction, "FileRegistryManager", return_value=mock_registry), \
             patch.object(extraction, "get_parser", return_value=mock_parser):
            
            result = extraction.extract_raw_data(force=True, input_dir=str(tmp_path))
            assert result is not None
            assert result["bank_name"].iloc[0] == "玉山銀行"

    def test_parsed_empty_dataframe_registers_zero_records(self, tmp_path):
        file_path = tmp_path / "202410_玉山銀行_test.csv"
        file_path.write_text("dummy", encoding="utf-8")

        mock_parser = MagicMock()
        mock_parser.parse.return_value = pd.DataFrame()  # 空 DataFrame

        mock_registry = MagicMock()
        mock_registry.calculate_file_hash.return_value = "hash_empty_df"

        with patch.object(extraction, "FileRegistryManager", return_value=mock_registry), \
             patch.object(extraction, "get_parser", return_value=mock_parser):
            
            result = extraction.extract_raw_data(force=True, input_dir=str(tmp_path))
            assert result is None
            mock_registry.register_file.assert_called_once()
            call_kwargs = mock_registry.register_file.call_args[1]
            assert call_kwargs["status"] == "SUCCESS"
            assert call_kwargs["record_count"] == 0

    def test_parser_exception_caught_and_registers_failed(self, tmp_path):
        file_path = tmp_path / "202410_玉山銀行_test.csv"
        file_path.write_text("corrupted_content", encoding="utf-8")

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValueError("檔案結構嚴重毀損")

        mock_registry = MagicMock()
        mock_registry.calculate_file_hash.return_value = "hash_failed"

        with patch.object(extraction, "FileRegistryManager", return_value=mock_registry), \
             patch.object(extraction, "get_parser", return_value=mock_parser):
            
            result = extraction.extract_raw_data(force=True, input_dir=str(tmp_path))
            assert result is None
            mock_registry.register_file.assert_called_once()
            call_kwargs = mock_registry.register_file.call_args[1]
            assert call_kwargs["status"] == "FAILED"
            assert call_kwargs["record_count"] == 0

    def test_multiple_files_parsed_and_concatenated(self, tmp_path):
        # 建立兩個有效測試檔案
        (tmp_path / "202410_玉山銀行_f1.csv").write_text("d1", encoding="utf-8")
        (tmp_path / "202410_中國信託_f2.csv").write_text("d2", encoding="utf-8")

        def side_effect_parse(filepath):
            if "玉山" in filepath:
                return pd.DataFrame([{"txn": "t1", "bank_name": "玉山銀行"}])
            else:
                return pd.DataFrame([{"txn": "t2", "bank_name": "中國信託"}])

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = side_effect_parse

        with patch.object(extraction, "FileRegistryManager", None), \
             patch.object(extraction, "get_parser", return_value=mock_parser):
            
            result = extraction.extract_raw_data(force=True, input_dir=str(tmp_path))
            assert result is not None
            assert len(result) == 2
            assert set(result["bank_name"].tolist()) == {"玉山銀行", "中國信託"}
