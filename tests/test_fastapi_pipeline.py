# tests/test_fastapi_pipeline.py
import os
import sys
import sqlite3
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# 動態加入專案根目錄
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import const
from api.server import app
from api.utils import _task_lock
from etl.loading import load_data, TransactionIdGenerator, DBColMapper
from etl.transformation import transform_data
from database.loaders.db_reader import DBReader


client = TestClient(app)


@pytest.fixture(autouse=True)
def set_sqlite_backend_env(monkeypatch):
    """確保測試環境使用 SQLite 後端，避免在無本機 PostgreSQL 服務時產生連線逾時等待"""
    monkeypatch.setenv('DB_BACKEND', 'sqlite')


class TestFastAPIPipelineStreaming:
    """測試 FastAPI SSE 任務串流調度端點與並發鎖機制"""

    def test_run_etl_endpoint_stream(self):
        """測試 GET /api/run/etl SSE 串流響應與執行標記"""
        with patch('api.routers.etl.run_etl_pipeline', return_value=True):
            response = client.get("/api/run/etl?force=false")
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            lines = [line for line in response.iter_lines() if line]
            assert any("啟動 ETL 流程" in line for line in lines)
            assert any("ETL 流程 執行完畢" in line for line in lines)
            assert all(line.startswith("data:") for line in lines)

    def test_run_etl_alias_endpoint(self):
        """測試別名端點 GET /api/etl/run"""
        with patch('api.routers.etl.run_etl_pipeline', return_value=True):
            response = client.get("/api/etl/run")
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]
            assert any("ETL 流程" in line for line in lines)

    def test_run_config_all_stream(self):
        """測試 GET /api/run/config_all 全量設定同步串流"""
        with patch('api.routers.configs.run_all_config_sync', return_value=True):
            response = client.get("/api/run/config_all")
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            lines = [line for line in response.iter_lines() if line]
            assert any("啟動 所有資料同步" in line for line in lines)
            assert any("所有資料同步 執行完畢" in line for line in lines)

    @pytest.mark.parametrize("sub_endpoint,task_label", [
        ("/api/run/config_card", "信用卡資料同步"),
        ("/api/run/config_reward", "回饋規則同步"),
        ("/api/run/config_mer", "特約商店同步"),
        ("/api/run/config_paygate", "支付平台同步"),
        ("/api/run/config_billing_history", "對帳單歷史同步"),
        ("/api/run/config_fx_table", "匯率每日表同步")
    ])
    def test_run_config_sub_tasks_stream(self, sub_endpoint, task_label):
        """測試各子項設定同步端點串流響應"""
        response = client.get(sub_endpoint)
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
        assert any(task_label in line for line in lines)

    def test_task_lock_busy_scenario(self):
        """測試當系統有任務執行中時，並發請求會立即收到 [系統忙碌] 警告且不阻塞"""
        # 手動鎖定 _task_lock 模擬另一執行緒正忙碌
        _task_lock.acquire()
        try:
            response = client.get("/api/run/etl")
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]
            assert any("系統忙碌" in line for line in lines)
        finally:
            _task_lock.release()

    def test_analyzable_data_structure(self):
        """測試 GET /api/analyzable-data 取得標準維度下拉選單資料"""
        response = client.get("/api/analyzable-data")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "banks" in data
        assert "cards" in data
        assert "payment_processes" in data


class TestEndToEndDataPipeline:
    """測試資料管線端到端 (Extract -> Transform -> Load -> Query) 與隔離入庫"""

    @pytest.fixture
    def mock_extracted_df(self):
        """構造包含國內實體、LINE Pay、外幣雙幣與重複交易之原始資料"""
        return pd.DataFrame([
            {
                'transaction_date': '2024-05-01',
                'posting_date': '2024-05-02',
                'conversion_date': '',
                'statement_month': '2024-05',
                'bank_name': '國泰世華',
                'card_type': 'CUBE卡',
                'card_no': '1234',
                'merchant': '連線商業銀行－LINE Pay*統一超商',
                'merchant_location': 'TW',
                'transaction_type': '國內消費',
                'currency_type': 'TWD',
                'currency_amount': 100.0,
                'payment_currency': 'TWD',
                'payment_amount': 100.0
            },
            {
                'transaction_date': '2024-05-10',
                'posting_date': '2024-05-11',
                'conversion_date': '2024-05-12',
                'statement_month': '2024-05',
                'bank_name': '玉山銀行',
                'card_type': '熊本熊卡',
                'card_no': '5678',
                'merchant': 'TOKYO DISNEY RESORT',
                'merchant_location': 'JP',
                'transaction_type': '國外消費',
                'currency_type': 'JPY',
                'currency_amount': 5000.0,
                'payment_currency': 'JPY',
                'payment_amount': 5000.0
            },
            # 重複交易 (同日、同卡、同金額、同商家)
            {
                'transaction_date': '2024-05-01',
                'posting_date': '2024-05-02',
                'conversion_date': '',
                'statement_month': '2024-05',
                'bank_name': '國泰世華',
                'card_type': 'CUBE卡',
                'card_no': '1234',
                'merchant': '連線商業銀行－LINE Pay*統一超商',
                'merchant_location': 'TW',
                'transaction_type': '國內消費',
                'currency_type': 'TWD',
                'currency_amount': 100.0,
                'payment_currency': 'TWD',
                'payment_amount': 100.0
            }
        ])

    @pytest.fixture
    def mock_fx_df(self):
        """模擬匯率表"""
        return pd.DataFrame([
            {
                'conversion_date': '2024-05-12',
                'currency_type': 'JPY',
                'fx_rate': 0.21
            }
        ])

    def test_end_to_end_pipeline_execution(self, mock_extracted_df, mock_fx_df, tmp_path, monkeypatch):
        """測試完整 Transform -> Load -> Database 入庫驗證 (使用 tmp_path 隔離資料庫)"""
        test_db = str(tmp_path / "pipeline_test.db")
        test_output = str(tmp_path / "output")
        os.makedirs(test_output, exist_ok=True)

        # 隔離專案常數
        monkeypatch.setattr(const, 'DB_PATH', test_db)
        monkeypatch.setattr(const, 'OUTPUT_DIR', test_output)

        # 1. Transform 階段 (特店正規化、前綴拆分)
        transformed_df = transform_data(mock_extracted_df)
        assert not transformed_df.empty
        assert 'LINE Pay' in transformed_df['payment_process'].values or 'Line Pay' in transformed_df['payment_process'].values

        # 2. Load 階段 (以 Mock 匯率進行折算入庫)
        with patch('etl.loading.load_fx_table', return_value=mock_fx_df):
            success = load_data(
                final_df=transformed_df,
                force=True,
                db_backend='sqlite',
                output_dir=test_output
            )
            assert success is True

        # 3. 驗證資料庫寫入結果
        assert os.path.exists(test_db)
        with sqlite3.connect(test_db) as conn:
            # (1) 驗證 all_transactions 事實表 (去重與流水號處理)
            df_all = pd.read_sql("SELECT * FROM all_transactions", conn)
            # 原始有 3 筆，其中 2 筆為相同交易，經流水號分組後 transaction_id 不重複
            assert len(df_all) == 3
            assert df_all['transaction_id'].nunique() == 3

            # (2) 驗證 rfm_transactions 匯率折算 (JPY 5000 * 0.21 = 1050 TWD)
            df_rfm = pd.read_sql("SELECT * FROM rfm_transactions WHERE card_type = '熊本熊卡'", conn)
            assert len(df_rfm) == 1
            assert df_rfm['payment_amount'].iloc[0] == 1050.0

            # (3) 驗證 rewards_transactions 存在
            df_rewards = pd.read_sql("SELECT * FROM rewards_transactions", conn)
            assert len(df_rewards) == 3

        # 4. 驗證 DBReader 讀取抽象能正常查詢
        df_query = DBReader.read_sql("SELECT count(*) as cnt FROM all_transactions", db_path=test_db)
        assert df_query['cnt'].iloc[0] == 3

    def test_query_export_endpoint_with_database(self, tmp_path, monkeypatch):
        """測試 GET /api/run/query_export 針對已入庫資料執行篩選並輸出 CSV"""
        test_db = str(tmp_path / "export_test.db")
        test_output = str(tmp_path / "export_output")
        os.makedirs(test_output, exist_ok=True)

        monkeypatch.setattr(const, 'DB_PATH', test_db)
        monkeypatch.setattr(const, 'OUTPUT_DIR', test_output)

        # 建立測試資料 (建立符合 query_transactions_modular 規範之 rfm_transactions 資料表)
        with sqlite3.connect(test_db) as conn:
            conn.execute("""
                CREATE TABLE rfm_transactions (
                    transaction_id TEXT, transaction_date TEXT, bank_name TEXT,
                    card_type TEXT, payment_process TEXT, ec_platform TEXT,
                    merchant_name TEXT, merchant_display TEXT, normalized_merchant TEXT,
                    category TEXT, sub_category TEXT, payment_amount REAL,
                    merchant_location TEXT, transaction_type TEXT
                )
            """)
            conn.execute("""
                INSERT INTO rfm_transactions VALUES 
                ('tx1', '2024-05-01', '國泰世華', 'CUBE卡', '一般實體刷卡', '', '星巴克台北店', '星巴克', '星巴克', '餐飲食品', '咖啡茶飲', 150.0, 'TW', '一般消費'),
                ('tx2', '2024-05-02', '玉山銀行', '熊本熊卡', 'LINE Pay', '', '統一超商台北一店', 'LINE Pay－統一超商', '統一超商', '日常購物', '便利超商', 80.0, 'TW', '一般消費')
            """)
            conn.commit()

        # 呼叫 query_export
        response = client.get("/api/run/query_export?banks=國泰世華")
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]
        assert any("篩選與匯出成功" in line for line in lines)

        # 驗證導出的 CSV 檔案
        export_csv = os.path.join(test_output, 'filtered_transactions.csv')
        assert os.path.exists(export_csv)
        df_exported = pd.read_csv(export_csv)
        assert len(df_exported) == 1
        assert df_exported['bank_name'].iloc[0] == '國泰世華'
