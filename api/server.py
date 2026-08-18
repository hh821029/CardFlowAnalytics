# api/server.py
"""
FastAPI 控制台主伺服器 (Server Entrypoint & Static File Mount)
重構架構說明：將 API 端點解耦至 api/routers/ 目錄管理，大幅簡化主檔職責。
"""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import etl, configs, analytics, auth, cards_json
from web.web_api import setup_web_error_handlers, router as web_api_router

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MyCreditCardProjectPro API",
    description="信用卡帳單 ETL、RFM 分析與回饋計算 API 控制台"
)

# 1. 設定 CORS (允許前端存取 API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 註冊 Web 錯誤處理器 (403/404/501/502/503/500 & errorlog 紀錄)
setup_web_error_handlers(app)

# 3. 掛載 APIRouter 路由器模組
app.include_router(auth.router)
app.include_router(cards_json.router)
app.include_router(etl.router)
app.include_router(configs.router)
app.include_router(analytics.router)
app.include_router(web_api_router)

# 3. 設定靜態檔案路徑 (用於 web/index.html 控制台)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")

if os.path.exists(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
else:
    @app.get("/")
    async def root():
        return {"message": "API Server is running. Frontend folder 'web/' not found."}

if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    # 啟動伺服器 (Port 8000)
    uvicorn.run(app, host="127.0.0.1", port=8000)
