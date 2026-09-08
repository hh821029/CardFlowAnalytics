# export_demo_static_json.py
"""
Demo 靜態 JSON 預烘焙匯出工具 (支援 GitHub Pages 純靜態部署)
功能：
讀取 TransactionsAnalysis_demo.db 與 TransactionsBills_demo.db，
預先將前端 5 大核心儀表板所需的數據導出為靜態 JSON 檔案至 web/mock_data/。
讓前端在沒有任何 Python / Docker 後端的環境下（例如 GitHub Pages），也能 100% 流暢操作！
"""
import os
import sys
import json
import re

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 防呆：確保 Windows 終端輸出以 UTF-8 編碼執行，避免 UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 鎖定 Demo 隔離路徑
os.environ["ACTIVE_PROFILE"] = "example_public"
os.environ["DB_BACKEND"] = "sqlite"

DEMO_BILLS_DB = os.path.join(ROOT_DIR, "database", "TransactionsBills_demo.db")
DEMO_CONFIGS_DB = os.path.join(ROOT_DIR, "database", "TransactionsConfigs_demo.db")
DEMO_ANALYSIS_DB = os.path.join(ROOT_DIR, "database", "TransactionsAnalysis_demo.db")

os.environ["TRANSACTIONS_DB_PATH"] = DEMO_BILLS_DB
os.environ["CONFIGS_DB_PATH"] = DEMO_CONFIGS_DB
os.environ["ANALYSIS_DB_PATH"] = DEMO_ANALYSIS_DB

import const
from analytics.rfm import get_rfm_dashboard_data, get_dimension_volatility_bubble_data
from analytics.api import get_rewards_summary_mart_data
from analytics.analytics_base import prepare_analytics_dataset
from analytics.common import build_monthly_trend_payload
from analytics.sankeyflow import build_sankey_flow
from profiles.loaders.config_loader import ConfigFilter

MOCK_DATA_DIR = os.path.join(ROOT_DIR, "web", "mock_data")
os.makedirs(MOCK_DATA_DIR, exist_ok=True)


def _safe_write_json(filename: str, payload: dict):
    filepath = os.path.join(MOCK_DATA_DIR, filename)
    raw = json.dumps(payload, allow_nan=True, ensure_ascii=False, indent=2, default=str)
    # NaN / Infinity 替換為 null
    raw = re.sub(r'\bNaN\b', 'null', raw)
    raw = re.sub(r'\b-?Infinity\b', 'null', raw)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"✅ 已匯出靜態展示資料: {filepath}")


def export_all():
    print("=" * 60)
    print("📦 正在預烘焙 Demo 靜態 JSON 數據 (支援 GitHub Pages)...")
    print("=" * 60)

    # 確保 const 路徑鎖定在 Demo 隔離資料庫 (防範 pytest 或其他流程已先載入 const)
    os.environ["ACTIVE_PROFILE"] = "example_public"
    os.environ["DB_BACKEND"] = "sqlite"
    os.environ["TRANSACTIONS_DB_PATH"] = DEMO_BILLS_DB
    os.environ["CONFIGS_DB_PATH"] = DEMO_CONFIGS_DB
    os.environ["ANALYSIS_DB_PATH"] = DEMO_ANALYSIS_DB

    const.ACTIVE_PROFILE_NAME = "example_public"
    const.ACTIVE_PROFILE_DIR = os.path.join(const.PROFILES_DIR, "example_public")
    const.PROFILE_CONFIG_DIR = os.path.join(const.ACTIVE_PROFILE_DIR, "configs")
    const.PROFILE_DATA_DIR = os.path.join(const.ACTIVE_PROFILE_DIR, "data")
    const.PROFILE_JSON_PATH = os.path.join(const.ACTIVE_PROFILE_DIR, "profile.json")
    const.TRANSACTIONS_DB_PATH = DEMO_BILLS_DB
    const.CONFIGS_DB_PATH = DEMO_CONFIGS_DB
    const.ANALYSIS_DB_PATH = DEMO_ANALYSIS_DB
    const.DB_PATH = DEMO_BILLS_DB
    const.DEFAULT_DB_BACKEND = "sqlite"

    # 防呆檢查：若 Demo 資料庫未就緒，自動觸發準備精靈
    needs_prep = not os.path.exists(DEMO_BILLS_DB) or os.path.getsize(DEMO_BILLS_DB) == 0
    if not needs_prep:
        try:
            import sqlite3
            with sqlite3.connect(DEMO_BILLS_DB) as conn:
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM rfm_transactions")
                if cur.fetchone()[0] == 0:
                    needs_prep = True
        except Exception:
            needs_prep = True

    if needs_prep:
        from prepare_demo_dataset import prepare_demo_dataset
        prepare_demo_dataset()

    # 1. RFM 圖表數據 (含全部類別與五大分群)
    print("1. 匯出 RFM 價值氣泡圖數據 (rfm_chart.json)...")
    rfm_data = get_rfm_dashboard_data(
        window="life",
        category="all",
        limit=150,
        df_tx_provider=lambda: prepare_analytics_dataset(time_window="life", db_path=DEMO_BILLS_DB)
    )
    _safe_write_json("rfm_chart.json", {"success": True, "data": rfm_data})

    # 2. 金流維度消費波動數據 (六大流向)
    print("2. 匯出金流維度消費波動數據 (dimension_volatility.json)...")
    dim_data = get_dimension_volatility_bubble_data(
        window="life",
        group_mode="payment_category",
        limit=150,
        df_tx_provider=lambda: prepare_analytics_dataset(time_window="life", db_path=DEMO_BILLS_DB)
    )
    _safe_write_json("dimension_volatility.json", {"success": True, "data": dim_data})

    # 3. 月度趨勢數據
    print("3. 匯出月度趨勢圖表數據 (monthly_trend.json)...")
    df_tx = prepare_analytics_dataset(time_window="life", db_path=DEMO_BILLS_DB)
    trend_payload = build_monthly_trend_payload(df_tx)
    _safe_write_json("monthly_trend.json", {"success": True, "data": trend_payload})

    # 4. 金流桑基圖數據
    print("4. 匯出金流桑基圖流向數據 (sankey_flow.json)...")
    sankey_data = build_sankey_flow(df_tx, include_merchants=True, demo_mode=True)
    _safe_write_json("sankey_flow.json", {"success": True, "data": sankey_data})

    # 5. 回饋 Data Mart 數據 (月度效益與回饋池)
    print("5. 匯出回饋效益與回饋池監控數據 (rewards_summary.json)...")
    rewards_data = get_rewards_summary_mart_data(db_path=DEMO_ANALYSIS_DB)
    _safe_write_json("rewards_summary.json", {"success": True, "data": rewards_data})

    # 6. 可分析維度數據 (篩選清單)
    print("6. 匯出可分析維度資料 (analyzable_data.json)...")
    analyzable_data = ConfigFilter.get_analyzable_data(db_path=DEMO_CONFIGS_DB)
    _safe_write_json("analyzable_data.json", analyzable_data)

    print("\n🎉 全量 Demo 靜態 JSON 預烘焙完成！目錄：web/mock_data/")


if __name__ == "__main__":
    export_all()
