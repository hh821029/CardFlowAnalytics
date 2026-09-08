# tests/test_analytics_pipeline.py
"""
Unit tests for Analytics base pipeline and Facade API:
- validate_analytics_schema (analytics/__init__.py)
- prepare_analytics_dataset & BaseAnalyticsPipeline (analytics/analytics_base.py)
- run_analytics, sync_rewards_data_mart, get_rewards_summary_mart_data (analytics/api.py)
"""
import os
import sqlite3
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

import const
from analytics import validate_analytics_schema, EXPECTED_RFM_COLUMNS
from analytics.analytics_base import prepare_analytics_dataset, BaseAnalyticsPipeline
from analytics.api import (
    run_analytics,
    _save_to_data_mart,
    sync_rewards_data_mart,
    get_rewards_summary_mart_data
)


@pytest.fixture(autouse=True)
def force_sqlite_backend(monkeypatch):
    """確保測試環境使用獨立的 SQLite 模式，避免讀取本機 PostgreSQL"""
    monkeypatch.setenv('DB_BACKEND', 'sqlite')


@pytest.fixture
def sample_tx_df():
    data = [
        {
            "transaction_id": "tx01",
            "transaction_date": "2024-05-01",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "payment_process": "LINE Pay",
            "category": "餐飲食品",
            "payment_amount": 500.0,
            "normalized_merchant": "麥當勞",
            "merchant_display": "麥當勞"
        },
        {
            "transaction_id": "tx02",
            "transaction_date": "2024-05-15",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "payment_process": "LINE Pay",
            "category": "餐飲食品",
            "payment_amount": 300.0,
            "normalized_merchant": "星巴克",
            "merchant_display": "星巴克"
        },
        {
            "transaction_id": "tx03",
            "transaction_date": "2024-05-20",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "payment_process": "街口支付",
            "category": "生活水電",
            "payment_amount": 1200.0,
            "normalized_merchant": "台電",
            "merchant_display": "台電"
        },
        {
            "transaction_id": "tx04",
            "transaction_date": "2024-06-05",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "payment_process": "一般實體刷卡",
            "category": "餐飲食品",
            "payment_amount": 800.0,
            "normalized_merchant": "王品",
            "merchant_display": "王品"
        }
    ]
    df = pd.DataFrame(data)
    df['transaction_date'] = pd.to_datetime(df['transaction_date'])
    return df


# ==============================================================================
# 1. validate_analytics_schema 測試
# ==============================================================================

def test_validate_analytics_schema_valid(tmp_path):
    """資料表欄位完全符合 StandardColumns.RFM_TRANSACTIONS 時應驗證通過"""
    db_file = str(tmp_path / "valid_schema.db")
    with sqlite3.connect(db_file) as conn:
        cols_sql = ", ".join([f"{c} TEXT" for c in EXPECTED_RFM_COLUMNS])
        conn.execute(f"CREATE TABLE rfm_transactions ({cols_sql})")
        conn.commit()

    is_valid, missing = validate_analytics_schema(db_path=db_file)
    assert is_valid is True
    assert missing == []


def test_validate_analytics_schema_missing_column(tmp_path):
    """缺少特定關鍵欄位時應返回 False 與缺失欄位清單"""
    db_file = str(tmp_path / "missing_schema.db")
    cols = [c for c in EXPECTED_RFM_COLUMNS if c != "payment_amount"]
    with sqlite3.connect(db_file) as conn:
        cols_sql = ", ".join([f"{c} TEXT" for c in cols])
        conn.execute(f"CREATE TABLE rfm_transactions ({cols_sql})")
        conn.commit()

    is_valid, missing = validate_analytics_schema(db_path=db_file)
    assert is_valid is False
    assert "payment_amount" in missing


def test_validate_analytics_schema_merchant_alias(tmp_path):
    """merchant 與 merchant_name 欄位互通容錯測試"""
    db_file = str(tmp_path / "alias_schema.db")
    cols = [c if c != "merchant_name" else "merchant" for c in EXPECTED_RFM_COLUMNS]
    with sqlite3.connect(db_file) as conn:
        cols_sql = ", ".join([f"{c} TEXT" for c in cols])
        conn.execute(f"CREATE TABLE rfm_transactions ({cols_sql})")
        conn.commit()

    is_valid, missing = validate_analytics_schema(db_path=db_file)
    assert is_valid is True
    assert missing == []


def test_validate_analytics_schema_db_error(tmp_path):
    """當資料庫不存在或無該資料表時應優雅捕捉例外並返回 False"""
    fake_db = str(tmp_path / "not_found.db")
    is_valid, missing = validate_analytics_schema(db_path=fake_db)
    assert is_valid is False
    assert missing == EXPECTED_RFM_COLUMNS


# ==============================================================================
# 2. prepare_analytics_dataset 測試
# ==============================================================================

@pytest.fixture
def raw_dataset_sample():
    """提供標準清洗前交易 DataFrame"""
    data = [
        {
            "transaction_id": "tx01",
            "transaction_date": "2026-05-01",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "merchant_name": "統一超商",
            "merchant_display": "統一超商",
            "normalized_merchant": None,  # 需 fallback
            "payment_process": "LINE Pay",
            "payment_amount": "150.5",  # 字串型別需強轉
            "category": "餐飲食品",
            "sub_category": "便利商店"
        },
        {
            "transaction_id": "tx02",
            "transaction_date": "2026-05-05",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "merchant_name": "麥當勞",
            "merchant_display": "麥當勞",
            "normalized_merchant": "麥當勞",
            "payment_process": "",
            "payment_amount": 200,
            "category": None,  # 需補齊為 '未分類'
            "sub_category": None  # 需補齊為 ''
        },
        {
            "transaction_id": "tx03",
            "transaction_date": "2026-05-10",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "merchant_name": "銀行利息",
            "merchant_display": "銀行利息",
            "normalized_merchant": "銀行利息",
            "payment_process": "",
            "payment_amount": "50",
            "category": "銀行費用",  # 預設應被排除
            "sub_category": ""
        },
        {
            "transaction_id": "tx04",
            "transaction_date": "2026-05-15",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "merchant_name": "無次分類商家",
            "merchant_display": "無次分類商家",
            "normalized_merchant": "無次分類商家",
            "payment_process": "街口支付",
            "payment_amount": 300,
            "category": "生活購物",
            "sub_category": "nan"  # 特殊字串空次分類
        }
    ]
    return pd.DataFrame(data)


def test_prepare_analytics_dataset_empty_handling():
    """當底層無任何資料時，應安全返回空 DataFrame"""
    with patch("analytics.analytics_base.get_transactions", return_value=pd.DataFrame()):
        df = prepare_analytics_dataset()
        assert isinstance(df, pd.DataFrame)
        assert df.empty


def test_prepare_analytics_dataset_pipeline_routing(raw_dataset_sample):
    """驗證參數路由：有篩選參數走 query_transactions_modular，無篩選走 get_transactions"""
    with patch("analytics.analytics_base.query_transactions_modular", return_value=raw_dataset_sample.copy()) as mock_query, \
         patch("analytics.analytics_base.get_transactions", return_value=raw_dataset_sample.copy()) as mock_get:
        
        # 1. 帶有篩選條件 (如 banks)
        prepare_analytics_dataset(banks=["013"])
        mock_query.assert_called_once()
        mock_get.assert_not_called()

        mock_query.reset_mock()
        mock_get.reset_mock()

        # 2. include_direct_payment=False 亦應觸發 query_transactions_modular
        prepare_analytics_dataset(include_direct_payment=False)
        mock_query.assert_called_once()
        mock_get.assert_not_called()

        mock_query.reset_mock()
        mock_get.reset_mock()

        # 3. 無篩選參數且 include_direct_payment=True 走 get_transactions(LIFETIME)
        prepare_analytics_dataset()
        mock_get.assert_called_once_with(window=const.TimeWindow.LIFETIME)
        mock_query.assert_not_called()


def test_prepare_analytics_dataset_cleaning_and_fallbacks(raw_dataset_sample):
    """驗證資料型態強轉、商家 Fallback 與預設排除銀行費用/未分類"""
    with patch("analytics.analytics_base.get_transactions", return_value=raw_dataset_sample.copy()):
        df = prepare_analytics_dataset()

        # tx03(銀行費用) 應被預設排除
        assert "tx03" not in df["transaction_id"].values
        # tx02 補齊為 '未分類'，亦應被預設排除
        assert "tx02" not in df["transaction_id"].values

        # 剩餘 tx01 (餐飲食品) 與 tx04 (生活購物)
        assert len(df) == 2
        assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])
        assert pd.api.types.is_float_dtype(df["payment_amount"])
        
        # tx01 normalized_merchant 應由 merchant_display 補齊
        tx01_row = df[df["transaction_id"] == "tx01"].iloc[0]
        assert tx01_row["normalized_merchant"] == "統一超商"
        assert tx01_row["payment_amount"] == 150.5


def test_prepare_analytics_dataset_explicit_categories(raw_dataset_sample):
    """自訂 categories 時應覆蓋預設排除規則"""
    with patch("analytics.analytics_base.get_transactions", return_value=raw_dataset_sample.copy()):
        # 主動請求「銀行費用」
        df = prepare_analytics_dataset(categories=["銀行費用"])
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == "tx03"
        assert df.iloc[0]["category"] == "銀行費用"


def test_prepare_analytics_dataset_sub_category_filtering(raw_dataset_sample):
    """驗證次分類篩選（包含「無次分類」匹配空字串、None、nan）"""
    with patch("analytics.analytics_base.get_transactions", return_value=raw_dataset_sample.copy()):
        # 篩選「無次分類」
        df_no_sub = prepare_analytics_dataset(
            categories=["生活購物"],
            sub_categories=["無次分類"]
        )
        assert len(df_no_sub) == 1
        assert df_no_sub.iloc[0]["transaction_id"] == "tx04"


def test_base_analytics_pipeline_lifecycle(raw_dataset_sample):
    """測試 BaseAnalyticsPipeline 物件封裝調用"""
    with patch("analytics.analytics_base.query_transactions_modular", return_value=raw_dataset_sample.copy()):
        pipeline = BaseAnalyticsPipeline(banks=["013"], categories=["餐飲食品"])
        df_clean = pipeline.prepare_data()
        assert not df_clean.empty
        assert pipeline.df_clean is df_clean
        assert all(df_clean["category"] == "餐飲食品")


# ==============================================================================
# 3. run_analytics Facade 測試
# ==============================================================================

def test_run_analytics_early_return_on_empty():
    """無交易資料時應提前返回，不執行後續模型計算或寫入"""
    with patch("analytics.api.prepare_analytics_dataset", return_value=pd.DataFrame()), \
         patch("analytics.api.calculate_merchant_rfm") as mock_rfm, \
         patch("analytics.api._save_to_data_mart") as mock_save:
        
        run_analytics()
        mock_rfm.assert_not_called()
        mock_save.assert_not_called()


def test_run_analytics_end_to_end_orchestration(tmp_path, sample_tx_df):
    """驗證 run_analytics 完整總調度（RFM、Matrix、樞紐、桑基、報表匯出、Data Mart）"""
    out_rfm = str(tmp_path / "rfm")
    out_matrix = str(tmp_path / "matrix")
    out_db = str(tmp_path / "TransactionsAnalysis.db")
    os.makedirs(out_rfm, exist_ok=True)
    os.makedirs(out_matrix, exist_ok=True)

    with patch("analytics.api.prepare_analytics_dataset", return_value=sample_tx_df.copy()), \
         patch("analytics.api.RFM_OUTPUT_DIR", out_rfm), \
         patch("analytics.api.MATRIX_OUTPUT_DIR", out_matrix), \
         patch("const.ANALYSIS_DB_PATH", out_db):
        
        run_analytics()

        # 1. 驗證 RFM CSV 報表匯出
        assert os.path.exists(os.path.join(out_rfm, "merchant_rfm.csv"))
        assert os.path.exists(os.path.join(out_rfm, "category_rfm.csv"))
        assert os.path.exists(os.path.join(out_rfm, "payment_rfm.csv"))
        assert os.path.exists(os.path.join(out_rfm, "card_rfm.csv"))

        # 2. 驗證 Spending Matrix 報表匯出
        matrix_files = os.listdir(out_matrix)
        assert len(matrix_files) > 0

        # 3. 驗證 Data Mart 資料庫成功寫入各張分析超市表
        assert os.path.exists(out_db)
        with sqlite3.connect(out_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            expected_tables = {
                "rfm_merchants", "rfm_categories", "rfm_payments", "rfm_cards",
                "matrix_monthly_category", "matrix_monthly_card",
                "matrix_monthly_payment", "matrix_monthly_detail", "sankey_flow_links"
            }
            assert expected_tables.issubset(tables)


# ==============================================================================
# 4. sync_rewards_data_mart & get_rewards_summary_mart_data 測試
# ==============================================================================

def test_sync_rewards_data_mart_file_not_found(tmp_path):
    """找不到回饋明細 CSV 時應優雅返回 False"""
    fake_csv = str(tmp_path / "non_existent.csv")
    with patch("const.OUTPUT_DIR", str(tmp_path)):
        success = sync_rewards_data_mart(detailed_csv_path=fake_csv)
        assert success is False


def test_sync_rewards_data_mart_and_get_summary(tmp_path):
    """驗證回饋明細解析、實質回饋率、回饋單位判定與 Data Mart 讀取清洗"""
    csv_file = str(tmp_path / "reward_calculation_detailed.csv")
    db_file = str(tmp_path / "test_rewards_analysis.db")

    reward_data = [
        {
            "transaction_id": "tx01",
            "transaction_date": "2026-05-10",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "payment_amount": 1000.0,
            "calculated_reward": 30.0,
            "reward_type": "小樹點",
            "pool_id": "cube_default",
            "pool_name": "CUBE一般消費",
            "is_capped": "FALSE",
            "cap_amount": ""
        },
        {
            "transaction_id": "tx02",
            "transaction_date": "2026-05-15",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "payment_amount": 2000.0,
            "calculated_reward": 60.0,
            "reward_type": "小樹點",
            "pool_id": "cube_default",
            "pool_name": "CUBE一般消費",
            "is_capped": "TRUE",
            "cap_amount": 1000
        }
    ]
    pd.DataFrame(reward_data).to_csv(csv_file, index=False, encoding="utf-8")

    # 1. 執行同步
    success = sync_rewards_data_mart(detailed_csv_path=csv_file, db_path=db_file)
    assert success is True
    assert os.path.exists(db_file)

    # 2. 驗證資料庫結構
    with sqlite3.connect(db_file) as conn:
        df_summary = pd.read_sql("SELECT * FROM rewards_monthly_summary", conn)
        assert len(df_summary) == 1
        row = df_summary.iloc[0]
        assert row["month"] == "2026-05"
        assert row["bank_name"] == "國泰世華"
        assert row["card_type"] == "CUBE卡"
        assert row["total_spending"] == 3000.0
        assert row["total_reward"] == 90.0
        assert row["effective_rate"] == 3.0
        assert row["reward_unit"] == "小樹點"

        df_pools = pd.read_sql("SELECT * FROM rewards_pool_utilization", conn)
        assert len(df_pools) == 1
        p_row = df_pools.iloc[0]
        assert p_row["pool_name"] == "CUBE一般消費"
        assert p_row["total_reward"] == 90.0
        assert p_row["is_capped"] == 1  # 至少有一筆 is_capped 為 True

    # 3. 測試 get_rewards_summary_mart_data
    with patch("analytics.api.sync_rewards_data_mart", return_value=True):
        summary_payload = get_rewards_summary_mart_data(db_path=db_file)
        assert "monthly_summary" in summary_payload
        assert "pool_utilization" in summary_payload
        assert len(summary_payload["monthly_summary"]) == 1
        assert len(summary_payload["pool_utilization"]) == 1
        assert summary_payload["pool_utilization"][0]["is_capped"] is True
