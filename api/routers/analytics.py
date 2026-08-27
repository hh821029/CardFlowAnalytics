# api/routers/analytics.py
"""
RFM 分析、回饋金計算 (直連 C# 瀑布式引擎)、交易 SQL 篩選導出與視覺化數據查詢 API 路由器模組
"""
import os
import sqlite3
import logging
from typing import Optional, List, Dict, Any, cast, Union
import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

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
    include_merchants: bool = False
):
    """查詢金流桑基圖 (Sankey Flow) nodes 與 links 結構"""
    try:
        df = _extract_dataset_from_query(
            banks=banks, cards=cards, payments=payments,
            include_direct_payment=include_direct_payment,
            time_window=time_window, start_date=start_date,
            end_date=end_date, location=location,
            categories=categories, sub_categories=sub_categories
        )
        flow_data = build_sankey_flow(df, include_merchants=include_merchants)
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
    """查詢 RFM 視覺化圖表資料 (氣泡圖、客群分佈統計、卡片價值)"""
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
                    "cards": []
                }
            })

        # 1. 提取所有有效分類清單 (在篩選前提取)
        all_categories = sorted([str(c) for c in df_merchants['category'].unique() if pd.notna(c) and str(c).strip() != '' and str(c).strip() != 'nan']) if 'category' in df_merchants.columns else []

        m_col = f"{prefix}monetary" if f"{prefix}monetary" in df_merchants.columns else "life_monetary"
        f_col = f"{prefix}frequency" if f"{prefix}frequency" in df_merchants.columns else "life_frequency"
        r_col = f"{prefix}recency_days" if f"{prefix}recency_days" in df_merchants.columns else "life_recency_days"

        # 2. 計算各生活消費領域 Top 3 商家排行 (依 M 累積金額降冪)
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

        # 3. 類別篩選 (若有傳入特定 category，供氣泡圖與九宮格)
        df_filtered = df_merchants.copy()
        if category and category != 'all' and 'category' in df_filtered.columns:
            df_filtered = cast(pd.DataFrame, df_filtered[df_filtered['category'] == category])

        # 依 Monetary 排序並限制筆數 (供氣泡圖)
        if m_col in df_filtered.columns:
            df_filtered = cast(pd.DataFrame, df_filtered.sort_values(by=m_col, ascending=False))

        merchants_list = []
        for _, row in df_filtered.head(limit).iterrows():
            m_val = float(pd.to_numeric(row.get(m_col, 0), errors='coerce') or 0.0)
            f_val = int(pd.to_numeric(row.get(f_col, 0), errors='coerce') or 0)
            r_val = int(pd.to_numeric(row.get(r_col, 9999), errors='coerce') or 9999)
            merchants_list.append({
                "name": str(row.get('normalized_merchant', '')),
                "recency": r_val,
                "frequency": f_val,
                "monetary": m_val,
                "segment": str(row.get('segment', '一般活躍 (Active)')),
                "category": str(row.get('category', '未分類')),
                "sub_category": str(row.get('sub_category', '') if pd.notna(row.get('sub_category')) and str(row.get('sub_category')) != 'nan' else '')
            })

        # 客群分佈統計 (基於篩選後的商家資料)
        segment_counts = df_filtered['segment'].value_counts().to_dict() if 'segment' in df_filtered.columns else {}

        # 卡片資料
        cards_list = []
        if not df_cards.empty:
            for _, row in df_cards.iterrows():
                cards_list.append({
                    "bank_name": str(row.get('bank_name', '')),
                    "card_type": str(row.get('card_type', '')),
                    "status": str(row.get('status', 'active')),
                    "segment": str(row.get('segment', '')),
                    "recency": int(pd.to_numeric(row.get(r_col, row.get('life_recency_days', 9999)), errors='coerce') or 9999),
                    "frequency": int(pd.to_numeric(row.get(f_col, row.get('life_frequency', 0)), errors='coerce') or 0),
                    "monetary": float(pd.to_numeric(row.get(m_col, row.get('life_monetary', 0)), errors='coerce') or 0.0),
                    "avg_ticket": float(pd.to_numeric(row.get('avg_ticket', 0), errors='coerce') or 0.0)
                })

        return JSONResponse(content={
            "success": True,
            "data": {
                "merchants": merchants_list,
                "segment_counts": segment_counts,
                "categories": all_categories,
                "top_by_category": top_by_category,
                "cards": cards_list
            }
        })
    except Exception as e:
        logger.error(f"❌ 查詢 RFM 圖表數據失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@data_router.get("/rewards-summary")
async def get_rewards_summary_data():
    """查詢 C# 回饋金月度彙總與回饋池上限使用率 (Data Mart)"""
    try:
        db_path = const.ANALYSIS_DB_PATH
        monthly_summary = []
        pool_utilization = []

        # 每次都嘗試同步 Data Mart (確保資料是最新計算結果)
        from analytics.api import sync_rewards_data_mart
        sync_ok = sync_rewards_data_mart()
        logger.info(f"🔄 [rewards-summary] Data Mart 同步結果: {sync_ok}")

        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                try:
                    df_m = pd.read_sql_query("SELECT * FROM rewards_monthly_summary ORDER BY month DESC", conn)
                    df_m = df_m.replace([float('inf'), float('-inf')], 0.0)
                    df_m = df_m.where(pd.notna(df_m), other=0.0)
                    logger.info(f"✅ rewards_monthly_summary: {len(df_m)} 筆")
                    monthly_summary = df_m.to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"⚠️ 讀取 rewards_monthly_summary 失敗: {e}")

                try:
                    df_p = pd.read_sql_query("SELECT * FROM rewards_pool_utilization ORDER BY month DESC", conn)
                    df_p = df_p.replace([float('inf'), float('-inf')], 0.0)
                    # is_capped 統一轉 bool；NaN 型態的字串欄位轉為 None
                    if 'is_capped' in df_p.columns:
                        df_p['is_capped'] = df_p['is_capped'].apply(lambda x: bool(str(x).upper() == 'TRUE') if pd.notna(x) else False)
                    if 'cap_amount' in df_p.columns:
                        df_p['cap_amount'] = pd.to_numeric(df_p['cap_amount'], errors='coerce').fillna(0.0)
                    logger.info(f"✅ rewards_pool_utilization: {len(df_p)} 筆")
                    pool_utilization = df_p.where(pd.notna(df_p), other=None).to_dict(orient='records')
                except Exception as e:
                    logger.warning(f"⚠️ 讀取 rewards_pool_utilization 失敗: {e}")
        else:
            logger.warning(f"⚠️ 找不到 TransactionsAnalysis.db: {db_path}")

        import json as _json
        return JSONResponse(content=_json.loads(_json.dumps({
            "success": True,
            "data": {
                "monthly_summary": monthly_summary,
                "pool_utilization": pool_utilization
            }
        }, default=lambda x: None if (isinstance(x, float) and (x != x or x == float('inf') or x == float('-inf'))) else x)))
    except Exception as e:
        logger.error(f"❌ 查詢回饋彙總數據失敗: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

