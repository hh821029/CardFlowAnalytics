# main.py
import logging
import os
import sys
import time

# 引入核心 ETL 與 Analytics 分析 API
import const
from etl.etl_api import run_etl_pipeline
from analytics.api import run_analytics
from profiles.profiles_api import run_all_config_sync

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
    """顯示控制台選單"""
    print("\n" + "■"*40)
    print("  MyCreditCardProjectPro 控制台 (CLI)")
    print("■"*40)
    print("  1.  [ETL] 掃描原始檔案並產生/更新資料庫 (去重檢查)")
    print("  1F. [ETL Force] 強制全量重新解析所有帳單檔案")
    print("  2.  [RFM] 執行全方位 RFM 分析 (需資料庫)")
    print("  3.  [Rewards] 計算信用卡回饋 (需資料庫)")
    print("  4.  [Configs] 設定載入測試")
    print("  Q.  退出程式")
    print("-" * 40)

def run_cli_csharp_rewards():
    """CLI 模式下連線 C# 引擎進行回饋計算與日誌印出"""
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
    except Exception as e:
        print(f"❌ 呼叫 C# 引擎失敗: {e} (請確認 C# RewardEngine.Api:5000 是否已啟動)")

# ==========================================
# 主進入點
# ==========================================
if __name__ == "__main__":
    while True:
        show_menu()
        choice = input("請輸入選項 (1/1F/2/3/4/Q): ").strip().upper()
        
        if choice == '1':
            safe_execute("ETL 流程 (產生資料庫)", run_etl_pipeline)
        elif choice == '1F':
            safe_execute("ETL 流程 (強制全量重新解析)", lambda: run_etl_pipeline(force=True))
        elif choice == '2':
            safe_execute("RFM 分析", run_analytics, require_db=True)
        elif choice == '3':
            safe_execute("C# 回饋計算", run_cli_csharp_rewards, require_db=True)
        elif choice == '4':
            safe_execute("同步與載入所有設定檔 (Configs)", run_all_config_sync)
        elif choice == 'Q':
            print("\n感謝使用，程式已結束。")
            break
        elif choice == '':
            continue
        else:
            print(f"\n⚠️  無效的選項 '{choice}'，請重新選擇。")
