# api/routers/etl.py
"""
ETL 流程 API 路由器模組
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from etl.etl_api import run_etl_pipeline
from api.utils import run_task_and_stream
#from scratch.feature_checker_service import check_feature_extraction_status

router = APIRouter(tags=["ETL"])

@router.get("/api/run/etl")
@router.get("/api/etl/run")
async def api_run_etl(force: bool = False):
    """啟動 ETL 帳單解析與入庫 Pipeline"""
    return StreamingResponse(
        run_task_and_stream(lambda: run_etl_pipeline(force=force), "ETL 流程"),
        media_type="text/event-stream"
    )
#
#@router.get("/api/etl/feature-status")
#@router.get("/api/run/etl_feature_status")
#async def api_check_feature_status(export_csv: bool = True):
#    """檢查所有資料表與視圖之特徵提取狀態與覆蓋率"""
#    df_status = check_feature_extraction_status(export_csv=export_csv)
#    return {
#        "status": "success",
#        "total_tables": len(df_status),
#        "data": df_status.to_dict(orient="records")
#    }


