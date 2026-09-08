# tests/test_transaction_query.py
"""
Unit tests for analytics.common.transaction_query:
- _resolve_bank_names
- get_transactions
- query_transactions_modular
"""
import os
import sqlite3
import pytest
import pandas as pd
from unittest.mock import patch

import const
from analytics.common.transaction_query import (
    _resolve_bank_names,
    get_transactions,
    query_transactions_modular
)


@pytest.fixture(autouse=True)
def force_sqlite_backend(monkeypatch):
    """確保測試環境使用獨立的 SQLite 模式，避免讀取本機 PostgreSQL"""
    monkeypatch.setenv('DB_BACKEND', 'sqlite')


@pytest.fixture
def mock_db_with_rfm(tmp_path):
    """建立包含 rfm_transactions 視圖與表的測試資料庫"""
    db_file = str(tmp_path / "test_transactions.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE rfm_transactions (
                transaction_id TEXT PRIMARY KEY,
                transaction_date TEXT,
                bank_name TEXT,
                card_type TEXT,
                merchant_name TEXT,
                merchant_display TEXT,
                merchant_location TEXT,
                normalized_merchant TEXT,
                payment_process TEXT,
                ec_platform TEXT,
                payment_currency TEXT,
                payment_amount REAL,
                category TEXT,
                sub_category TEXT,
                transaction_type TEXT
            )
        """)
        # 插入多筆測試資料 (含國內/國外、各支付方式、直刷/非直刷、排除交易類型等)
        records = [
            ("tx01", "2026-05-01", "國泰世華", "CUBE卡", "全家便利商店", "全家便利商店", "TW", "全家", "LINE Pay", "", "TWD", 120.0, "餐飲食品", "便利商店", "交易"),
            ("tx02", "2026-05-15", "國泰世華", "CUBE卡", "麥當勞", "麥當勞", "TWN", "麥當勞", "", "", "TWD", 250.0, "餐飲食品", "速食連鎖", "交易"),  # 直刷 (空支付管道)
            ("tx03", "2026-06-01", "台北富邦", "J卡", "APPLE.COM/BILL", "APPLE.COM/BILL", "US", "Apple", "Apple Pay", "", "TWD", 390.0, "娛樂數位", "訂閱服務", "交易"),  # 國外
            ("tx04", "2026-06-10", "玉山銀行", "U Bear卡", "新光三越", "新光三越", "台灣", "新光三越", "街口支付", "", "TWD", 1500.0, "生活購物", "百貨商場", "交易"),
            ("tx05", "2026-06-20", "中國信託", "LINE Pay卡", "日本唐吉訶德", "唐吉訶德", "JP", "唐吉訶德", "一般實體刷卡", "", "JPY", 800.0, "生活購物", "", "交易"),  # 國外、空次分類
            ("tx06", "2026-06-25", "國泰世華", "CUBE卡", "年費", "年費", "TW", "年費", "", "", "TWD", 1800.0, "銀行費用", "", "各項費用"),  # 應被排除
            ("tx07", "2026-06-28", "台北富邦", "J卡", "繳納信用卡費", "信用卡繳款", "TW", "信用卡繳款", "", "", "TWD", 5000.0, "未分類", "", "繳款"),  # 應被排除
            ("tx08", "2026-07-01", "玉山銀行", "U Bear卡", "退刷退貨", "退刷退貨", "TW", "退款", "", "", "TWD", -200.0, "未分類", "", "退刷"),  # 應被排除
        ]
        conn.executemany("""
            INSERT INTO rfm_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
    return db_file


@pytest.fixture
def mock_db_fallback_only(tmp_path):
    """僅有 all_transactions 表（無 rfm_transactions 視圖），用於驗證降級邏輯"""
    db_file = str(tmp_path / "test_fallback.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE all_transactions (
                transaction_id TEXT PRIMARY KEY,
                transaction_date TEXT,
                merchant_name TEXT,
                merchant_display TEXT,
                normalized_merchant TEXT,
                merchant_location TEXT,
                payment_amount REAL,
                bank_name TEXT,
                transaction_type TEXT
            )
        """)
        records = [
            ("fb01", "2026-04-10", "家樂福", "家樂福", "家樂福", "TW", 890.0, "國泰世華", "一般消費"),
            ("fb02", "2026-04-12", "自動扣繳", "繳款", "繳款", "TW", 2000.0, "國泰世華", "繳款"),  # 應被排除
            ("fb03", "2026-04-20", "大潤發", "大潤發", "大潤發", "TW", 450.0, "玉山銀行", "一般消費"),
        ]
        conn.executemany("""
            INSERT INTO all_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
    return db_file


# ==============================================================================
# 1. _resolve_bank_names 測試
# ==============================================================================

def test_resolve_bank_names_known_bank():
    """已知銀行 ID 或別名應解析出對應的中文全稱與代碼"""
    cathay_resolved = _resolve_bank_names(["013"])
    assert any("國泰" in name for name in cathay_resolved)
    assert any("013" in name for name in cathay_resolved)

    esun_resolved = _resolve_bank_names(["esun"])
    assert any("玉山" in name for name in esun_resolved)


def test_resolve_bank_names_unknown_bank():
    """未收錄在 dim_banks 中的自訂名稱應安全保留原名稱"""
    custom = _resolve_bank_names(["神秘銀行", "VirtualBank"])
    assert "神秘銀行" in custom
    assert "VirtualBank" in custom


def test_resolve_bank_names_case_insensitive():
    """英文大小寫不敏感匹配"""
    res_lower = _resolve_bank_names(["ctbc"])
    res_upper = _resolve_bank_names(["CTBC"])
    assert set(res_lower) == set(res_upper)


# ==============================================================================
# 2. get_transactions 測試
# ==============================================================================

def test_get_transactions_normal(mock_db_with_rfm):
    """讀取 rfm_transactions 視圖，預設排除非日常消費 (繳款/費用等)"""
    df = get_transactions(
        window=const.TimeWindow.LIFETIME,
        db_path=mock_db_with_rfm
    )
    assert not df.empty
    expected_cols = [
        "transaction_id", "transaction_date", "bank_name", "card_type",
        "merchant", "merchant_display", "merchant_location", "normalized_merchant",
        "payment_process", "payment_amount", "category"
    ]
    for col in expected_cols:
        assert col in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])


def test_get_transactions_with_time_window(mock_db_with_rfm):
    """指定時間視窗與動態 anchor_date"""
    # 以最新交易日 2026-07-01 為基準日
    df = get_transactions(
        window=const.TimeWindow.LAST_MONTH,
        db_path=mock_db_with_rfm
    )
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert df["transaction_date"].min() >= pd.Timestamp("2026-06-01")


def test_get_transactions_fallback_to_all_transactions(mock_db_fallback_only):
    """當 rfm_transactions 視圖不存在時，自動降級讀取 all_transactions 並排除非消費"""
    df = get_transactions(
        window=const.TimeWindow.LIFETIME,
        db_path=mock_db_fallback_only
    )
    assert not df.empty
    assert len(df) == 2
    assert "fb02" not in df["transaction_id"].values
    assert "家樂福" in df["merchant"].values


def test_get_transactions_both_fail_returns_empty(tmp_path):
    """當資料庫完全不存在或兩張表均不存在時，安全返回空 DataFrame"""
    fake_db = str(tmp_path / "non_existent.db")
    df = get_transactions(db_path=fake_db)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


# ==============================================================================
# 3. query_transactions_modular 測試
# ==============================================================================

def test_query_transactions_modular_base(mock_db_with_rfm):
    """預設條件：自動排除繳款、費用、退刷等非消費"""
    df = query_transactions_modular(db_path=mock_db_with_rfm)
    assert not df.empty
    txn_ids = set(df["transaction_id"])
    assert "tx06" not in txn_ids
    assert "tx07" not in txn_ids
    assert "tx08" not in txn_ids
    assert {"tx01", "tx02", "tx03", "tx04", "tx05"}.issubset(txn_ids)
    dates = list(df["transaction_date"])
    assert dates == sorted(dates, reverse=True)


def test_query_transactions_modular_date_filters(mock_db_with_rfm):
    """測試 start_date 與 end_date 區間篩選"""
    df = query_transactions_modular(
        start_date="2026-05-10",
        end_date="2026-06-15",
        db_path=mock_db_with_rfm
    )
    assert not df.empty
    txn_ids = set(df["transaction_id"])
    assert txn_ids == {"tx02", "tx03", "tx04"}


def test_query_transactions_modular_time_window(mock_db_with_rfm):
    """傳入 time_window 參數自動計算區間"""
    df = query_transactions_modular(
        time_window="UNKNOWN_WINDOW",
        db_path=mock_db_with_rfm
    )
    assert not df.empty


def test_query_transactions_modular_bank_and_card_filter(mock_db_with_rfm):
    """測試銀行名稱 (透過 _resolve_bank_names) 與卡別複合篩選"""
    df = query_transactions_modular(
        banks=["013"],
        cards=["CUBE卡"],
        db_path=mock_db_with_rfm
    )
    assert len(df) == 2
    assert set(df["transaction_id"]) == {"tx01", "tx02"}
    assert all(df["bank_name"] == "國泰世華")
    assert all(df["card_type"] == "CUBE卡")


def test_query_transactions_modular_payment_matrix(mock_db_with_rfm):
    """測試支付管道所有邊界矩陣組合"""
    # 1. payments 包含 LINE Pay + include_direct_payment=True
    df1 = query_transactions_modular(
        payments=["LINE Pay"],
        include_direct_payment=True,
        db_path=mock_db_with_rfm
    )
    assert "tx01" in set(df1["transaction_id"])
    assert "tx02" in set(df1["transaction_id"])

    # 2. payments 包含 LINE Pay + include_direct_payment=False
    df2 = query_transactions_modular(
        payments=["LINE Pay"],
        include_direct_payment=False,
        db_path=mock_db_with_rfm
    )
    assert "tx01" in set(df2["transaction_id"])
    assert "tx02" not in set(df2["transaction_id"])

    # 3. payments=[] + include_direct_payment=True (僅直刷)
    df3 = query_transactions_modular(
        payments=[],
        include_direct_payment=True,
        db_path=mock_db_with_rfm
    )
    assert "tx02" in set(df3["transaction_id"])
    assert "tx01" not in set(df3["transaction_id"])

    # 4. payments=[] + include_direct_payment=False -> 1=0 無資料
    df4 = query_transactions_modular(
        payments=[],
        include_direct_payment=False,
        db_path=mock_db_with_rfm
    )
    assert df4.empty

    # 5. payments=None + include_direct_payment=False -> 僅非直刷
    df5 = query_transactions_modular(
        payments=None,
        include_direct_payment=False,
        db_path=mock_db_with_rfm
    )
    assert "tx02" not in set(df5["transaction_id"])
    assert "tx01" in set(df5["transaction_id"])


def test_query_transactions_modular_location_filters(mock_db_with_rfm):
    """測試國內、國外與特定國家消費地篩選"""
    # 1. 國內 (TW, TWN, 台灣 等)
    df_tw = query_transactions_modular(location="國內", db_path=mock_db_with_rfm)
    assert {"tx01", "tx02", "tx04"}.issubset(set(df_tw["transaction_id"]))
    assert "tx03" not in set(df_tw["transaction_id"])  # US
    assert "tx05" not in set(df_tw["transaction_id"])  # JP

    # 2. 國外 (非 TW/台灣 等)
    df_overseas = query_transactions_modular(location="國外", db_path=mock_db_with_rfm)
    assert set(df_overseas["transaction_id"]) == {"tx03", "tx05"}

    # 3. 同時包含國內與國外 -> 視為不限地點
    df_both = query_transactions_modular(location=["國內", "國外"], db_path=mock_db_with_rfm)
    assert len(df_both) == 5

    # 4. 指定具體代碼 JP
    df_jp = query_transactions_modular(location=["JP"], db_path=mock_db_with_rfm)
    assert set(df_jp["transaction_id"]) == {"tx05"}


def test_query_transactions_modular_fallback_mode(mock_db_fallback_only):
    """測試條件查詢在 rfm_transactions 缺失時降級查詢 all_transactions"""
    df = query_transactions_modular(
        banks=["013"],
        db_path=mock_db_fallback_only
    )
    assert not df.empty
    assert "fb01" in set(df["transaction_id"])
    assert df["category"].iloc[0] == "未分類"
    assert df["sub_category"].iloc[0] == ""
