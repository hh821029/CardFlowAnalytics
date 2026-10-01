# tests/test_raw_transactions_schema.py
import sqlite3
import pytest
import os
from database.loaders.views_manager import ViewsManager


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage1_schema.db"
    return str(db_file)


def test_ensure_raw_schema_creates_table_indices_and_view(temp_db):
    """測試 ensure_raw_schema 在 SQLite 能正確建立 raw_transactions 表、索引與 v_raw_transactions 視圖"""
    success = ViewsManager.ensure_raw_schema(db_backend='sqlite', db_path=temp_db)
    assert success is True

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # 1. 驗證 raw_transactions 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='raw_transactions'")
    assert cursor.fetchone() is not None, "raw_transactions 表未被建立"

    # 2. 驗證索引是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='raw_transactions'")
    indices = {row[0] for row in cursor.fetchall()}
    assert "idx_raw_txns_bank_month" in indices
    assert "idx_raw_txns_date" in indices
    assert "idx_raw_txns_card_no" in indices

    # 3. 驗證 v_raw_transactions 視圖是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_raw_transactions'")
    assert cursor.fetchone() is not None, "v_raw_transactions 視圖未被建立"

    conn.close()


def test_raw_transactions_constraints_and_insert(temp_db):
    """測試 raw_transactions 的約束性（PK 唯一性、NOT NULL 檢查）"""
    ViewsManager.ensure_raw_schema(db_backend='sqlite', db_path=temp_db)

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # 正常插入
    cursor.execute("""
        INSERT INTO raw_transactions (
            transaction_id, bank_no, statement_month, transaction_date,
            raw_merchant, raw_amount, payment_amount
        ) VALUES (
            'tx_001', '808', '2026-09-01', '2026-09-15',
            '全家便利商店', 105.0, 105.0
        )
    """)
    conn.commit()

    # 測試 PK 唯一性 (重複 tx_001 應拋出 IntegrityError)
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("""
            INSERT INTO raw_transactions (
                transaction_id, bank_no, statement_month, transaction_date,
                raw_merchant, raw_amount, payment_amount
            ) VALUES (
                'tx_001', '808', '2026-09-01', '2026-09-15',
                '重複交易', 200.0, 200.0
            )
        """)

    # 測試 NOT NULL 約束 (缺 bank_no 應拋出 IntegrityError)
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("""
            INSERT INTO raw_transactions (
                transaction_id, bank_no, statement_month, transaction_date,
                raw_merchant, raw_amount, payment_amount
            ) VALUES (
                'tx_002', NULL, '2026-09-01', '2026-09-15',
                '缺銀行代碼', 100.0, 100.0
            )
        """)

    conn.close()


def test_v_raw_transactions_join_dim_banks(temp_db):
    """測試 v_raw_transactions 視圖自動 LEFT JOIN dim_banks 補充 bank_name"""
    ViewsManager.ensure_raw_schema(db_backend='sqlite', db_path=temp_db)

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # 建立測試用 dim_banks 維度表
    cursor.execute("""
        CREATE TABLE dim_banks (
            bank_no VARCHAR(3) PRIMARY KEY,
            bank_name VARCHAR(50),
            bills_mapping_name VARCHAR(50)
        )
    """)
    cursor.execute("INSERT INTO dim_banks VALUES ('808', '玉山商業銀行', '玉山銀行')")
    cursor.execute("INSERT INTO dim_banks VALUES ('013', '國泰世華商業銀行', '國泰世華')")

    # 插入兩筆 raw 交易 (一筆在 dim_banks，一筆為未映射未知銀行)
    cursor.execute("""
        INSERT INTO raw_transactions (
            transaction_id, bank_no, statement_month, transaction_date,
            raw_merchant, raw_amount, payment_amount, card_no
        ) VALUES (
            'tx_esun', '808', '2026-09-01', '2026-09-20',
            '玉山實體刷卡測試', 500.0, 500.0, '1234'
        )
    """)
    cursor.execute("""
        INSERT INTO raw_transactions (
            transaction_id, bank_no, statement_month, transaction_date,
            raw_merchant, raw_amount, payment_amount, card_no
        ) VALUES (
            'tx_unknown', '999', '2026-09-01', '2026-09-21',
            '未知銀行測試', 300.0, 300.0, '9999'
        )
    """)
    conn.commit()

    # 查詢視圖
    cursor.execute("SELECT transaction_id, bank_no, bank_name, bills_mapping_name, card_no FROM v_raw_transactions ORDER BY transaction_id")
    rows = cursor.fetchall()
    assert len(rows) == 2

    # tx_esun: 正確關聯出玉山商業銀行
    assert rows[0][0] == 'tx_esun'
    assert rows[0][1] == '808'
    assert rows[0][2] == '玉山商業銀行'
    assert rows[0][3] == '玉山銀行'
    assert rows[0][4] == '1234'

    # tx_unknown: 查無 dim_banks 時 fallback 為空字串 '' 而非崩潰
    assert rows[1][0] == 'tx_unknown'
    assert rows[1][1] == '999'
    assert rows[1][2] == ''
    assert rows[1][3] == ''

    conn.close()


def test_existing_all_transactions_remains_intact(temp_db):
    """驗證現有 all_transactions 與視圖建立完全不受 raw_transactions 影響"""
    ViewsManager.ensure_raw_schema(db_backend='sqlite', db_path=temp_db)

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # 模擬建立 all_transactions 表
    cursor.execute("""
        CREATE TABLE all_transactions (
            transaction_id VARCHAR(32) PRIMARY KEY,
            bank_no VARCHAR(3),
            card_id VARCHAR(50),
            card_no VARCHAR(4),
            vpc_no VARCHAR(4),
            vpc_type VARCHAR(50),
            transaction_date DATE,
            posting_date DATE,
            payment_amount NUMERIC(12,2),
            payment_currency VARCHAR(3),
            currency_amount NUMERIC(12,2),
            currency_type VARCHAR(3),
            conversion_date DATE,
            statement_month DATE,
            transaction_type VARCHAR(50),
            payment_process VARCHAR(100),
            ec_platform VARCHAR(100),
            merchant_name VARCHAR(500),
            normalized_merchant VARCHAR(500),
            merchant_display VARCHAR(500),
            merchant_location VARCHAR(10)
        )
    """)
    conn.commit()

    # 調用 create_or_replace_views
    result = ViewsManager.create_or_replace_views(db_backend='sqlite', db_path=temp_db, conn=conn)
    assert result is True

    # 驗證 rewards_transactions, rfm_transactions 與 v_raw_transactions 同時存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = {row[0] for row in cursor.fetchall()}
    assert "rewards_transactions" in views
    assert "rfm_transactions" in views
    assert "v_raw_transactions" in views

    conn.close()
