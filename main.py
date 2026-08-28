# main.py
import logging
import os
import sys
import time

# 引入核心 ETL 與 Analytics 分析 API
import const
from etl.etl_api import run_etl_pipeline
from analytics.api import run_analytics, sync_rewards_data_mart
from analytics.common.transaction_query import query_transactions_modular
from profiles.profiles_api import (
    run_all_config_sync,
    run_config_card_sync,
    run_config_reward_sync,
    run_config_merchant_sync,
    run_config_paygate_sync,
    run_config_billing_history_sync,
    run_config_fx_table_sync,
    run_config_ec_platform_sync
)

# ==========================================
# 設定日誌 (Logging)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==========================================
# 全域狀態控制 (防呆鎖定)
# ==========================================
_is_running = False

def safe_execute(task_name, func, require_db=False):
    """
    安全執行包裝器：處理執行鎖定與資料庫檢查
    """
    global _is_running
    
    # 1. 執行中鎖定檢查
    if _is_running:
        print(f"\n⚠️  [防呆攔截] 任務 '{task_name}' 無法啟動。目前已有其他任務正在執行中，請稍候。")
        return

    # 2. 資料庫存在檢查
    if require_db:
        if not os.path.exists(const.DB_PATH):
            print(f"\n❌ [權限錯誤] 執行 '{task_name}' 失敗！")
            print(f"   原因：找不到基礎資料庫檔案 ({const.DB_PATH})。")
            print(f"   建議：請先執行「選項 1」產生資料庫後，再進行分析。")
            return

    try:
        _is_running = True
        print(f"\n{'='*50}")
        print(f"🚀 啟動任務: {task_name}")
        print(f"{'='*50}")
        
        start_time = time.time()
        func()  # 呼叫 Service 層邏輯
        end_time = time.time()
        
        print(f"\n{'='*50}")
        print(f"✅ {task_name} 執行成功！ (耗時: {end_time - start_time:.2f} 秒)")
        print(f"{'='*50}")
        
    except Exception as e:
        logger.error(f"🚨 {task_name} 執行過程中發生未預期錯誤: {e}", exc_info=True)
    finally:
        _is_running = False

def show_menu():
    """顯示控制台選單 (與 Web 端功能完全對齊)"""
    print("\n" + "■"*50)
    print("  MyCreditCardProjectPro 控制台 (CLI)")
    print("■"*50)
    print("  【📦 帳單 ETL 入庫】")
    print("    1.   掃描原始檔案並產生/更新資料庫 (去重檢查)")
    print("    1F.  強制全量重新解析所有帳單檔案")
    print("  【⚙️ 設定檔與維度表同步 (SSOT)】")
    print("    2.   執行全量設定同步 (All Configs)")
    print("    2A.  🏪 特約商家資料同步")
    print("    2B.  👛 第三方支付錢包同步")
    print("    2C.  💳 信用卡基本資料同步")
    print("    2D.  📅 帳單結帳日歷史同步")
    print("    2E.  📜 回饋規則與方案同步")
    print("    2F.  💱 匯率每日表同步")
    print("    2G.  🛒 電商平台維度同步")
    print("  【💰 回饋計算與 RFM 模型】")
    print("    3.   [Rewards] C# 瀑布式回饋計算 (含 Data Mart 同步)")
    print("    4.   [RFM] 執行全方位 RFM 分析與消費透視 (需資料庫)")
    print("    5.   [Export] 依條件篩選匯出交易 CSV")
    print("  【🌐 系統與 Web 控制台】")
    print("    6.   [Web Server] 啟動 Web 控制台伺服器 (Port 8000)")
    print("    Q.   退出程式")
    print("-" * 50)

def run_cli_csharp_rewards():
    """CLI 模式下連線 C# 引擎進行回饋計算與日誌印出，並自動同步 Data Mart"""
    import urllib.request
    url = os.getenv("CSHARP_REWARDS_API_URL", "http://127.0.0.1:5000/api/run/rewards")
    print(f"📡 連線 C# 回饋計算引擎 ({url})...")
    try:
        req = urllib.request.Request(url, headers={'Accept': 'text/event-stream'})
        with urllib.request.urlopen(req, timeout=300) as resp:
            for line_bytes in resp:
                line = line_bytes.decode('utf-8', errors='ignore').strip()
                if line.startswith("data: "):
                    print(line[6:])
        
        # 運算完成後，自動將明細匯總寫入 Data Mart (與 Web 端 API 行為一致)
        try:
            if sync_rewards_data_mart():
                print("\n💾 [Data Mart] 回饋計算摘要已成功寫入 TransactionsAnalysis.db ([rewards_monthly_summary], [rewards_pool_utilization])")
        except Exception as dm_err:
            logger.warning(f"⚠️ 自動同步回饋至 Data Mart 失敗: {dm_err}")
    except Exception as e:
        print(f"❌ 呼叫 C# 引擎失敗: {e} (請確認 C# RewardEngine.Api:5000 是否已啟動)")

def run_cli_query_export():
    """CLI 模式下執行交易條件篩選並導出 CSV"""
    print("\n" + "-"*45)
    print("  📥 交易資料條件篩選與匯出 CSV")
    print("-" * 45)
    print("  💡 提示：直接按 Enter 鍵可套用預設值 (全量匯出)。")
    time_window = input("  請輸入時間視窗 (例如 30d, 90d, 180d, 365d，留空為全歷史): ").strip() or None
    start_date = input("  請輸入起始日期 (YYYY-MM-DD，留空略過): ").strip() or None
    end_date = input("  請輸入結束日期 (YYYY-MM-DD，留空略過): ").strip() or None
    bank_input = input("  請輸入銀行名稱 (多個以逗號隔開，留空為全部): ").strip()
    card_input = input("  請輸入卡片名稱 (多個以逗號隔開，留空為全部): ").strip()
    payment_input = input("  請輸入支付方式 (多個以逗號隔開，留空為全部): ").strip()

    banks = [b.strip() for b in bank_input.split(',') if b.strip()] if bank_input else None
    cards = [c.strip() for c in card_input.split(',') if c.strip()] if card_input else None
    payments = [p.strip() for p in payment_input.split(',') if p.strip()] if payment_input else None

    print("\n⚙️ 正在根據條件查詢交易資料庫...")
    df = query_transactions_modular(
        banks=banks,
        cards=cards,
        payments=payments,
        time_window=time_window,
        start_date=start_date,
        end_date=end_date
    )

    if df.empty:
        print("⚠️ 篩選結果為空，未產生匯出檔。")
        return

    os.makedirs(const.OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(const.OUTPUT_DIR, 'filtered_transactions.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"✅ 篩選與匯出成功！共計 {len(df)} 筆交易，已儲存至：{csv_path}")

def run_cli_web_server():
    """啟動 FastAPI Web 控制台伺服器"""
    try:
        import uvicorn
        print("\n" + "="*50)
        print("🌐 正在啟動 Web 控制台伺服器 (FastAPI + Uvicorn)...")
        print("📌 請在瀏覽器開啟: http://127.0.0.1:8000")
        print("⏹️  若要停止伺服器，請按 Ctrl+C。")
        print("="*50 + "\n")
        uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)
    except ImportError:
        print("❌ 找不到 uvicorn 套件，請先安裝: pip install uvicorn")
    except Exception as e:
        print(f"❌ 啟動 Web 伺服器失敗: {e}")

# ==========================================
# 主進入點
# ==========================================
if __name__ == "__main__":
    while True:
        show_menu()
        choice = input("請輸入選項 (例如 1, 1F, 2, 2A, 3, 4, 5, 6, Q): ").strip().upper()
        
        if choice == '1':
            safe_execute("ETL 流程 (產生資料庫)", run_etl_pipeline)
        elif choice == '1F':
            safe_execute("ETL 流程 (強制全量重新解析)", lambda: run_etl_pipeline(force=True))
        elif choice == '2':
            safe_execute("全量設定檔同步 (All Configs)", run_all_config_sync)
        elif choice == '2A':
            safe_execute("特約商店資料同步", run_config_merchant_sync)
        elif choice == '2B':
            safe_execute("支付錢包資料同步", run_config_paygate_sync)
        elif choice == '2C':
            safe_execute("信用卡資料同步", run_config_card_sync)
        elif choice == '2D':
            safe_execute("對帳單歷史同步", run_config_billing_history_sync)
        elif choice == '2E':
            safe_execute("回饋規則設定同步", run_config_reward_sync)
        elif choice == '2F':
            safe_execute("匯率每日表同步", run_config_fx_table_sync)
        elif choice == '2G':
            safe_execute("電商平台維度同步", run_config_ec_platform_sync)
        elif choice == '3':
            safe_execute("C# 瀑布式回饋計算", run_cli_csharp_rewards, require_db=True)
        elif choice == '4':
            safe_execute("RFM 全方位消費分析", run_analytics, require_db=True)
        elif choice == '5':
            safe_execute("條件篩選匯出交易 CSV", run_cli_query_export, require_db=True)
        elif choice == '6':
            run_cli_web_server()
        elif choice == 'Q':
            print("\n感謝使用，程式已結束。")
            break
        elif choice == '':
            continue
        else:
            print(f"\n⚠️  無效的選項 '{choice}'，請重新選擇。")
