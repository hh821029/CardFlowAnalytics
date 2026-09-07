# run_demo_web.py
"""
Demo 展示專用 Web 伺服器啟動腳本
完全隔離機制：
1. 嚴格鎖定 ACTIVE_PROFILE=example_public
2. 指向獨立的 Demo SQLite 資料庫：
   - database/TransactionsBills_demo.db
   - database/TransactionsConfigs_demo.db
   - database/TransactionsAnalysis_demo.db
3. 絕不讀取、絕不寫入、絕不污染正式環境或 user_main 資料庫！
"""
import os
import sys
import webbrowser

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 1. 強制設定環境變數為 Demo 隔離狀態
os.environ["ACTIVE_PROFILE"] = "example_public"
os.environ["DB_BACKEND"] = "sqlite"

DEMO_BILLS_DB = os.path.join(ROOT_DIR, "database", "TransactionsBills_demo.db")
DEMO_CONFIGS_DB = os.path.join(ROOT_DIR, "database", "TransactionsConfigs_demo.db")
DEMO_ANALYSIS_DB = os.path.join(ROOT_DIR, "database", "TransactionsAnalysis_demo.db")

os.environ["TRANSACTIONS_DB_PATH"] = DEMO_BILLS_DB
os.environ["CONFIGS_DB_PATH"] = DEMO_CONFIGS_DB
os.environ["ANALYSIS_DB_PATH"] = DEMO_ANALYSIS_DB

if __name__ == "__main__":
    # 若尚未產生 Demo 資料庫，提示先執行 prepare_demo_dataset.py
    if not os.path.exists(DEMO_BILLS_DB) or not os.path.exists(DEMO_ANALYSIS_DB):
        print("⚠️ 尚未偵測到 Demo 隔離資料庫，正在為您自動初始化...")
        from prepare_demo_dataset import prepare_demo_dataset
        prepare_demo_dataset()

    print("\n" + "=" * 65)
    print("🚀 【CardFlow Analytics】Demo Web 控制台啟動中 (Port 8000)")
    print("=" * 65)
    print(f"🔒 Profile 模式        : example_public (公開展示)")
    print(f"📁 帳單庫 (Bills)       : {DEMO_BILLS_DB}")
    print(f"📊 分析超市 (Analysis)  : {DEMO_ANALYSIS_DB}")
    print("🌐 瀏覽器存取網址       : http://127.0.0.1:8000")
    print("👑 推薦體驗頁面         : http://127.0.0.1:8000/web/analytics_dashboard.html")
    print("⏹️  若要結束服務，請在終端機按 Ctrl + C")
    print("=" * 65 + "\n")

    try:
        import uvicorn
        # 自動打開預設瀏覽器進入推薦的 RFM / 回饋儀表板
        try:
            webbrowser.open("http://127.0.0.1:8000/web/analytics_dashboard.html")
        except Exception:
            pass
        uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)
    except ImportError:
        print("❌ 找不到 uvicorn 套件，請先執行: pip install uvicorn")
    except Exception as e:
        print(f"❌ 伺服器啟動失敗: {e}")
