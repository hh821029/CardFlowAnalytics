# api/routers/analytics.py
"""
RFM 分析、回饋金計算 (直連 C# 瀑布式引擎)、交易 SQL 篩選導出與視覺化數據查詢 API 路由器模組
"""
import os
import re
import json
import sqlite3
import logging
from typing import Optional, List, Dict, Any, cast, Union
import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response

import const
from analytics.api import run_analytics
from analytics.analytics_base import prepare_analytics_dataset
from analytics.common.transaction_query import query_transactions_modular
from analytics.common import (
    aggregate_monthly_by_category,
    aggregate_monthly_by_card,
    aggregate_monthly_by_payment,
    aggregate_monthly_card_category,
    generate_monthly_pivot,
    generate_monthly_percentage_pivot
)
from analytics.sankeyflow import build_sankey_flow
from api.utils import run_task_and_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/run", tags=["Analytics"])
data_router = APIRouter(prefix="/api/analytics", tags=["AnalyticsData"])

# C# RewardEngine.Api 的位址 (預設為 http://127.0.0.1:5000/api/run/rewards，Docker 內環境變數自動覆蓋)
CSHARP_REWARDS_API_URL = os.getenv("CSHARP_REWARDS_API_URL", "http://127.0.0.1:5000/api/run/rewards")


async def stream_csharp_rewards_calculation(
    banks: Optional[List[str]] = None,
    cards: Optional[List[str]] = None,
    payments: Optional[List[str]] = None,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[List[str]] = None,
    enable_billing_validation: bool = True,
    limit_by_card_start: bool = False
):
    """
    透過 HTTP SSE 串流連線 C# RewardEngine.Api 服務並將 Log 即時轉發給 Web 前端
    """
    params = {}
    if banks: params['banks'] = ",".join(banks)
    if cards: params['cards'] = ",".join(cards)
    if payments: params['payments'] = ",".join(payments)
    if time_window: params['time_window'] = time_window
    if start_date: params['start_date'] = start_date
    if end_date: params['end_date'] = end_date
    if location: params['location'] = ",".join(location) if isinstance(location, list) else location
    params['enable_billing_validation'] = str(enable_billing_validation).lower()
    params['limit_by_card_start'] = str(limit_by_card_start).lower()

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            async with client.stream("GET", CSHARP_REWARDS_API_URL, params=params) as response:
                async for chunk in response.aiter_text():
                    yield chunk
            
            # C# 運算完成後，自動將明細匯總寫入 Data Mart
            try:
                from analytics.api import sync_rewards_data_mart
                if sync_rewards_data_mart():
                    yield "data: 💾 [Data Mart] 回饋計算摘要已成功寫入 TransactionsAnalysis.db ([rewards_monthly_summary], [rewards_pool_utilization])\n\n"
            except Exception as dm_err:
                logger.warning(f"⚠️ 自動同步回饋至 Data Mart 失敗: {dm_err}")
        except Exception as e:
            yield f"data: ❌ [C# 引擎連線失敗] 無法連線至 C# RewardEngine 服務 ({CSHARP_REWARDS_API_URL}): {e}\n\n"


@router.get("/analytics")
async def api_run_analytics(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    include_direct_payment: Optional[str] = "true",
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None
):
    """執行全方位 RFM 分析計算並產出矩陣報表"""
    bank_list = [b.strip() for b in banks.split(',')] if banks else None
    card_list = [c.strip() for c in cards.split(',')] if cards else None
    pay_list = [p.strip() for p in payments.split(',')] if payments else None
    loc_list = [l.strip() for l in location.split(',')] if location else None
    cat_list = [c.strip() for c in categories.split(',')] if categories else None
    sub_cat_list = [sc.strip() for sc in sub_categories.split(',')] if sub_categories else None
    is_include_direct = include_direct_payment.strip().lower() in ('true', '1', 'yes') if include_direct_payment is not None else True

    def run_task():
        run_analytics(
            banks=bank_list,
            cards=card_list,
            payments=pay_list,
            include_direct_payment=is_include_direct,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=loc_list,
            categories=cat_list,
            sub_categories=sub_cat_list
        )
    return StreamingResponse(run_task_and_stream(run_task, "RFM 分析", require_db=True), media_type="text/event-stream")


@router.get("/rewards")
async def api_run_rewards(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    enable_billing_validation: bool = True,
    limit_by_card_start: bool = False
):
    """啟動信用卡回饋金計算引擎 (直連 C# 瀑布式引擎)"""
    bank_list = [b.strip() for b in banks.split(',')] if banks else None
    card_list = [c.strip() for c in cards.split(',')] if cards else None
    pay_list = [p.strip() for p in payments.split(',')] if payments else None
    loc_list = [l.strip() for l in location.split(',')] if location else None

    return StreamingResponse(
        stream_csharp_rewards_calculation(
            banks=bank_list,
            cards=card_list,
            payments=pay_list,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=loc_list,
            enable_billing_validation=enable_billing_validation,
            limit_by_card_start=limit_by_card_start
        ),
        media_type="text/event-stream"
    )


@router.get("/query_export")
async def api_run_query_export(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    include_direct_payment: Optional[str] = "true",
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None
):
    """執行交易動態 SQL 條件篩選並導出 CSV"""
    bank_list = [b.strip() for b in banks.split(',')] if banks else None
    card_list = [c.strip() for c in cards.split(',')] if cards else None
    pay_list = [p.strip() for p in payments.split(',')] if payments else None
    loc_list = [l.strip() for l in location.split(',')] if location else None
    cat_list = [c.strip() for c in categories.split(',')] if categories else None
    sub_cat_list = [sc.strip() for sc in sub_categories.split(',')] if sub_categories else None
    is_include_direct = include_direct_payment.strip().lower() in ('true', '1', 'yes') if include_direct_payment is not None else True

    def run_task():
        logger.info("⚙️ 啟動 SQL 條件篩選與匯出任務...")
        df = query_transactions_modular(
            banks=bank_list,
            cards=card_list,
            payments=pay_list,
            include_direct_payment=is_include_direct,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=loc_list
        )
        
        if df.empty:
            logger.warning("⚠️ 篩選結果為空，跳過 CSV 匯出作業。")
            return
            
        if cat_list and 'category' in df.columns:
            df = df[df['category'].isin(cat_list)]
            
        if sub_cat_list and 'sub_category' in df.columns:
            has_no_sub = '無次分類' in sub_cat_list or '' in sub_cat_list
            mask = df['sub_category'].isin(sub_cat_list)
            if has_no_sub:
                sub_cat_str = df['sub_category'].astype(str).str.strip()
                mask = mask | (df['sub_category'] == '') | df['sub_category'].isna() | sub_cat_str.isin(['', 'nan', 'None'])
            df = df[mask]

        if df.empty:
            logger.warning("⚠️ 分類篩選後結果為空，跳過 CSV 匯出作業。")
            return

        csv_path = os.path.join(const.OUTPUT_DIR, 'filtered_transactions.csv')
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 篩選與匯出成功！結果已儲存至：output/filtered_transactions.csv，共計 {len(df)} 筆交易。")

    return StreamingResponse(run_task_and_stream(run_task, "SQL 篩選與匯出", require_db=True), media_type="text/event-stream")


# =========================================================================
# 視覺化圖表資料查詢 API (Visual Dashboard Endpoints)
# =========================================================================

def _extract_dataset_from_query(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    include_direct_payment: Optional[str] = "true",
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None
) -> pd.DataFrame:
    bank_list = [b.strip() for b in banks.split(',')] if banks else None
    card_list = [c.strip() for c in cards.split(',')] if cards else None
    pay_list = [p.strip() for p in payments.split(',')] if payments else None
    loc_list = [l.strip() for l in location.split(',')] if location else None
    cat_list = [c.strip() for c in categories.split(',')] if categories else None
    sub_cat_list = [sc.strip() for sc in sub_categories.split(',')] if sub_categories else None
    is_include_direct = include_direct_payment.strip().lower() in ('true', '1', 'yes') if include_direct_payment is not None else True

    return prepare_analytics_dataset(
        banks=bank_list,
        cards=card_list,
        payments=pay_list,
        include_direct_payment=is_include_direct,
        time_window=time_window,
        start_date=start_date,
        end_date=end_date,
        location=loc_list,
        categories=cat_list,
        sub_categories=sub_cat_list
    )


@data_router.get("/monthly-trend")
async def get_monthly_trend(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    include_direct_payment: Optional[str] = "true",
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None
):
    """查詢月份消費趨勢資料 (含月度加總、類別矩陣與卡別矩陣)"""
    try:
        df = _extract_dataset_from_query(
            banks=banks, cards=cards, payments=payments,
            include_direct_payment=include_direct_payment,
            time_window=time_window, start_date=start_date,
            end_date=end_date, location=location,
            categories=categories, sub_categories=sub_categories
        )
        if df.empty:
            return JSONResponse(content={
                "success": True,
                "data": {
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
            })

        df_cat = aggregate_monthly_by_category(df)
        df_card = aggregate_monthly_by_card(df)
        pivot_cat = generate_monthly_pivot(df, column_dim='category')

        months = sorted(list(set(df_cat['month'])))
        all_categories = sorted(list(set(df_cat['category'])))
        
        # 建立 ECharts 堆疊面積/折線圖 series
        series = []
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

        total_amount = round(float(df['payment_amount'].sum()), 2)
        active_months = len(months)
        card_count = df['card_type'].nunique() if 'card_type' in df.columns else 0
        payment_count = df['payment_process'].nunique() if 'payment_process' in df.columns else 0

        return JSONResponse(content={
            "success": True,
            "data": {
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
        })
    except Exception as e:
        logger.error(f"❌ 查詢月度趨勢失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@data_router.get("/sankey")
async def get_sankey_flow_data(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    include_direct_payment: Optional[str] = "true",
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None,
    include_merchants: bool = False,
    demo_mode: Optional[str] = "true"
):
    """查詢金流桑基圖 (Sankey Flow) nodes 與 links 結構 (支援四層級與 DEMO 脫敏白名單模式)"""
    try:
        df = _extract_dataset_from_query(
            banks=banks, cards=cards, payments=payments,
            include_direct_payment=include_direct_payment,
            time_window=time_window, start_date=start_date,
            end_date=end_date, location=location,
            categories=categories, sub_categories=sub_categories
        )
        is_demo = str(demo_mode).strip().lower() in ('true', '1', 'yes') if demo_mode is not None else False
        flow_data = build_sankey_flow(df, include_merchants=include_merchants, demo_mode=is_demo)
        return JSONResponse(content={"success": True, "data": flow_data})
    except Exception as e:
        logger.error(f"❌ 查詢桑基圖數據失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@data_router.get("/rfm-chart")
async def get_rfm_chart_data(
    window: Optional[str] = "life",
    category: Optional[str] = None,
    limit: int = 200
):
    """查詢 RFM 視覺化圖表資料 (客單價 vs 標準差氣泡圖、客群分佈統計、信用卡置頂排序)"""
    try:
        prefix = f"{window}_" if window and window != "life" else "life_"
        db_path = const.ANALYSIS_DB_PATH
        df_merchants = pd.DataFrame()
        df_cards = pd.DataFrame()

        # 優先從 TransactionsAnalysis.db 讀取
        if os.path.exists(db_path):
            try:
                with sqlite3.connect(db_path) as conn:
                    df_merchants = pd.read_sql_query("SELECT * FROM rfm_merchants", conn)
                    try:
                        df_cards = pd.read_sql_query("SELECT * FROM rfm_cards", conn)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"⚠️ 從 DB 讀取 RFM 失敗: {e}")

        # Fallback 讀取 CSV
        if df_merchants.empty:
            csv_path = os.path.join(const.OUTPUT_DIR, 'rfm', 'merchant_rfm.csv')
            if os.path.exists(csv_path):
                df_merchants = pd.read_csv(csv_path, encoding='utf-8')

        if df_cards.empty:
            card_csv_path = os.path.join(const.OUTPUT_DIR, 'rfm', 'card_rfm.csv')
            if os.path.exists(card_csv_path):
                df_cards = pd.read_csv(card_csv_path, encoding='utf-8')

        if df_merchants.empty:
            return JSONResponse(content={
                "success": True,
                "data": {
                    "merchants": [],
                    "segment_counts": {},
                    "categories": [],
                    "top_by_category": [],
                    "cards": [],
                    "median_avg_ticket": 0.0,
                    "median_std_ticket": 0.0
                }
            })

        # 1. 提取所有有效分類清單 (在篩選前提取)
        all_categories = sorted([str(c) for c in df_merchants['category'].unique() if pd.notna(c) and str(c).strip() != '' and str(c).strip() != 'nan']) if 'category' in df_merchants.columns else []

        m_col = f"{prefix}monetary" if f"{prefix}monetary" in df_merchants.columns else "life_monetary"
        f_col = f"{prefix}frequency" if f"{prefix}frequency" in df_merchants.columns else "life_frequency"
        r_col = f"{prefix}recency_days" if f"{prefix}recency_days" in df_merchants.columns else "life_recency_days"

        # 2. 計算各商家的單筆交易明細統計 (平均客單價 μ, 樣本標準差 σ, 變異係數 CV)
        merchant_stats: Dict[str, Dict[str, float]] = {}
        try:
            df_tx = _extract_dataset_from_query(time_window=window)
            if not df_tx.empty and 'payment_amount' in df_tx.columns:
                m_field = 'normalized_merchant' if 'normalized_merchant' in df_tx.columns else 'merchant_display'
                if m_field in df_tx.columns:
                    df_tx_clean = cast(pd.DataFrame, df_tx[df_tx[m_field].notna() & (df_tx[m_field] != '')].copy())
                    amount_series = pd.to_numeric(df_tx_clean['payment_amount'], errors='coerce')
                    if isinstance(amount_series, pd.Series):
                        df_tx_clean['payment_amount'] = amount_series.fillna(0.0)
                    else:
                        df_tx_clean['payment_amount'] = pd.Series(amount_series).fillna(0.0)

                    for m_name, group in df_tx_clean.groupby(m_field):
                        group_df = cast(pd.DataFrame, group)
                        pmt_val = pd.to_numeric(group_df['payment_amount'], errors='coerce')
                        pmt_series = pmt_val.dropna() if isinstance(pmt_val, pd.Series) else pd.Series(pmt_val).dropna()
                        cnt = len(pmt_series)
                        mean_amt = float(cast(Any, pmt_series.mean())) if cnt > 0 else 0.0
                        std_amt = float(cast(Any, pmt_series.std(ddof=1))) if cnt >= 2 else 0.0
                        if pd.isna(std_amt):
                            std_amt = 0.0
                        cv_amt = round(std_amt / mean_amt, 3) if mean_amt > 0 else 0.0
                        merchant_stats[str(m_name).strip()] = {
                            'avg_ticket': round(mean_amt, 2),
                            'std_ticket': round(std_amt, 2),
                            'cv': cv_amt,
                            'count': float(cnt)
                        }
        except Exception as stat_err:
            logger.warning(f"⚠️ 計算單筆標準差統計失敗: {stat_err}")

        # 3. 計算各生活消費領域 Top 3 商家排行 (依 M 累積金額降冪)
        top_by_category = []
        if 'category' in df_merchants.columns and m_col in df_merchants.columns:
            df_calc = df_merchants.copy()
            df_calc[m_col] = cast(pd.Series, pd.to_numeric(df_calc[m_col], errors='coerce')).fillna(0.0)
            
            valid_cats = cast(pd.DataFrame, df_calc[
                df_calc['category'].notna() & 
                (df_calc['category'] != '') & 
                (df_calc['category'] != '未分類') & 
                (df_calc['category'] != 'nan') &
                (df_calc[m_col] > 0)
            ])

            # 若前端指定特定類別，則僅計算該類別 Top 3
            if category and category != 'all':
                valid_cats = cast(pd.DataFrame, valid_cats[valid_cats['category'] == category])

            for cat_name, group in valid_cats.groupby('category'):
                group_df = cast(pd.DataFrame, group)
                top_3 = cast(pd.DataFrame, group_df.sort_values(by=m_col, ascending=False)).head(3)
                for rank, (_, row) in enumerate(top_3.iterrows(), start=1):
                    top_by_category.append({
                        "category": str(cat_name),
                        "rank": rank,
                        "name": str(row.get('normalized_merchant', '')),
                        "sub_category": str(row.get('sub_category', '') if pd.notna(row.get('sub_category')) and str(row.get('sub_category')) != 'nan' else ''),
                        "monetary": float(pd.to_numeric(row.get(m_col, 0), errors='coerce') or 0.0),
                        "frequency": int(pd.to_numeric(row.get(f_col, 0), errors='coerce') or 0),
                        "recency": int(pd.to_numeric(row.get(r_col, 9999), errors='coerce') or 9999),
                        "segment": str(row.get('segment', '一般活躍 (Active)'))
                    })

        # 4. 構建全量有效商家清單，以計算不隨分類篩選變動之「全類別中位數 (Global Medians)」
        if m_col in df_merchants.columns:
            df_merchants_sorted = cast(pd.DataFrame, df_merchants.sort_values(by=m_col, ascending=False))
        else:
            df_merchants_sorted = df_merchants.copy()

        all_merchants_processed = []
        for _, row in df_merchants_sorted.iterrows():
            name_str = str(row.get('normalized_merchant', '')).strip()
            m_val = float(pd.to_numeric(row.get(m_col, 0), errors='coerce') or 0.0)
            f_val = int(pd.to_numeric(row.get(f_col, 0), errors='coerce') or 0)
            r_val = int(pd.to_numeric(row.get(r_col, 9999), errors='coerce') or 9999)

            stats = merchant_stats.get(name_str)
            if stats:
                avg_ticket = stats['avg_ticket']
                std_ticket = stats['std_ticket']
                cv_val = stats['cv']
            else:
                avg_ticket = round(m_val / f_val, 2) if f_val > 0 else 0.0
                std_ticket = 0.0
                cv_val = 0.0

            all_merchants_processed.append({
                "name": name_str,
                "recency": r_val,
                "frequency": f_val,
                "monetary": m_val,
                "avg_ticket": avg_ticket,
                "std_ticket": std_ticket,
                "cv": cv_val,
                "segment": str(row.get('segment', '一般活躍 (Active)')),
                "category": str(row.get('category', '未分類')),
                "sub_category": str(row.get('sub_category', '') if pd.notna(row.get('sub_category')) and str(row.get('sub_category')) != 'nan' else '')
            })

        # 計算全類別（Global）固定的客單價與標準差中位數
        global_avg_list = [m['avg_ticket'] for m in all_merchants_processed if m['avg_ticket'] > 0]
        global_std_list = [m['std_ticket'] for m in all_merchants_processed if m['std_ticket'] > 0]
        global_median_avg = float(pd.Series(global_avg_list).median()) if global_avg_list else 183.0
        global_median_std = float(pd.Series(global_std_list).median()) if global_std_list else 73.0
        if pd.isna(global_median_avg): global_median_avg = 183.0
        if pd.isna(global_median_std): global_median_std = 73.0

        # 5. 類別篩選 (若有傳入特定 category，則篩選子集；若為 all 則取全量)
        if category and category != 'all':
            merchants_filtered = [m for m in all_merchants_processed if m['category'] == category]
            cur_avg_list = [m['avg_ticket'] for m in merchants_filtered if m['avg_ticket'] > 0]
            cur_std_list = [m['std_ticket'] for m in merchants_filtered if m['std_ticket'] > 0]
            cur_median_avg = float(pd.Series(cur_avg_list).median()) if cur_avg_list else global_median_avg
            cur_median_std = float(pd.Series(cur_std_list).median()) if cur_std_list else global_median_std
            if pd.isna(cur_median_avg): cur_median_avg = global_median_avg
            if pd.isna(cur_median_std): cur_median_std = global_median_std
            merchants_list = merchants_filtered[:limit]
            df_filtered = cast(pd.DataFrame, df_merchants[df_merchants['category'] == category]) if 'category' in df_merchants.columns else df_merchants
        else:
            cur_median_avg = global_median_avg
            cur_median_std = global_median_std
            merchants_list = all_merchants_processed[:limit]
            df_filtered = df_merchants

        # 標註波動度象限分群（依當前類別之中位數基準分割）
        for m in merchants_list:
            mu = m['avg_ticket']
            sigma = m['std_ticket']
            if mu >= cur_median_avg and sigma < cur_median_std:
                vol_seg = "固定大額型 (Fixed High-Value)"
            elif mu >= cur_median_avg and sigma >= cur_median_std:
                vol_seg = "大額偶發型 (Spike Big-Ticket)"
            elif mu < cur_median_avg and sigma < cur_median_std:
                vol_seg = "微額日常型 (Micro-Routine)"
            else:
                vol_seg = "長尾混合型 (Elastic Long-Tail)"
            m['volatility_segment'] = vol_seg

        # 客群分佈統計 (基於篩選後的商家資料)
        segment_counts = df_filtered['segment'].value_counts().to_dict() if 'segment' in df_filtered.columns else {}


        # 5. 卡片資料與 DEMO 模式釘選排序 (Cube, Uniopen, Unicard 置頂)
        cards_list = []
        if not df_cards.empty:
            for _, row in df_cards.iterrows():
                card_name = str(row.get('card_type', ''))
                cards_list.append({
                    "bank_name": str(row.get('bank_name', '')),
                    "card_type": card_name,
                    "status": str(row.get('status', 'active')),
                    "segment": str(row.get('segment', '')),
                    "recency": int(pd.to_numeric(row.get(r_col, row.get('life_recency_days', 9999)), errors='coerce') or 9999),
                    "frequency": int(pd.to_numeric(row.get(f_col, row.get('life_frequency', 0)), errors='coerce') or 0),
                    "monetary": float(pd.to_numeric(row.get(m_col, row.get('life_monetary', 0)), errors='coerce') or 0.0),
                    "avg_ticket": float(pd.to_numeric(row.get('avg_ticket', 0), errors='coerce') or 0.0)
                })

            def _card_sort_priority(item: Dict[str, Any]):
                cn = str(item.get('card_type', '')).lower()
                if 'cube' in cn:
                    prio = 1
                elif 'uniopen' in cn:
                    prio = 2
                elif 'unicard' in cn:
                    prio = 3
                else:
                    prio = 99
                return (prio, -float(item.get('monetary', 0.0)))

            cards_list.sort(key=_card_sort_priority)
            for item in cards_list:
                cn = str(item.get('card_type', '')).lower()
                item['is_demo_pinned'] = any(kw in cn for kw in ['cube', 'uniopen', 'unicard'])

        return JSONResponse(content={
            "success": True,
            "data": {
                "merchants": merchants_list,
                "segment_counts": segment_counts,
                "categories": all_categories,
                "top_by_category": top_by_category,
                "cards": cards_list,
                "median_avg_ticket": round(cur_median_avg, 2),
                "median_std_ticket": round(cur_median_std, 2),
                "current_median_avg_ticket": round(cur_median_avg, 2),
                "current_median_std_ticket": round(cur_median_std, 2),
                "global_median_avg_ticket": round(global_median_avg, 2),
                "global_median_std_ticket": round(global_median_std, 2)
            }
        })

    except Exception as e:
        logger.error(f"❌ 查詢 RFM 圖表數據失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})



def _safe_json_response(payload: Any) -> Response:
    """
    安全 JSON 回應：使用 allow_nan=True 序列化後，以 regex 將所有 NaN/Infinity/-Infinity
    替換為 JSON null，再以 application/json 回傳。
    完全迴避 JSONResponse 內部 allow_nan=False 導致的序列化錯誤。
    """
    raw = json.dumps(payload, allow_nan=True, ensure_ascii=False,
                     separators=(',', ':'), default=str)
    # NaN / Infinity / -Infinity → null
    raw = re.sub(r'\bNaN\b', 'null', raw)
    raw = re.sub(r'\b-?Infinity\b', 'null', raw)
    return Response(content=raw, media_type='application/json')


@data_router.get("/rewards-summary")
async def get_rewards_summary_data():
    """查詢 C# 回饋金月度彙總與回饋池上限使用率 (Data Mart)"""
    try:
        db_path = const.ANALYSIS_DB_PATH
        monthly_summary: List[Dict] = []
        pool_utilization: List[Dict] = []

        # 每次都嘗試同步 Data Mart (確保資料是最新計算結果)
        from analytics.api import sync_rewards_data_mart
        sync_ok = sync_rewards_data_mart()
        logger.info(f"🔄 [rewards-summary] Data Mart 同步結果: {sync_ok}")

        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                try:
                    df_m = pd.read_sql_query(
                        "SELECT * FROM rewards_monthly_summary ORDER BY month DESC", conn
                    )
                    for col in df_m.select_dtypes(include='number').columns:
                        df_m[col] = df_m[col].replace(
                            [float('inf'), float('-inf')], 0.0
                        ).fillna(0.0)
                    for col in df_m.select_dtypes(include='object').columns:
                        df_m[col] = df_m[col].fillna('')
                    logger.info(f"✅ rewards_monthly_summary: {len(df_m)} 筆")
                    monthly_summary = df_m.to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"⚠️ 讀取 rewards_monthly_summary 失敗: {e}")

                try:
                    df_p = pd.read_sql_query(
                        "SELECT * FROM rewards_pool_utilization ORDER BY month DESC", conn
                    )
                    for col in df_p.select_dtypes(include='number').columns:
                        df_p[col] = df_p[col].replace(
                            [float('inf'), float('-inf')], 0.0
                        ).fillna(0.0)
                    if 'is_capped' in df_p.columns:
                        df_p['is_capped'] = df_p['is_capped'].apply(
                            lambda x: bool(str(x).strip().upper() in ('TRUE', '1', 'YES'))
                            if pd.notna(x) else False
                        )
                    for col in df_p.select_dtypes(include='object').columns:
                        df_p[col] = df_p[col].fillna('')
                    logger.info(f"✅ rewards_pool_utilization: {len(df_p)} 筆")
                    pool_utilization = df_p.to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"⚠️ 讀取 rewards_pool_utilization 失敗: {e}")
        else:
            logger.warning(f"⚠️ 找不到 TransactionsAnalysis.db: {db_path}")

        return _safe_json_response({
            "success": True,
            "data": {
                "monthly_summary": monthly_summary,
                "pool_utilization": pool_utilization
            }
        })

    except Exception as e:
        logger.error(f"❌ 查詢回饋彙總數據失敗: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

