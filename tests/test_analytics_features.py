# tests/test_analytics_features.py
import pytest
import pandas as pd
import sqlite3
import os
from fastapi.testclient import TestClient

from analytics.common import (
    aggregate_monthly_by_category,
    aggregate_monthly_by_card,
    aggregate_monthly_by_payment,
    aggregate_monthly_card_category,
    generate_monthly_pivot,
    generate_monthly_percentage_pivot,
    generate_cross_dimension_pivot
)
from analytics.sankeyflow import build_sankey_flow, build_sankey_dataframe
from analytics.api import _save_to_data_mart
from api.server import app


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
            "normalized_merchant": "麥當勞"
        },
        {
            "transaction_id": "tx02",
            "transaction_date": "2024-05-15",
            "bank_name": "國泰世華",
            "card_type": "CUBE卡",
            "payment_process": "LINE Pay",
            "category": "餐飲食品",
            "payment_amount": 300.0,
            "normalized_merchant": "星巴克"
        },
        {
            "transaction_id": "tx03",
            "transaction_date": "2024-05-20",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "payment_process": "街口支付",
            "category": "生活水電",
            "payment_amount": 1200.0,
            "normalized_merchant": "台電"
        },
        {
            "transaction_id": "tx04",
            "transaction_date": "2024-06-05",
            "bank_name": "台北富邦",
            "card_type": "J卡",
            "payment_process": "一般實體刷卡",
            "category": "餐飲食品",
            "payment_amount": 800.0,
            "normalized_merchant": "王品"
        }
    ]
    return pd.DataFrame(data)


def test_group_by_aggregations(sample_tx_df):
    # 1. aggregate_monthly_by_category
    df_cat = aggregate_monthly_by_category(sample_tx_df)
    assert not df_cat.empty
    assert "month" in df_cat.columns
    assert "total_amount" in df_cat.columns
    # 2024-05 餐飲食品 sum should be 800.0
    may_food = df_cat[(df_cat['month'] == '2024-05') & (df_cat['category'] == '餐飲食品')]
    assert len(may_food) == 1
    assert may_food.iloc[0]['total_amount'] == 800.0
    assert may_food.iloc[0]['txn_count'] == 2

    # 2. aggregate_monthly_by_card
    df_card = aggregate_monthly_by_card(sample_tx_df)
    assert not df_card.empty
    assert "card_type" in df_card.columns

    # 3. aggregate_monthly_by_payment
    df_pay = aggregate_monthly_by_payment(sample_tx_df)
    assert not df_pay.empty
    assert "payment_process" in df_pay.columns

    # 4. aggregate_monthly_card_category
    df_detail = aggregate_monthly_card_category(sample_tx_df)
    assert not df_detail.empty
    assert "card_type" in df_detail.columns
    assert "category" in df_detail.columns


def test_pivot_table_operations(sample_tx_df):
    # 1. generate_monthly_pivot
    pivot = generate_monthly_pivot(sample_tx_df, column_dim='category')
    assert not pivot.empty
    assert '餐飲食品' in pivot.columns
    assert pivot.loc['2024-05', '餐飲食品'] == 800.0

    # 2. generate_monthly_percentage_pivot
    pct_pivot = generate_monthly_percentage_pivot(sample_tx_df, column_dim='category')
    assert not pct_pivot.empty
    # 2024-05 total is 2000, food is 800 -> 40%
    assert pct_pivot.loc['2024-05', '餐飲食品'] == 40.0

    # 3. generate_cross_dimension_pivot
    cross_pivot = generate_cross_dimension_pivot(sample_tx_df, row_dim='card_type', col_dim='payment_process')
    assert not cross_pivot.empty
    assert 'CUBE卡' in cross_pivot.index
    assert 'LINE Pay' in cross_pivot.columns


def test_sankey_flow(sample_tx_df):
    # 1. 測試常規模式 (含 Bank -> Card -> Payment -> Category 四層級)
    flow = build_sankey_flow(sample_tx_df, include_merchants=False, demo_mode=False)
    assert "nodes" in flow
    assert "links" in flow
    assert "summary" in flow
    assert len(flow["nodes"]) > 0
    assert len(flow["links"]) > 0
    assert flow["summary"]["total_amount"] == 2800.0

    layers = {l['layer'] for l in flow['links']}
    assert 'bank_to_card' in layers
    assert 'card_to_payment' in layers
    assert 'payment_to_category' in layers

    # 2. 測試 DEMO 脫敏模式 (CUBE卡保留，J卡收斂為其他卡片；LINE Pay/街口保留)
    demo_flow = build_sankey_flow(sample_tx_df, demo_mode=True)
    card_targets = [l['target'] for l in demo_flow['links'] if l['layer'] == 'bank_to_card']
    assert 'CUBE卡' in card_targets
    assert '其他卡片' in card_targets

    df_links = build_sankey_dataframe(sample_tx_df)
    assert not df_links.empty
    assert "source" in df_links.columns
    assert "target" in df_links.columns
    assert "value" in df_links.columns



def test_data_mart_save(sample_tx_df, tmp_path):
    test_db = os.path.join(tmp_path, "test_analysis.db")
    df_cat = aggregate_monthly_by_category(sample_tx_df)
    _save_to_data_mart({"matrix_monthly_category": df_cat}, db_path=test_db)

    assert os.path.exists(test_db)
    with sqlite3.connect(test_db) as conn:
        df_read = pd.read_sql("SELECT * FROM matrix_monthly_category", conn)
        assert len(df_read) == len(df_cat)


def test_api_endpoints():
    client = TestClient(app)
    
    # 測試月度趨勢 API 端點 (即便資料庫無資料亦回傳 200 結構)
    res_trend = client.get("/api/analytics/monthly-trend")
    assert res_trend.status_code == 200
    json_trend = res_trend.json()
    assert json_trend["success"] is True

    # 測試桑基圖 API 端點
    res_sankey = client.get("/api/analytics/sankey")
    assert res_sankey.status_code == 200
    json_sankey = res_sankey.json()
    assert json_sankey["success"] is True

    # 測試 RFM 視覺化圖表 API 端點
    res_rfm = client.get("/api/analytics/rfm-chart")
    assert res_rfm.status_code == 200
    json_rfm = res_rfm.json()
    assert json_rfm["success"] is True
    assert "merchants" in json_rfm["data"]
    assert "cards" in json_rfm["data"]


def test_merchant_ticket_stats(sample_tx_df):
    from analytics.rfm.service import compute_merchant_ticket_stats
    stats = compute_merchant_ticket_stats(sample_tx_df)
    assert "麥當勞" in stats
    assert stats["麥當勞"]["avg_ticket"] == 500.0
    assert stats["麥當勞"]["count"] == 1.0


def test_build_monthly_trend_payload(sample_tx_df):
    from analytics.common import build_monthly_trend_payload
    payload = build_monthly_trend_payload(sample_tx_df)
    assert "months" in payload
    assert "series" in payload
    assert len(payload["series"]) > 0
    assert payload["summary"]["total_amount"] == 2800.0



def test_time_window_resolution():
    import const
    anchor = "2026-08-26"
    
    # 1. 今年 (THIS_YEAR)
    start_this, end_this = const.TimeWindow.resolve_range("THIS_YEAR", anchor)
    assert start_this == "2026-01-01"
    assert end_this == "2026-08-26"

    # 2. 去年曆年 (LAST_CALENDAR_YEAR)
    start_last_cal, end_last_cal = const.TimeWindow.resolve_range("LAST_CALENDAR_YEAR", anchor)
    assert start_last_cal == "2025-01-01"
    assert end_last_cal == "2025-12-31"

    # 3. 近一年 (1Y / 365天)
    start_1y, end_1y = const.TimeWindow.resolve_range("1Y", anchor)
    assert start_1y == "2025-08-26"
    assert end_1y == "2026-08-26"

    # 4. 全歷史 (LIFETIME)
    start_life, end_life = const.TimeWindow.resolve_range("LIFETIME", anchor)
    assert start_life is None
    assert end_life is None

