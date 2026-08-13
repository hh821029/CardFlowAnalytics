# web/web_api.py
"""
Web 前端 API 與 HTTP 錯誤處理模組
處理前端 HTTP 錯誤狀態 (403/404/501/502/503/500) 顯示與頁面渲染，
並將後端發出的對應錯誤狀況輸出至 `errorlog/` 資料夾。
"""

import os
import datetime
import traceback
import logging
from typing import Optional

from fastapi import FastAPI, Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# APIRouter 供伺服器掛載測試端點
router = APIRouter(tags=["WebAPI"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERROR_LOG_DIR = os.path.join(BASE_DIR, "errorlog")

ERROR_MESSAGES = {
    403: ("403 存取被拒絕", "您沒有權限存取此資源或頁面。"),
    404: ("404 找不到資源", "您所請求的頁面或 API 端點不存在或已被移動。"),
    501: ("501 功能尚未實作", "伺服器尚不支援或未實作您所請求的功能。"),
    502: ("502 閘道與通訊錯誤", "上游伺服器或代理閘道回應無效，請稍後再試。"),
    503: ("503 服務暫時不可用", "伺服器目前忙碌中或正在維護，請稍後重試。"),
    500: ("500 伺服器內部錯誤", "系統處理您的請求時發生非預期例外錯誤。")
}


def log_backend_error(request: Request, status_code: int, detail: str, exc: Optional[Exception] = None):
    """
    將後端發生的 HTTP 錯誤與例外資訊記錄至 errorlog/ 資料夾
    """
    try:
        os.makedirs(ERROR_LOG_DIR, exist_ok=True)
        today_str = datetime.date.today().strftime("%Y%m%d")
        log_file_path = os.path.join(ERROR_LOG_DIR, f"error_{today_str}.log")

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client_host = request.client.host if request.client else "unknown"
        method = request.method
        url = str(request.url)

        log_lines = [
            f"[{timestamp}] [HTTP {status_code}] Client: {client_host} | Method: {method} | URL: {url}",
            f"  Detail: {detail}"
        ]

        if exc:
            tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log_lines.append(f"  Traceback:\n{tb_str}")

        log_content = "\n".join(log_lines) + "\n" + ("-" * 80) + "\n"

        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(log_content)

        logger.error(f"❌ [HTTP {status_code}] {url} -> 錯誤已記錄至 errorlog/{os.path.basename(log_file_path)}")
    except Exception as e:
        logger.error(f"❌ 寫入 errorlog 失敗: {e}")


def generate_error_html(status_code: int, detail: str = "") -> str:
    """
    讀取 web/error.html 靜態樣板並渲染動態錯誤內容
    """
    title, summary = ERROR_MESSAGES.get(status_code, (f"{status_code} 系統錯誤", "發生非預期的 HTTP 錯誤。"))
    display_detail = detail if detail else summary

    template_path = os.path.join(os.path.dirname(__file__), "error.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
        return template.format(
            status_code=status_code,
            title=title,
            summary=summary,
            display_detail=display_detail
        )

    # 備援 (Fallback)
    return f"<!DOCTYPE html><html><body><h1>{status_code} {title}</h1><pre>{display_detail}</pre></body></html>"



def setup_web_error_handlers(app: FastAPI):
    """
    於 FastAPI 應用程式註冊 HTTP 錯誤 (403/404/501/502/503/500) 之 Handler
    """
    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
        status_code = exc.status_code
        detail = exc.detail if exc.detail else "HTTP Exception"
        
        # 記錄錯誤日誌至 errorlog/
        log_backend_error(request, status_code, detail)

        # 判斷請求型態 (API JSON vs 前端網頁 HTML)
        accept_header = request.headers.get("accept", "")
        is_api_request = request.url.path.startswith("/api/") or "application/json" in accept_header

        if is_api_request:
            return JSONResponse(
                status_code=status_code,
                content={
                    "status": status_code,
                    "error": ERROR_MESSAGES.get(status_code, (f"HTTP {status_code}", ""))[0],
                    "detail": detail
                }
            )
        
        html_content = generate_error_html(status_code, detail)
        return HTMLResponse(content=html_content, status_code=status_code)

    @app.exception_handler(Exception)
    async def custom_unhandled_exception_handler(request: Request, exc: Exception):
        status_code = 500
        detail = f"非預期伺服器錯誤: {str(exc)}"

        # 記錄詳細 Exception Traceback 至 errorlog/
        log_backend_error(request, status_code, detail, exc=exc)

        accept_header = request.headers.get("accept", "")
        is_api_request = request.url.path.startswith("/api/") or "application/json" in accept_header

        if is_api_request:
            return JSONResponse(
                status_code=status_code,
                content={
                    "status": status_code,
                    "error": "500 伺服器內部錯誤",
                    "detail": str(exc)
                }
            )

        html_content = generate_error_html(status_code, str(exc))
        return HTMLResponse(content=html_content, status_code=status_code)


@router.get("/api/error/{status_code}")
async def trigger_simulated_error(status_code: int):
    """
    測試用端點：手動觸發指定 HTTP 錯誤碼 (403, 404, 501, 502, 503) 以驗證 errorlog 與錯誤頁面
    """
    if status_code not in [403, 404, 501, 502, 503, 500]:
        raise HTTPException(status_code=400, detail="僅支援測試 403, 404, 501, 502, 503, 500 狀態碼")

    msg_title, msg_desc = ERROR_MESSAGES.get(status_code, ("模擬錯誤", "觸發模擬測試"))
    raise HTTPException(status_code=status_code, detail=f"[模擬測試] 觸發 {msg_title} - {msg_desc}")
