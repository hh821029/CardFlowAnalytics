# analytics/common/pivot_table.py
"""
通用樞紐分析矩陣服務 (Pivot Table Analysis)
支援時間軸樞紐表生成、缺失值填補、交叉矩陣與金額佔比計算
"""
import pandas as pd
from typing import Optional, Literal
from analytics.common.group_by import ensure_month_column


def generate_monthly_pivot(
    df: pd.DataFrame,
    column_dim: str = 'category',
    metric: Literal['sum', 'count', 'mean'] = 'sum',
    fill_value: float = 0.0
) -> pd.DataFrame:
    """
    生成月份時間軸樞紐表 (列為 month，欄為指定維度 column_dim)
    """
    if df.empty:
        return pd.DataFrame()

    df_work = ensure_month_column(df)
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    
    if column_dim not in df_work.columns:
        return pd.DataFrame()

    pivot = df_work.pivot_table(
        index='month',
        columns=column_dim,
        values=amount_col,
        aggfunc=metric,
        fill_value=fill_value
    )
    # 按月份由新到舊排序
    pivot = pivot.sort_index(ascending=False)
    return pivot.round(2)


def generate_monthly_percentage_pivot(
    df: pd.DataFrame,
    column_dim: str = 'category',
    fill_value: float = 0.0
) -> pd.DataFrame:
    """
    生成月份時間軸之橫向百分比佔比樞紐表 (每一月份各欄位佔比總和為 100%)
    """
    pivot = generate_monthly_pivot(df, column_dim=column_dim, metric='sum', fill_value=fill_value)
    if pivot.empty:
        return pivot

    row_totals = pivot.sum(axis=1)
    # 避免除以 0
    pct_pivot = pivot.div(row_totals.replace(0, 1), axis=0) * 100
    return pct_pivot.round(2)


def generate_cross_dimension_pivot(
    df: pd.DataFrame,
    row_dim: str = 'card_type',
    col_dim: str = 'payment_process',
    fill_value: float = 0.0
) -> pd.DataFrame:
    """
    生成任意雙維度交叉透視表 (例如：信用卡 × 支付管道)
    """
    if df.empty:
        return pd.DataFrame()

    amount_col = 'payment_amount' if 'payment_amount' in df.columns else 'pay_amount'
    if row_dim not in df.columns or col_dim not in df.columns:
        return pd.DataFrame()

    pivot = df.pivot_table(
        index=row_dim,
        columns=col_dim,
        values=amount_col,
        aggfunc='sum',
        fill_value=fill_value
    )
    return pivot.round(2)
