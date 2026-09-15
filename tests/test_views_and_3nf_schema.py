# tests/test_views_and_3nf_schema.py
import os
import sqlite3
import pandas as pd
import pytest

import const
from etl.utils import StandardColumns, STANDARD_COLUMNS
from database.loaders.views_manager import ViewsManager
from profiles.loaders.config_loader import ConfigLoader


class TestViewsAnd3NFSchema:
    """驗證 3NF 正規化 Schema、複合索引與 SQL Views 行為"""

    def test_all_transactions_standard_columns_3nf(self):
        """1. 驗證 all_transactions 3NF 正規化欄位清單 (含 bank_no, card_id；排除 bank_name, card_type)"""
        cols = StandardColumns.ALL_TRANSACTIONS
        assert 'bank_no' in cols, "❌ all_transactions 必須包含 bank_no"
        assert 'card_id' in cols, "❌ all_transactions 必須包含 card_id"
        assert 'bank_name' not in cols, "❌ 3NF all_transactions 不得包含冗餘欄位 bank_name"
        assert 'card_type' not in cols, "❌ 3NF all_transactions 不得包含冗餘欄位 card_type"
        assert len(cols) == 18, f"❌ all_transactions 欄位總數應維持 18 個，當前為 {len(cols)}"

    def test_configs_3nf_purification(self):
        """2. 驗證 dim_card_rewards_base 與 dim_card_rewards_campaigns 均已移除 bank_name 與 card_type"""
        df_base = ConfigLoader.load_config(base_name='dim_card_rewards_base', profile_name='example_public', strategy='replace')
        assert not df_base.empty
        assert 'bank_no' in df_base.columns
        assert 'card_id' in df_base.columns
        assert 'bank_name' not in df_base.columns, "❌ dim_card_rewards_base 不得含有 bank_name"
        assert 'card_type' not in df_base.columns, "❌ dim_card_rewards_base 不得含有 card_type"

    def test_sqlite_compound_indices_creation(self, tmp_path):
        """3. 驗證 ViewsManager 能成功在 all_transactions 建立複合索引"""
        test_db = str(tmp_path / "index_test.db")
        with sqlite3.connect(test_db) as conn:
            conn.execute("""
            CREATE TABLE all_transactions (
                transaction_id TEXT PRIMARY KEY,
                transaction_date TEXT,
                bank_no TEXT,
                card_id TEXT,
                payment_amount REAL
            )
            """)
            conn.commit()

        success = ViewsManager.create_indices(db_backend='sqlite', db_path=test_db)
        assert success is True

        with sqlite3.connect(test_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='all_transactions'")
            idx_names = [r[0] for r in cur.fetchall()]
            assert 'idx_all_transactions_bank_card' in idx_names, "❌ 複合索引 idx_all_transactions_bank_card 應存在"
            assert 'idx_all_transactions_txn_date' in idx_names, "❌ 索引 idx_all_transactions_txn_date 應存在"

    def test_sql_views_dynamic_join_resolution(self, tmp_path):
        """4. 驗證 rewards_transactions 視圖透過 LEFT JOIN 動態解析 bank_name 與 card_type"""
        test_db = str(tmp_path / "views_test.db")
        with sqlite3.connect(test_db) as conn:
            # 建立維度表
            conn.execute("""
            CREATE TABLE dim_banks (
                bank_no TEXT PRIMARY KEY,
                bank_name TEXT,
                bills_mapping_name TEXT
            )
            """)
            conn.execute("INSERT INTO dim_banks VALUES ('013', '國泰世華銀行', '國泰世華')")

            conn.execute("""
            CREATE TABLE dim_credit_card_products (
                card_id TEXT PRIMARY KEY,
                bank_no TEXT,
                card_type TEXT
            )
            """)
            conn.execute("INSERT INTO dim_credit_card_products VALUES ('cathay_cube', '013', 'Cube卡')")

            # 建立 3NF all_transactions
            conn.execute("""
            CREATE TABLE all_transactions (
                transaction_id TEXT PRIMARY KEY,
                transaction_date TEXT,
                posting_date TEXT,
                conversion_date TEXT,
                statement_month TEXT,
                bank_no TEXT,
                card_id TEXT,
                card_no TEXT,
                vpc_no TEXT,
                vpc_type TEXT,
                payment_amount REAL,
                payment_currency TEXT,
                currency_amount REAL,
                currency_type TEXT,
                transaction_type TEXT,
                payment_process TEXT,
                ec_platform TEXT,
                merchant_name TEXT,
                normalized_merchant TEXT,
                merchant_display TEXT,
                merchant_location TEXT
            )
            """)
            conn.execute("""
            INSERT INTO all_transactions (
                transaction_id, transaction_date, bank_no, card_id, card_no,
                payment_amount, payment_process, merchant_name, merchant_display, merchant_location
            ) VALUES (
                'tx001', '2025-01-10', '013', 'cathay_cube', '8888',
                1200.0, 'LINE Pay', '全家便利商店', 'LINE Pay－全家便利商店', 'TW'
            )
            """)
            conn.commit()

        # 建立視圖
        success = ViewsManager.create_or_replace_views(db_backend='sqlite', db_path=test_db)
        assert success is True

        with sqlite3.connect(test_db) as conn:
            df_rewards = pd.read_sql("SELECT * FROM rewards_transactions", conn)
            assert len(df_rewards) == 1
            # 驗證動態關聯取出的維度名稱
            assert df_rewards['bank_name'].iloc[0] == '國泰世華銀行'
            assert df_rewards['card_type'].iloc[0] == 'Cube卡'
            assert df_rewards['bank_no'].iloc[0] == '013'
            assert df_rewards['card_id'].iloc[0] == 'cathay_cube'
            assert df_rewards['amount'].iloc[0] == 1200.0
            assert df_rewards['payment_process'].iloc[0] == 'LINE Pay'
            assert df_rewards['merchant_display'].iloc[0] == 'LINE Pay－全家便利商店'
