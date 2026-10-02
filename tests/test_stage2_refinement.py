# tests/test_stage2_refinement.py
import pytest
import pandas as pd
import sqlite3
import os

from etl.refinement import refine_transactions, DataRefiner
from etl.etl_api import run_stage2_pipeline
from etl.transformation import transform_data
from database.loaders.views_manager import ViewsManager


def test_refine_transactions_functional():
    """測試純函數式 refine_transactions 能處理 raw 欄位並產出完整商業標籤"""
    raw_df = pd.DataFrame([
        {
            "transaction_id": "tx_mock_001",
            "bank_no": "808",
            "statement_month": "2026-09-01",
            "transaction_date": "2026-09-15",
            "raw_merchant": "麥當勞台北館前店",
            "raw_currency": "TWD",
            "raw_amount": 165.0,
            "payment_currency": "TWD",
            "payment_amount": 165.0,
            "card_no": "1234",
            "raw_location": "TW"
        },
        {
            "transaction_id": "tx_mock_002",
            "bank_no": "808",
            "statement_month": "2026-09-01",
            "transaction_date": "2026-09-16",
            "raw_merchant": "自動扣繳信用卡費",
            "raw_currency": "TWD",
            "raw_amount": 5000.0,
            "payment_currency": "TWD",
            "payment_amount": 5000.0,
            "card_no": None,
            "raw_location": "TW"
        }
    ])

    refined_df = refine_transactions(raw_df)

    assert not refined_df.empty
    assert len(refined_df) == 2
    # 驗證必要商業欄位已生成
    assert 'merchant_display' in refined_df.columns
    assert 'transaction_type' in refined_df.columns
    assert 'card_type' in refined_df.columns

    # 驗證麥當勞交易之商業標籤
    row1 = refined_df.iloc[0]
    assert "麥當勞" in str(row1['merchant_display'])

    # 驗證自動扣繳之交易類型為繳款
    row2 = refined_df.iloc[1]
    assert row2['transaction_type'] == "繳款"


def test_transformation_backward_compatibility():
    """測試 etl/transformation.py 舊介面相容性"""
    raw_df = pd.DataFrame([
        {
            "transaction_id": "tx_compat_001",
            "bank_no": "808",
            "merchant": "全家便利商店",
            "payment_amount": 45.0,
            "card_no": "1234"
        }
    ])

    # 呼叫舊版 transform_data
    df_transformed = transform_data(raw_df)
    assert not df_transformed.empty
    assert 'merchant_display' in df_transformed.columns


def test_run_stage2_pipeline_with_sqlite(tmp_path, monkeypatch):
    """測試 run_stage2_pipeline 直接自 raw_transactions 重跑清洗並入庫的端到端流程"""
    test_db = str(tmp_path / "test_stage2.db")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    import const
    monkeypatch.setattr(const, "DB_PATH", test_db)
    monkeypatch.setattr(const, "TRANSACTIONS_DB_PATH", test_db)

    # 1. 建立 raw_transactions 表並填入假資料，同時建立維度表以供視圖查詢
    ViewsManager.ensure_raw_schema(db_backend='sqlite', db_path=test_db)

    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE IF NOT EXISTS dim_banks (bank_no VARCHAR(3) PRIMARY KEY, bank_name VARCHAR(50), bills_mapping_name VARCHAR(50))")
    conn.execute("INSERT INTO dim_banks VALUES ('808', '玉山商業銀行', '玉山銀行')")
    conn.execute("CREATE TABLE IF NOT EXISTS dim_credit_card_products (card_id VARCHAR(50) PRIMARY KEY, card_type VARCHAR(100))")
    conn.execute("INSERT INTO dim_credit_card_products VALUES ('esun_unicard', '玉山 Unicard')")

    conn.execute("""
        INSERT INTO raw_transactions (
            transaction_id, bank_no, statement_month, transaction_date,
            raw_merchant, raw_amount, payment_amount, card_no, raw_location
        ) VALUES (
            'tx_stage2_101', '808', '2026-09-01', '2026-09-18',
            '康是美台北民生門市', 350.0, 350.0, '5678', 'TW'
        )
    """)
    conn.commit()
    conn.close()

    # 2. 執行 Stage 2 獨立重跑管線
    success = run_stage2_pipeline(db_backend='sqlite', db_path=test_db)
    assert success is True

    # 3. 驗證 all_transactions 實體表已寫入基礎 3NF 商業標籤
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT transaction_id, merchant_name, transaction_type FROM all_transactions WHERE transaction_id='tx_stage2_101'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 'tx_stage2_101'
    assert '康是美' in row[1]
    assert row[2] is not None
    conn.close()


def test_run_stage2_pipeline_empty_db(tmp_path, monkeypatch):
    """測試當 raw_transactions 表不存在或無資料時，run_stage2_pipeline 安全返回 False"""
    empty_db = str(tmp_path / "empty.db")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    import const
    monkeypatch.setattr(const, "DB_PATH", empty_db)
    monkeypatch.setattr(const, "TRANSACTIONS_DB_PATH", empty_db)

    # raw_transactions 尚未建立或為空
    success = run_stage2_pipeline(db_backend='sqlite', db_path=empty_db)
    assert success is False
