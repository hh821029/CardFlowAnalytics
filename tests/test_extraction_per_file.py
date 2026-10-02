# tests/test_stage1_per_file.py
"""
驗證 Stage 1 逐檔串流提取 (Per-File Extraction)、單檔錯誤隔離 (Fault Isolation)
以及 Stage 1 -> Stage 2 記憶體資料流無縫銜接
"""
import os
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from etl.parsers.dispatcher import extract_file, extract_raw_data_stream
from etl.etl_api import run_extraction_pipeline, run_etl_pipeline, Stage1Result
from etl.schemas.raw_transaction import RawTransactionSchema


class TestStage1PerFileProcessing:
    """測試 Stage 1 逐檔處理與錯誤隔離機制"""

    def test_stage1_result_namedtuple_and_bool_behavior(self):
        """驗證 Stage1Result 同時支援解構賦值與布林真假值判定"""
        # 1. 成功且有資料
        df_dummy = pd.DataFrame([{"a": 1}])
        res_success = Stage1Result(success=True, df=df_dummy)
        assert bool(res_success) is True
        if not res_success:
            pytest.fail("Stage1Result(success=True) 應判定為 True")

        success, df = res_success
        assert success is True
        assert df is not None and len(df) == 1

        # 2. 失敗
        res_fail = Stage1Result(success=False, df=None)
        assert bool(res_fail) is False
        if res_fail:
            pytest.fail("Stage1Result(success=False) 應判定為 False")

        success_f, df_f = res_fail
        assert success_f is False
        assert df_f is None

    def test_extract_file_fault_isolation(self, tmp_path):
        """驗證單檔解析失敗時，回傳 FAILED 字典且不引發全域崩潰"""
        bad_file = tmp_path / "202410_玉山銀行_bad.csv"
        bad_file.write_text("corrupted_data", encoding="utf-8")

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = RuntimeError("檔案損壞模擬")

        with patch("etl.parsers.dispatcher.get_parser", return_value=mock_parser):
            res = extract_file(str(bad_file), force=True)
            assert res["status"] == "FAILED"
            assert res["df"] is None
            assert "檔案損壞模擬" in res["error"]

    def test_extract_raw_data_stream_yields_each_file(self, tmp_path):
        """驗證 extract_raw_data_stream 能以 Generator 逐檔產出"""
        (tmp_path / "202410_玉山銀行_1.csv").write_text("d1", encoding="utf-8")
        (tmp_path / "202410_中國信託_2.csv").write_text("d2", encoding="utf-8")

        def mock_parse(filepath):
            if "玉山" in filepath:
                return pd.DataFrame([{"bank_name": "玉山銀行", "amount": 100}])
            return pd.DataFrame([{"bank_name": "中國信託", "amount": 200}])

        mock_parser = MagicMock()
        mock_parser.parse.side_effect = mock_parse

        with patch("etl.parsers.dispatcher.get_parser", return_value=mock_parser), \
             patch("etl.parsers.dispatcher.FileRegistryManager", None):
            items = list(extract_raw_data_stream(force=True, input_dir=str(tmp_path)))
            assert len(items) == 2
            statuses = [it["status"] for it in items]
            assert statuses == ["SUCCESS", "SUCCESS"]

    def test_run_extraction_pipeline_isolates_bad_file_and_saves_good_file(self, tmp_path):
        """
        核心測試：兩個檔案，一好一壞。
        壞檔應被隔離 (dump 並記錄 failed)，好檔應順利驗證並寫入 raw_transactions，整體流程回傳 True 且包含好檔的 DataFrame！
        """
        # 模擬 extract_raw_data_stream 產出兩個檔案：一個有效，一個無效
        good_df = pd.DataFrame([{
            "transaction_date": "2024-10-01",
            "posting_date": "2024-10-02",
            "bank_no": "808",
            "statement_month": "2024-10-01",
            "raw_merchant": "良好商家",
            "raw_currency": "TWD",
            "raw_amount": 500.0,
            "payment_currency": "TWD",
            "payment_amount": 500.0
        }])

        mock_stream_data = [
            {
                "filename": "good_file.csv",
                "file_hash": "hash_good",
                "file_size": 100,
                "bank_id": "esun",
                "status": "SUCCESS",
                "df": good_df
            },
            {
                "filename": "bad_file.csv",
                "file_hash": "hash_bad",
                "file_size": 100,
                "bank_id": "ctbc",
                "status": "FAILED",
                "df": None,
                "error": "Parser 毀損"
            }
        ]

        mock_loader = MagicMock()
        mock_registry = MagicMock()

        with patch("etl.etl_api.ViewsManager.ensure_raw_schema") as mock_schema, \
             patch("etl.etl_api.get_db_loader", return_value=mock_loader), \
             patch("etl.etl_api.FileRegistryManager", return_value=mock_registry), \
             patch("etl.etl_api.extract_raw_data_stream", return_value=iter(mock_stream_data)):

            result = run_extraction_pipeline(force=True, input_dir=str(tmp_path))

            # 驗證結果
            assert result.success is True
            assert result.df is not None
            assert len(result.df) == 1
            assert result.df["raw_merchant"].iloc[0] == "良好商家"

            # 驗證 Loader 只寫入好檔案
            mock_loader.load.assert_called_once()
            loaded_df = mock_loader.load.call_args[0][0]
            assert len(loaded_df) == 1
            assert "transaction_id" in loaded_df.columns

            # 驗證 Registry 正確登記一成功一失敗
            assert mock_registry.register_file.call_count == 2
            calls = mock_registry.register_file.call_args_list
            registered_statuses = [c[1]["status"] for c in calls]
            assert "SUCCESS" in registered_statuses
            assert "FAILED" in registered_statuses

    def test_run_etl_pipeline_passes_stage1_dataframe_directly_to_stage2(self):
        """驗證 run_etl_pipeline 能將 Stage 1 在記憶體的 DataFrame 直接無縫傳給 Stage 2"""
        dummy_stage1_df = pd.DataFrame([{"transaction_id": "tx123", "raw_merchant": "測試商家"}])

        with patch("etl.etl_api.run_extraction_pipeline", return_value=Stage1Result(success=True, df=dummy_stage1_df)), \
             patch("etl.etl_api.run_stage2_pipeline", return_value=True) as mock_s2:

            overall_success = run_etl_pipeline(force=True)
            assert overall_success is True

            # 關鍵斷言：Stage 2 接收到的 raw_df 正是 Stage 1 傳遞的 DataFrame！免重讀 DB！
            mock_s2.assert_called_once()
            passed_raw_df = mock_s2.call_args[1].get("raw_df")
            assert passed_raw_df is not None
            assert len(passed_raw_df) == 1
            assert passed_raw_df["transaction_id"].iloc[0] == "tx123"
