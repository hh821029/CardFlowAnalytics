# api/routers/analytics.py
"""
RFM 分析、回饋金計算 (直連 C# 瀑布式引擎) 與交易 SQL 篩選導出 API 路由器模組
"""
import os
import logging
from typing import Optional, List
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import const
from rfm_analysis.rfm_analysis_api import run_analytics
from database.database_api import query_transactions_modular
from api.utils import run_task_and_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/run", tags=["Analytics"])

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
        except Exception as e:
            yield f"data: ❌ [C# 引擎連線失敗] 無法連線至 C# RewardEngine 服務 ({CSHARP_REWARDS_API_URL}): {e}\n\n"

@router.get("/analytics")
async def api_run_analytics(
    banks: Optional[str] = None,
    cards: Optional[str] = None,
    payments: Optional[str] = None,
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

    def run_task():
        run_analytics(
            banks=bank_list,
            cards=card_list,
            payments=pay_list,
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

    def run_task():
        logger.info("⚙️ 啟動 SQL 條件篩選與匯出任務...")
        logger.info(f"篩選參數 -> 銀行數: {len(bank_list) if bank_list else '未限制'}, 卡片數: {len(card_list) if card_list else '未限制'}, 支付管道數: {len(pay_list) if pay_list else '未限制'}, 時間視窗: {time_window or '未設定'}, 開始日: {start_date or '未設定'}, 結束日: {end_date or '未設定'}, 地點/國家代碼: {location or '未限制'}, 消費主類別: {cat_list or '未限制'}, 消費次類別: {sub_cat_list or '未限制'}")
        
        df = query_transactions_modular(
            banks=bank_list,
            cards=card_list,
            payments=pay_list,
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
        logger.info(f"✅ 篩選與匯出成功！結果已儲存至：output/filtered_transactions.csv，共計 {len(df)} 筆交易。請至 output/ 資料夾查看該檔案。")

    return StreamingResponse(run_task_and_stream(run_task, "SQL 篩選與匯出", require_db=True), media_type="text/event-stream")
