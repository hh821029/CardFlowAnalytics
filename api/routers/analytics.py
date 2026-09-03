# api/routers/analytics.py
"""
RFM 分析、回饋金計算 (直連 C# 瀑布式引擎)、交易 SQL 篩選導出與視覺化數據查詢 API 路由器模組
"""
import os
import re
import json
import logging
from typing import Optional, List, Dict, Any, Union
import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response

import const
from analytics.api import run_analytics, get_rewards_summary_mart_data
from analytics.analytics_base import prepare_analytics_dataset
from analytics.common.transaction_query import query_transactions_modular
from analytics.common import build_monthly_trend_payload
from analytics.sankeyflow import build_sankey_flow
from analytics.rfm import get_rfm_dashboard_data
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


def _parse_filter_lists(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
    location: Optional[str] = None,
    categories: Optional[str] = None,
    sub_categories: Optional[str] = None,
    include_direct_payment: Optional[str] = "true"
) -> Dict[str, Any]:
    """解析並標準化 API Query 參數為串列與布林值"""
    return {
        'banks': [b.strip() for b in banks.split(',')] if banks else None,
        'cards': [c.strip() for c in cards.split(',')] if cards else None,
        'payments': [p.strip() for p in payments.split(',')] if payments else None,
        'location': [l.strip() for l in location.split(',')] if location else None,
        'categories': [c.strip() for c in categories.split(',')] if categories else None,
        'sub_categories': [sc.strip() for sc in sub_categories.split(',')] if sub_categories else None,
        'include_direct_payment': include_direct_payment.strip().lower() in ('true', '1', 'yes') if include_direct_payment is not None else True,
    }


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
    filters = _parse_filter_lists(
        banks=banks, cards=cards, payments=payments,
        location=location, categories=categories, sub_categories=sub_categories,
        include_direct_payment=include_direct_payment
    )

    def run_task():
        run_analytics(
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            **filters
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
    filters = _parse_filter_lists(banks=banks, cards=cards, payments=payments, location=location)

    return StreamingResponse(
        stream_csharp_rewards_calculation(
            banks=filters['banks'],
            cards=filters['cards'],
            payments=filters['payments'],
            location=filters['location'],
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
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
    filters = _parse_filter_lists(
        banks=banks, cards=cards, payments=payments,
        location=location, categories=categories, sub_categories=sub_categories,
        include_direct_payment=include_direct_payment
    )
    cat_list = filters['categories']
    sub_cat_list = filters['sub_categories']

    def run_task():
        logger.info("⚙️ 啟動 SQL 條件篩選與匯出任務...")
        df = query_transactions_modular(
            banks=filters['banks'],
            cards=filters['cards'],
            payments=filters['payments'],
            include_direct_payment=filters['include_direct_payment'],
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=filters['location']
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
    filters = _parse_filter_lists(
        banks=banks, cards=cards, payments=payments,
        location=location, categories=categories, sub_categories=sub_categories,
        include_direct_payment=include_direct_payment
    )
    return prepare_analytics_dataset(
        time_window=time_window,
        start_date=start_date,
        end_date=end_date,
        **filters
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
        data = build_monthly_trend_payload(df)
        return JSONResponse(content={"success": True, "data": data})
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
        data = get_rfm_dashboard_data(
            window=window,
            category=category,
            limit=limit,
            df_tx_provider=lambda: _extract_dataset_from_query(time_window=window)
        )
        return JSONResponse(content={"success": True, "data": data})
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
        data = get_rewards_summary_mart_data()
        return _safe_json_response({"success": True, "data": data})
    except Exception as e:
        logger.error(f"❌ 查詢回饋彙總數據失敗: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

