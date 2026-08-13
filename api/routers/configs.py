# api/routers/configs.py
"""
維度對照表與 Config 同步 API 路由器模組
"""
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from profiles.profiles_api import (
    run_config_card_sync,
    run_config_reward_sync,
    run_config_merchant_sync,
    run_config_paygate_sync,
    run_all_config_sync,
    run_config_billing_history_sync,
    run_config_fx_table_sync
)
from profiles.loaders.config_loader import ConfigFilter
from api.utils import run_task_and_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Configs"])

@router.get("/api/run/config_all")
async def api_run_all_config_sync():
    """全量設定檔同步"""
    return StreamingResponse(run_task_and_stream(run_all_config_sync, "所有資料同步"), media_type="text/event-stream")

@router.get("/api/run/config_card")
async def api_run_config_card():
    """信用卡產品資料同步"""
    return StreamingResponse(run_task_and_stream(run_config_card_sync, "信用卡資料同步"), media_type="text/event-stream")

@router.get("/api/run/config_reward")
async def api_run_config_reward():
    """回饋規則設定同步"""
    return StreamingResponse(run_task_and_stream(run_config_reward_sync, "回饋規則同步"), media_type="text/event-stream")

@router.get("/api/run/config_mer")
async def api_run_config_mer():
    """特約商店維度同步"""
    return StreamingResponse(run_task_and_stream(run_config_merchant_sync, "特約商店同步"), media_type="text/event-stream")

@router.get("/api/run/config_paygate")
async def api_run_config_paygate():
    """第三方支付平台同步"""
    return StreamingResponse(run_task_and_stream(run_config_paygate_sync, "支付平台同步"), media_type="text/event-stream")

@router.get("/api/run/config_billing_history")
async def api_run_config_billing_history():
    """對帳單歷史同步"""
    return StreamingResponse(run_task_and_stream(run_config_billing_history_sync, "對帳單歷史同步"), media_type="text/event-stream")

@router.get("/api/run/config_fx_table")
async def api_run_config_fx_table():
    """每日匯率對照表同步"""
    return StreamingResponse(run_task_and_stream(run_config_fx_table_sync, "匯率每日表同步"), media_type="text/event-stream")

@router.get("/api/analyzable-data")
async def api_get_analyzable_data():
    """取得前端下拉選單與分析對照選單維度資料"""
    try:
        data = ConfigFilter.get_analyzable_data()
        return data
    except Exception as e:
        logger.error(f"❌ 讀取可分析資料失敗: {e}")
        return {"error": str(e), "banks": [], "cards": [], "payment_processes": []}
