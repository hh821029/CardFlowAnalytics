# analytics/common/chart.py
"""
視覺化圖表數據組裝服務 (Chart Payload Builders)
負責將交易與聚合數據轉換為前端圖表 (如 ECharts) 所需的結構化 Payload
"""
from typing import Dict, Any, List
import pandas as pd

from .group_by import aggregate_monthly_by_category, aggregate_monthly_by_card


def _generate_continuous_months(start_str: str, end_str: str) -> List[str]:
    """生成從 start_str 到 end_str (含) 的連續 YYYY-MM 清單"""
    sy, sm = map(int, start_str.split('-'))
    ey, em = map(int, end_str.split('-'))
    res = []
    cy, cm = sy, sm
    while (cy < ey) or (cy == ey and cm <= em):
        res.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    return res


def build_monthly_trend_payload(df: pd.DataFrame) -> Dict[str, Any]:
    """
    將交易 DataFrame 轉換為月度消費趨勢 Payload (方案 A：純月度總額直條圖 + 頂端走勢折線圖)
    - 支援連續時序補齊與至少 12 個月歷史保底
    - 提供直條 (Bar) 與折線 (Line) Series
    - 保留 category_summary 供前端 Tooltip 依金額排序展示所有類別
    """
    if df.empty:
        return {
            "months": [],
            "categories": [],
            "series": [],
            "monthly_totals": [],
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

    raw_months = sorted(list(set(df_cat['month'])))
    all_categories = sorted(list(set(df_cat['category'])))

    if not raw_months:
        return {
            "months": [],
            "categories": [],
            "series": [],
            "monthly_totals": [],
            "category_summary": [],
            "card_summary": [],
            "summary": {
                "total_amount": 0.0,
                "active_months": 0,
                "card_count": 0,
                "payment_count": 0
            }
        }

    # 1. 計算連續月份與保底至少 12 個月
    latest_month = raw_months[-1]
    earliest_month = raw_months[0]
    ey, em = map(int, latest_month.split('-'))
    
    # 往前推算 11 個月，得到 12 個月視窗的起點
    target_start_idx = (ey * 12 + em - 1) - 11
    target_sy = target_start_idx // 12
    target_sm = target_start_idx % 12 + 1
    min_window_start = f"{target_sy:04d}-{target_sm:02d}"

    # 若最早月份比 12 個月前更晚，則往前補齊至 12 個月；若更早則從最早月份算起
    start_month = min(earliest_month, min_window_start)
    months = _generate_continuous_months(start_month, latest_month)

    # 2. 計算各月份總支出 (無消費月份填 0.0)
    month_totals_map = df_cat.groupby('month')['total_amount'].sum().to_dict()
    monthly_totals = [round(float(month_totals_map.get(m, 0.0)), 2) for m in months]

    # 3. 建立 ECharts 方案 A series (直條圖 + 頂端折線圖)
    series: List[Dict[str, Any]] = [
        {
            "name": "月度消費",
            "type": "bar",
            "data": monthly_totals,
            "barMaxWidth": 38,
            "itemStyle": {
                "borderRadius": [4, 4, 0, 0]
            }
        },
        {
            "name": "支出走勢",
            "type": "line",
            "data": monthly_totals,
            "symbol": "circle",
            "symbolSize": 8
        }
    ]

    amount_col = 'payment_amount' if 'payment_amount' in df.columns else 'pay_amount'
    if amount_col in df.columns:
        amt_series = pd.Series(pd.to_numeric(df[amount_col], errors='coerce')).fillna(0.0)
        total_amount = round(float(amt_series.sum()), 2)
    else:
        total_amount = round(sum(monthly_totals), 2)
        
    active_months = len(raw_months)
    card_count = df['card_type'].nunique() if 'card_type' in df.columns else 0
    payment_count = df['payment_process'].nunique() if 'payment_process' in df.columns else 0

    return {
        "months": months,
        "categories": all_categories,
        "series": series,
        "monthly_totals": monthly_totals,
        "category_summary": df_cat.to_dict(orient='records'),
        "card_summary": df_card.to_dict(orient='records'),
        "summary": {
            "total_amount": total_amount,
            "active_months": active_months,
            "card_count": card_count,
            "payment_count": payment_count
        }
    }

