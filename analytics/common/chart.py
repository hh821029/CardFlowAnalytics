# analytics/common/chart.py
"""
視覺化圖表數據組裝服務 (Chart Payload Builders)
負責將交易與聚合數據轉換為前端圖表 (如 ECharts) 所需的結構化 Payload
"""
from typing import Dict, Any, List
import pandas as pd

from .group_by import aggregate_monthly_by_category, aggregate_monthly_by_card


def build_monthly_trend_payload(df: pd.DataFrame) -> Dict[str, Any]:
    """
    將交易 DataFrame 轉換為月度趨勢 ECharts 堆疊面積圖與統計摘要 Payload
    """
    if df.empty:
        return {
            "months": [],
            "categories": [],
            "series": [],
            "category_summary": [],
            "card_summary": [],
            "summary": {
                "total_amount": 0.0,
                "active_months": 0,
                "card_count": 0,
                "payment_count": 0
            }
        }

    df_cat = aggregate_monthly_by_category(df)
    df_card = aggregate_monthly_by_card(df)

    months = sorted(list(set(df_cat['month'])))
    all_categories = sorted(list(set(df_cat['category'])))

    # 建立 ECharts 堆疊面積/折線圖 series
    series: List[Dict[str, Any]] = []
    for cat in all_categories:
        sub = df_cat[df_cat['category'] == cat].set_index('month')['total_amount'].to_dict()
        data_points = [sub.get(m, 0.0) for m in months]
        series.append({
            "name": cat,
            "type": "line",
            "stack": "Total",
            "areaStyle": {},
            "emphasis": {"focus": "series"},
            "data": data_points
        })

    amount_col = 'payment_amount' if 'payment_amount' in df.columns else 'pay_amount'
    if amount_col in df.columns:
        amt_series = pd.Series(pd.to_numeric(df[amount_col], errors='coerce')).fillna(0.0)
        total_amount = round(float(amt_series.sum()), 2)
    else:
        total_amount = 0.0
    active_months = len(months)
    card_count = df['card_type'].nunique() if 'card_type' in df.columns else 0
    payment_count = df['payment_process'].nunique() if 'payment_process' in df.columns else 0

    return {
        "months": months,
        "categories": all_categories,
        "series": series,
        "category_summary": df_cat.to_dict(orient='records'),
        "card_summary": df_card.to_dict(orient='records'),
        "summary": {
            "total_amount": total_amount,
            "active_months": active_months,
            "card_count": card_count,
            "payment_count": payment_count
        }
    }
