# api/routers/etl.py
"""
ETL 流程 API 路由器模組
支援全量雙階 Pipeline (Stage 1 + Stage 2) 與獨立重跑 Stage 2 Refinement
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from etl.etl_api import run_etl_pipeline, run_stage2_pipeline
from api.utils import run_task_and_stream

router = APIRouter(tags=["ETL"])

@router.get("/api/run/etl")
@router.get("/api/etl/run")
async def api_run_etl(force: bool = False):
    """啟動全量 ETL 帳單解析與入庫 Pipeline"""
    return StreamingResponse(
        run_task_and_stream(lambda: run_etl_pipeline(force=force), "ETL 流程"),
        media_type="text/event-stream"
    )


@router.get("/api/run/stage2")
@router.get("/api/etl/refine")
async def api_run_stage2(force: bool = True):
    """直接自 raw_transactions 重跑 Stage 2 商業規則清洗 (免重掃實體帳單)"""
    return StreamingResponse(
        run_task_and_stream(lambda: run_stage2_pipeline(force=force), "Stage 2 商業清洗"),
        media_type="text/event-stream"
    )
