import pytest
import pandas as pd
import numpy as np
from etl.loading import normalize_to_twd, _standardize_fx_df
import const

def test_standardize_fx_df():
    # 測試 exchange_rate 欄位相容
    df_raw = pd.DataFrame([
        {"conversion_date": "2024-10-15 00:00:00", "currency_type": "jpy", "exchange_rate": "0.2185"},
        {"conversion_date": "2024-11-20", "currency_type": "USD", "fx_rate": 32.45}
    ])
    df_std = _standardize_fx_df(df_raw)
    assert "fx_rate" in df_std.columns
    assert len(df_std) == 2
    assert df_std.iloc[0]["conversion_date"] == "2024-10-15"
    assert df_std.iloc[0]["currency_type"] == "JPY"
    assert df_std.iloc[0]["fx_rate"] == 0.2185

def test_normalize_to_twd_domestic_twd_ignored():
    # 國內台幣消費：無 conversion_date，payment_currency 為 TWD -> 不折算
    df_txns = pd.DataFrame([
        {
            "transaction_id": "txn_1",
            "transaction_date": "2024-10-10",
            "conversion_date": None,
            "payment_currency": "TWD",
            "payment_amount": 1500,
            "currency_type": "TWD"
        }
    ])
    df_res = normalize_to_twd(df_txns)
    assert df_res.iloc[0]["payment_amount"] == 1500
    assert df_res.iloc[0]["payment_currency"] == "TWD"

def test_normalize_to_twd_dual_currency_conversion():
    # 雙幣卡外幣消費：conversion_date 存在，payment_currency 為 JPY -> 折算為 TWD
    df_txns = pd.DataFrame([
        {
            "transaction_id": "txn_2",
            "transaction_date": "2024-10-14",
            "conversion_date": "2024-10-15",
            "payment_currency": "JPY",
            "payment_amount": 10000,
            "currency_type": "JPY"
        }
    ])
    df_fx = pd.DataFrame([
        {
            "conversion_date": "2024-10-15",
            "currency_type": "JPY",
            "fx_rate": 0.2185
        }
    ])
    df_res = normalize_to_twd(df_txns, fx_df=df_fx)
    assert df_res.iloc[0]["payment_currency"] == "TWD"
    assert df_res.iloc[0]["payment_amount"] == 2185  # 10000 * 0.2185 = 2185

def test_normalize_to_twd_missing_fx_fallback(tmp_path):
    # 雙幣外幣消費若查無匯率，應產出異常報表並保留原金額
    df_txns = pd.DataFrame([
        {
            "transaction_id": "txn_3",
            "transaction_date": "2024-10-14",
            "conversion_date": "2024-10-15",
            "payment_currency": "EUR",
            "payment_amount": 100,
            "currency_type": "EUR"
        }
    ])
    df_fx = pd.DataFrame([
        {
            "conversion_date": "2024-10-15",
            "currency_type": "JPY",
            "fx_rate": 0.2185
        }
    ])
    df_res = normalize_to_twd(df_txns, fx_df=df_fx, output_dir=str(tmp_path))
    # 查無匯率時仍為原幣別與原金額
    assert df_res.iloc[0]["payment_currency"] == "EUR"
    assert df_res.iloc[0]["payment_amount"] == 100
    # 檢查異常報告是否產出
    anomaly_csv = tmp_path / "missing_fx_rate_anomalies.csv"
    assert anomaly_csv.exists()
