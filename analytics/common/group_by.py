# analytics/common/group_by.py
"""
通用多維度 GroupBy 聚合運算服務 (Multi-dimensional Aggregations)
支援月度、卡別、支付管道、消費類別之統計匯總
"""
import pandas as pd
from typing import List, Optional, cast, Union


def ensure_month_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    確保 DataFrame 具備 YYYY-MM 格式之 month 欄位。
    強制優先採用實際刷卡交易日 (transaction_date) 作為 SSOT，若無則依序退守至 billing_date / post_date。
    """
    df_out = df.copy()
    if 'transaction_date' in df_out.columns and df_out['transaction_date'].notna().any():
        dates = pd.to_datetime(df_out['transaction_date'], errors='coerce')
        # 若有少數缺失值，嘗試以 billing_date / post_date 備援補齊
        fallback_col = None
        for col in ['billing_date', 'post_date', 'entry_date']:
            if col in df_out.columns:
                fallback_col = col
                break
        if fallback_col:
            fallback_dates = pd.to_datetime(df_out[fallback_col], errors='coerce')
            if isinstance(dates, pd.Series):
                dates = dates.fillna(fallback_dates)
            else:
                dates = pd.Series(dates).fillna(fallback_dates)
        
        # 轉換為標準 YYYY-MM 字串，完全相容靜態型別檢查
        month_series = pd.Series(dates).astype(str).str.slice(0, 7)
        month_series = month_series.replace({'NaT': 'UNKNOWN', 'nan': 'UNKNOWN', 'None': 'UNKNOWN', '': 'UNKNOWN'})
        df_out['month'] = month_series.fillna('UNKNOWN')
    elif 'month' not in df_out.columns:
        df_out['month'] = 'UNKNOWN'
    return df_out


def aggregate_monthly_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    按「月份 × 消費主類別」分組聚合
    回傳欄位：month, category, total_amount, txn_count, avg_amount
    """
    if df.empty:
        return pd.DataFrame(columns=['month', 'category', 'total_amount', 'txn_count', 'avg_amount'])
    
    df_work = ensure_month_column(df)
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    cat_col = 'category' if 'category' in df_work.columns else 'ec_category'
    
    res = (
        df_work.groupby(['month', cat_col], as_index=False)
        .agg(
            total_amount=(amount_col, 'sum'),
            txn_count=(amount_col, 'count'),
            avg_amount=(amount_col, 'mean')
        )
    )
    if cat_col != 'category':
        res.rename(columns={cat_col: 'category'}, inplace=True)
        
    res['total_amount'] = res['total_amount'].round(2)
    res['avg_amount'] = res['avg_amount'].round(2)
    return res.sort_values(by=['month', 'total_amount'], ascending=[False, False]).reset_index(drop=True)


def aggregate_monthly_by_card(df: pd.DataFrame) -> pd.DataFrame:
    """
    按「月份 × 信用卡別 (含銀行)」分組聚合
    回傳欄位：month, bank_name, card_type, total_amount, txn_count, avg_amount
    """
    if df.empty:
        return pd.DataFrame(columns=['month', 'bank_name', 'card_type', 'total_amount', 'txn_count', 'avg_amount'])
    
    df_work = ensure_month_column(df)
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    group_cols = ['month']
    if 'bank_name' in df_work.columns:
        group_cols.append('bank_name')
    if 'card_type' in df_work.columns:
        group_cols.append('card_type')
        
    res = (
        df_work.groupby(group_cols, as_index=False)
        .agg(
            total_amount=(amount_col, 'sum'),
            txn_count=(amount_col, 'count'),
            avg_amount=(amount_col, 'mean')
        )
    )
    res['total_amount'] = res['total_amount'].round(2)
    res['avg_amount'] = res['avg_amount'].round(2)
    return res.sort_values(by=['month', 'total_amount'], ascending=[False, False]).reset_index(drop=True)


def aggregate_monthly_by_payment(df: pd.DataFrame) -> pd.DataFrame:
    """
    按「月份 × 支付管道」分組聚合
    回傳欄位：month, payment_process, total_amount, txn_count, avg_amount
    """
    if df.empty:
        return pd.DataFrame(columns=['month', 'payment_process', 'total_amount', 'txn_count', 'avg_amount'])
    
    df_work = ensure_month_column(df)
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    pay_col = 'payment_process' if 'payment_process' in df_work.columns else 'mobile_payment'
    
    res = (
        df_work.groupby(['month', pay_col], as_index=False)
        .agg(
            total_amount=(amount_col, 'sum'),
            txn_count=(amount_col, 'count'),
            avg_amount=(amount_col, 'mean')
        )
    )
    if pay_col != 'payment_process':
        res.rename(columns={pay_col: 'payment_process'}, inplace=True)
        
    res['total_amount'] = res['total_amount'].round(2)
    res['avg_amount'] = res['avg_amount'].round(2)
    return res.sort_values(by=['month', 'total_amount'], ascending=[False, False]).reset_index(drop=True)


def aggregate_monthly_card_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    按「月份 × 卡別 × 消費主類別」三維細分聚合
    回傳欄位：month, card_type, category, total_amount, txn_count
    """
    if df.empty:
        return pd.DataFrame(columns=['month', 'card_type', 'category', 'total_amount', 'txn_count'])
    
    df_work = ensure_month_column(df)
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    card_col = 'card_type' if 'card_type' in df_work.columns else 'card_no'
    cat_col = 'category' if 'category' in df_work.columns else 'ec_category'
    
    res = (
        df_work.groupby(['month', card_col, cat_col], as_index=False)
        .agg(
            total_amount=(amount_col, 'sum'),
            txn_count=(amount_col, 'count')
        )
    )
    if card_col != 'card_type':
        res.rename(columns={card_col: 'card_type'}, inplace=True)
    if cat_col != 'category':
        res.rename(columns={cat_col: 'category'}, inplace=True)
        
    res['total_amount'] = res['total_amount'].round(2)
    return res.sort_values(by=['month', 'card_type', 'total_amount'], ascending=[False, True, False]).reset_index(drop=True)
