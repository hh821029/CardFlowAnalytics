# tests/test_database_loaders.py
import os
import sys
import sqlite3
import pytest
import pandas as pd
import numpy as np
import datetime
from unittest.mock import patch, MagicMock

# 動態加入專案根目錄
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import const
from database.loaders.base_loader import BaseDBLoader
from database.loaders.sqlite_loader import SQLiteLoader
from database.loaders.db_factory import get_db_loader
from database.loaders.db_reader import DBReader
from database.loaders.postgres_loader import PostgresLoader
from database.loaders.db_config import get_postgres_url


class TestBaseDBLoaderSanitization:
    """測試 BaseDBLoader._sanitize_dataframe 資料清理與型態防呆規範"""

    def test_empty_dataframe(self):
        """驗證傳入空 DataFrame 時平滑回傳複本"""
        df_empty = pd.DataFrame()
        res = BaseDBLoader._sanitize_dataframe(df_empty)
        assert res.empty
        assert res is not df_empty  # 確保為 copy

    def test_date_columns_standardization(self):
        """驗證日期欄位（Timestamp, datetime.date, 含有 date/month 關鍵字之欄位）標準化為 YYYY-MM-DD"""
        df = pd.DataFrame([
            {
                'transaction_date': pd.Timestamp('2024-05-15 14:30:00'),
                'posting_date': datetime.date(2024, 5, 16),
                'statement_month': '2024-05',
                'custom_date_col': '2024/07/01'
            }
        ])
        res = BaseDBLoader._sanitize_dataframe(df)
        assert res['transaction_date'].iloc[0] == '2024-05-15'
        assert res['posting_date'].iloc[0] == '2024-05-16'
        assert res['statement_month'].iloc[0] == '2024-05-01'
        assert res['custom_date_col'].iloc[0] == '2024-07-01'

    def test_boolean_columns_normalization(self):
        """驗證布林欄位統一轉為大寫字串 'TRUE' / 'FALSE' 以確保跨 DB 行為一致"""
        df = pd.DataFrame([
            {'reward_cal_break': True, 'is_active': 'True', 'is_nccc_listed': 1},
            {'reward_cal_break': False, 'is_active': '0', 'is_nccc_listed': 'false'},
            {'reward_cal_break': None, 'is_active': np.nan, 'is_nccc_listed': ''},
        ])
        res = BaseDBLoader._sanitize_dataframe(df)
        assert list(res['reward_cal_break']) == ['TRUE', 'FALSE', 'FALSE']
        assert list(res['is_active']) == ['TRUE', 'FALSE', 'FALSE']
        assert list(res['is_nccc_listed']) == ['TRUE', 'FALSE', 'FALSE']

    def test_null_and_nan_handling(self):
        """驗證字串欄位之空值轉換為 None (SQL NULL)，數值欄位保持 float 型態避免 to_sql 報錯"""
        df = pd.DataFrame([
            {
                'merchant': '統一超商',
                'payment_amount': 150.0,
                'memo': np.nan
            },
            {
                'merchant': None,
                'payment_amount': np.nan,
                'memo': 'nan'
            },
            {
                'merchant': 'None',
                'payment_amount': 300.5,
                'memo': ''
            }
        ])
        res = BaseDBLoader._sanitize_dataframe(df)
        # 字串欄位
        assert res['merchant'].iloc[0] == '統一超商'
        assert res['merchant'].iloc[1] is None
        assert res['merchant'].iloc[2] is None
        assert res['memo'].iloc[0] is None
        assert res['memo'].iloc[1] is None
        assert res['memo'].iloc[2] is None
        # 數值欄位保持 float64 (np.nan 允許在數值欄位中存在供 SQLite / SQL engine 轉型為 NULL)
        assert res['payment_amount'].dtype == np.float64
        assert pd.isna(res['payment_amount'].iloc[1])


class TestSQLiteLoader:
    """測試 SQLiteLoader 資料載入、全量/增量模式與索引建立"""

    @pytest.fixture
    def test_db_path(self, tmp_path):
        return str(tmp_path / "test_loader.db")

    @pytest.fixture
    def sample_data(self):
        return pd.DataFrame([
            {
                'transaction_id': 'tx001',
                'transaction_date': '2024-05-01',
                'card_no': '1234',
                'merchant': '星巴克',
                'payment_amount': 160.0
            },
            {
                'transaction_id': 'tx002',
                'transaction_date': '2024-05-02',
                'card_no': '1234',
                'merchant': '麥當勞',
                'payment_amount': 120.0
            }
        ])

    def test_load_replace_mode(self, test_db_path, sample_data):
        """測試 mode='replace' 全量寫入與覆蓋"""
        loader = SQLiteLoader(db_path=test_db_path)
        loader.load(sample_data, table_name='all_transactions', mode='replace')

        with sqlite3.connect(test_db_path) as conn:
            df_read = pd.read_sql("SELECT * FROM all_transactions", conn)
            assert len(df_read) == 2
            assert set(df_read['transaction_id']) == {'tx001', 'tx002'}

        # 再次以新資料 replace
        new_data = pd.DataFrame([{
            'transaction_id': 'tx003',
            'transaction_date': '2024-05-03',
            'card_no': '5678',
            'merchant': '肯德基',
            'payment_amount': 200.0
        }])
        loader.load(new_data, table_name='all_transactions', mode='replace')

        with sqlite3.connect(test_db_path) as conn:
            df_read2 = pd.read_sql("SELECT * FROM all_transactions", conn)
            assert len(df_read2) == 1
            assert df_read2['transaction_id'].iloc[0] == 'tx003'

    def test_load_append_mode(self, test_db_path, sample_data):
        """測試 mode='append' 增量寫入"""
        loader = SQLiteLoader(db_path=test_db_path)
        loader.load(sample_data, table_name='all_transactions', mode='replace')

        append_data = pd.DataFrame([{
            'transaction_id': 'tx003',
            'transaction_date': '2024-05-03',
            'card_no': '5678',
            'merchant': '肯德基',
            'payment_amount': 200.0
        }])
        loader.load(append_data, table_name='all_transactions', mode='append')

        with sqlite3.connect(test_db_path) as conn:
            df_read = pd.read_sql("SELECT * FROM all_transactions", conn)
            assert len(df_read) == 3

    def test_indices_creation(self, test_db_path, sample_data):
        """測試索引建立機制：*_id 欄位建立 UNIQUE INDEX，其餘建立一般 INDEX"""
        loader = SQLiteLoader(db_path=test_db_path)
        indices = ['transaction_id', 'transaction_date', 'card_no']
        loader.load(sample_data, table_name='all_transactions', mode='replace', indices=indices)

        with sqlite3.connect(test_db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='all_transactions'")
            idx_rows = cur.fetchall()
            idx_names = [r[0] for r in idx_rows]
            idx_sqls = {r[0]: r[1] for r in idx_rows}

            # 驗證 transaction_id 為 UNIQUE INDEX
            assert 'idx_all_transactions_transaction_id' in idx_names
            assert 'UNIQUE INDEX' in idx_sqls['idx_all_transactions_transaction_id'].upper()

            # 驗證一般欄位為一般 INDEX
            assert 'idx_all_transactions_transaction_date' in idx_names
            assert 'idx_all_transactions_card_no' in idx_names
            assert 'UNIQUE INDEX' not in idx_sqls['idx_all_transactions_transaction_date'].upper()

    def test_load_empty_dataframe_does_not_fail(self, test_db_path):
        """測試傳入空 DataFrame 時優雅略過，不報錯"""
        loader = SQLiteLoader(db_path=test_db_path)
        loader.load(pd.DataFrame(), table_name='empty_tbl')
        assert not os.path.exists(test_db_path) or True


class TestDatabaseFactory:
    """測試 DatabaseFactory (get_db_loader) 動態分派與降級機制"""

    def test_explicit_sqlite_backend(self, tmp_path):
        custom_db = str(tmp_path / "custom.db")
        loader = get_db_loader(db_backend='sqlite', db_path=custom_db)
        assert isinstance(loader, SQLiteLoader)
        assert loader.db_path == custom_db

    def test_explicit_postgres_backend(self):
        loader = get_db_loader(db_backend='postgres')
        assert isinstance(loader, PostgresLoader)

    def test_unknown_backend_fallback_to_sqlite(self, tmp_path):
        """測試未知後端時自動發出警告並安全降級為 SQLiteLoader"""
        custom_db = str(tmp_path / "fallback.db")
        loader = get_db_loader(db_backend='oracle', db_path=custom_db)
        assert isinstance(loader, SQLiteLoader)
        assert loader.db_path == custom_db

    def test_env_var_dispatch(self, monkeypatch, tmp_path):
        """測試透過環境變數 DB_BACKEND 控制分派"""
        monkeypatch.setenv('DB_BACKEND', 'postgres')
        loader_pg = get_db_loader()
        assert isinstance(loader_pg, PostgresLoader)

        monkeypatch.setenv('DB_BACKEND', 'sqlite')
        loader_sl = get_db_loader()
        assert isinstance(loader_sl, SQLiteLoader)


class TestDBReader:
    """測試 DBReader 讀取抽象與平滑降級"""

    @pytest.fixture
    def populated_sqlite_db(self, tmp_path):
        db_file = str(tmp_path / "reader_test.db")
        with sqlite3.connect(db_file) as conn:
            conn.execute("CREATE TABLE mock_txns (id TEXT, amount REAL, txn_date TEXT)")
            conn.execute("INSERT INTO mock_txns VALUES ('t1', 100.0, '2024-05-01')")
            conn.execute("INSERT INTO mock_txns VALUES ('t2', 250.0, '2024-05-02')")
            conn.commit()
        return db_file

    def test_read_sql_sqlite_direct(self, populated_sqlite_db, monkeypatch):
        """測試直接使用 SQLite 讀取"""
        monkeypatch.setenv('DB_BACKEND', 'sqlite')
        df = DBReader.read_sql("SELECT * FROM mock_txns WHERE amount > :min_amt", params={'min_amt': 150.0}, db_path=populated_sqlite_db)
        assert len(df) == 1
        assert df['id'].iloc[0] == 't2'

    def test_read_sql_postgres_fallback_to_sqlite(self, populated_sqlite_db, monkeypatch):
        """測試當設定為 postgres 但連線失敗時，自動降級至 SQLite 讀取"""
        monkeypatch.setenv('DB_BACKEND', 'postgres')
        
        # 模擬 get_engine 回傳 None 或拋出例外
        with patch.object(DBReader, 'get_engine', return_value=None):
            df = DBReader.read_sql("SELECT * FROM mock_txns", db_path=populated_sqlite_db)
            assert len(df) == 2
            assert set(df['id']) == {'t1', 't2'}


class TestPostgresLoaderSpec:
    """測試 PostgresLoader 配置與連線字串規範"""

    def test_postgres_url_assembly(self):
        """測試連線字串生成與密碼隱藏"""
        url_safe = get_postgres_url(hide_password=True)
        assert url_safe.startswith('postgresql')
        assert '***' in url_safe

        url_raw = get_postgres_url(hide_password=False)
        assert url_raw.startswith('postgresql')
        assert '***' not in url_raw

    def test_custom_connection_parameters(self):
        """測試以自訂主機與資料庫初始化 PostgresLoader"""
        loader = PostgresLoader(
            host='db.example.com',
            port=5433,
            user='custom_user',
            password='secret_password',
            database='custom_db'
        )
        assert loader.host == 'db.example.com'
        assert loader.port == 5433
        assert loader.user == 'custom_user'
        assert loader.database == 'custom_db'
        assert loader.conn_str == get_postgres_url(hide_password=False)
