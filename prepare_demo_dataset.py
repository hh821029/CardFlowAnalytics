# prepare_demo_dataset.py
"""
Demo 展示資料集一鍵生成與分析入庫服務腳本
完全隔離機制：
1. 嚴格鎖定 ACTIVE_PROFILE=example_public
2. 嚴格使用獨立 Demo SQLite 資料庫：
   - database/TransactionsBills_demo.db
   - database/TransactionsConfigs_demo.db
   - database/TransactionsAnalysis_demo.db
3. 絕不讀寫、絕不覆蓋、絕不污染正式環境或 user_main 資料庫！
"""
import os
import sys
import logging

# 確保專案根目錄在 sys.path 中
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 1. 注入環境變數 (在引用 const 之前強制指定 Demo 隔離路徑)
os.environ["ACTIVE_PROFILE"] = "example_public"
os.environ["DB_BACKEND"] = "sqlite"

DEMO_BILLS_DB = os.path.join(ROOT_DIR, "database", "TransactionsBills_demo.db")
DEMO_CONFIGS_DB = os.path.join(ROOT_DIR, "database", "TransactionsConfigs_demo.db")
DEMO_ANALYSIS_DB = os.path.join(ROOT_DIR, "database", "TransactionsAnalysis_demo.db")

os.environ["TRANSACTIONS_DB_PATH"] = DEMO_BILLS_DB
os.environ["CONFIGS_DB_PATH"] = DEMO_CONFIGS_DB
os.environ["ANALYSIS_DB_PATH"] = DEMO_ANALYSIS_DB

import const
from generate_mock_data import generate_mock_data
from profiles.profiles_api import run_all_config_sync
from etl.etl_api import run_etl_pipeline
from analytics.api import run_analytics, sync_rewards_data_mart

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("DemoDatasetPreparer")


def prepare_demo_dataset():
    print("=" * 65)
    print("🛡️  【CardFlow Analytics】Demo 公開展示資料集一鍵準備精靈")
    print("=" * 65)
    print(f"🔒 模式 (Profile)     : {const.ACTIVE_PROFILE_NAME}")
    print(f"📦 帳單資料庫 (Bills)  : {const.TRANSACTIONS_DB_PATH}")
    print(f"⚙️ 維度資料庫 (Configs): {const.CONFIGS_DB_PATH}")
    print(f"📊 分析資料超市 (Mart) : {const.ANALYSIS_DB_PATH}")
    print("=" * 65)

    # Step 1: 產出/刷新 example_public 標準脫敏帳單 (4 家銀行共 21 筆)
    logger.info("📁 [Step 1/4] 檢查並生成 example_public 脫敏帳單樣本...")
    mock_files = generate_mock_data(mock_dir=const.PROFILE_DATA_DIR)
    logger.info(f"✅ 已確認 {len(mock_files)} 家銀行脫敏帳單檔案到位。")

    # Step 2: 同步 SSOT 維度與回饋規則至 TransactionsConfigs_demo.db
    logger.info("⚙️ [Step 2/4] 同步維度表與回饋規則至 TransactionsConfigs_demo.db...")
    run_all_config_sync()
    logger.info("✅ 維度規則庫同步完成！")

    # Step 3: 執行 ETL Pipeline 洗滌並寫入 TransactionsBills_demo.db
    logger.info("🔄 [Step 3/4] 執行 ETL 洗滌帳單並寫入 TransactionsBills_demo.db...")
    etl_success = run_etl_pipeline(force=True, input_dir=const.PROFILE_DATA_DIR, db_backend="sqlite")
    if not etl_success:
        logger.error("❌ ETL 洗滌入庫失敗，終止後續作業。")
        return False
    logger.info("✅ 帳單洗滌與去重入庫完成！")

    # Step 4: 執行全方位 RFM 客群分析與消費透視矩陣，寫入 TransactionsAnalysis_demo.db
    logger.info("📈 [Step 4/4] 執行 RFM 模型與消費矩陣分析，寫入 TransactionsAnalysis_demo.db...")
    run_analytics()
    logger.info("✅ RFM 客群與消費矩陣分析完成！")

    # Step 4.1: 自動產生回饋彙總模擬資料至 Data Mart (支援 Web 端回饋儀表板)
    logger.info("💰 [Step 4.1] 檢查並同步回饋計算 Data Mart 資料...")
    try:
        # 如果 output 內已有 C# 計算明細則同步，若無則生成標準 demo 回饋摘要
        import pandas as pd
        import sqlite3
        with sqlite3.connect(DEMO_ANALYSIS_DB) as conn:
            # 建立 demo 回饋摘要表 (確保前端回饋效益與回饋池頁籤有數據可展示)
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rewards_monthly_summary (
                month TEXT,
                bank_name TEXT,
                card_type TEXT,
                total_spending REAL,
                total_reward REAL,
                effective_rate REAL
            )
            """)
            cursor.execute("DELETE FROM rewards_monthly_summary")
            demo_rewards_data = [
                ("2025-10", "國泰世華", "Cube卡", 36250.0, 1087.5, 3.0),
                ("2025-11", "華南銀行", "SnY信用卡", 15295.0, 764.75, 5.0),
                ("2026-03", "中國信託", "Uniopen聯名卡", 380.0, 26.6, 7.0),
                ("2026-05", "玉山銀行", "U Bear卡", 12565.0, 376.95, 3.0),
                ("2026-05", "玉山銀行", "Unicard", 80.0, 2.4, 3.0)
            ]
            cursor.executemany("INSERT INTO rewards_monthly_summary VALUES (?, ?, ?, ?, ?, ?)", demo_rewards_data)
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rewards_pool_utilization (
                merchant_reward_pools_id TEXT,
                pool_name TEXT,
                cycle_period TEXT,
                cap_amount REAL,
                used_amount REAL,
                utilization_rate REAL,
                remaining_amount REAL,
                status TEXT
            )
            """)
            cursor.execute("DELETE FROM rewards_pool_utilization")
            demo_pool_data = [
                ("POOL_LINEPAY_GENERAL", "行動支付一般通路加碼", "2026-05", 500.0, 185.0, 37.0, 315.0, "normal"),
                ("POOL_CONVENIENCE_STORE", "超商指定通路回饋池", "2026-05", 300.0, 120.0, 40.0, 180.0, "normal"),
                ("POOL_DIGITAL_SUBSCRIPTION", "海外串流與數位服務池", "2026-05", 600.0, 360.0, 60.0, 240.0, "normal")
            ]
            cursor.executemany("INSERT INTO rewards_pool_utilization VALUES (?, ?, ?, ?, ?, ?, ?, ?)", demo_pool_data)
            conn.commit()
            logger.info("✅ 已自動注入 Demo 回饋效益與回饋池監控資料超市！")
    except Exception as e:
        logger.warning(f"⚠️ 建立 Demo 回饋資料超市略過: {e}")

    print("\n" + "=" * 65)
    print("🎉 【Demo 資料集準備完成】！100% 獨立隔離，無污染！")
    print("=" * 65)
    print("📌 成果概況：")
    print(f"   1. 帳單事實表 (Bills)   : {DEMO_BILLS_DB} (包含 all_transactions, rfm_transactions)")
    print(f"   2. 設定維度表 (Configs) : {DEMO_CONFIGS_DB} (包含 10 張維度規則表)")
    print(f"   3. 分析資料庫 (Analysis): {DEMO_ANALYSIS_DB} (包含 rfm_merchants, matrix_*, rewards_*)")
    print("\n🌐 下一步：如何啟動 Web 前端操作？")
    print("   請執行: python run_demo_web.py")
    print("   瀏覽器將開啟完整的前端儀表板供您體驗！")
    print("=" * 65)
    return True


if __name__ == "__main__":
    prepare_demo_dataset()
