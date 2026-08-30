# ⚡ 快速上手指南 (Quick Start Guide)

歡迎使用 **CardFlow Analytics**！本指南將帶您使用內建的**脫敏範例資料 (Mock Data)**，快速體驗「帳單 ETL 解析 ➔ 規則維度同步 ➔ RFM 客群分析 ➔ C# 瀑布式回饋試算」的完整資料管線。

---

## 🛠️ 1. 環境需求與準備

- **Python**：3.10 或更高版本
- **.NET SDK**（選填，欲執行 C# 回饋引擎時需要）：.NET 8.0 SDK
- **資料庫**：內建支援 SQLite（零配置，開箱即用）或 PostgreSQL 17

---

## 📦 2. 安裝與環境設定

### 步驟 2-1：Clone 專案與建立虛擬環境
```bash
# 1. 複製專案
git clone https://github.com/hh821029/CardFlowAnalytics.git
cd CardFlowAnalytics

# 2. 建立並啟動 Python 虛擬環境
python -m venv .venv

# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 3. 安裝 Python 依賴套件
pip install -r requirements.txt
```

### 步驟 2-2：啟用範例環境設定檔
```bash
# 複製環境變數範本 (預設使用 example_public 公開範例 Profile 與 SQLite)
cp .env.example .env
```

---

## 🎭 3. 產生脫敏範例帳單 (Mock Data)

專案內建各大銀行的脫敏帳單生成器，可一鍵生成涵蓋**玉山銀行、國泰世華、中國信託、華南銀行**之測試帳單：

```bash
python generate_mock_data.py
```
> ✅ 執行完成後，虛擬帳單將自動存放於 `profiles/example_public/data/`。

---

## 🚀 4. 體驗執行方式

### 方式 A：Web 視覺化控制台 (推薦)
```bash
python -m uvicorn api.server:app --port 8000
```
1. 打開瀏覽器訪問 `http://127.0.0.1:8000`。
2. 進入 **「資料管理中樞」** 點擊 **「🚀 執行全量 ETL 解析」**。
3. 進入 **「分析與回饋中樞」** 即可檢視：
   - 📊 **RFM 價值模型**（商家、卡別、支付管道多時間視窗客群分佈）。
   - 🌊 **消費金流桑基圖 (Sankey Flow)**。
   - 💰 **C# 瀑布式回饋金試算**（支援上限扣抵與 SSE 即時串流）。

### 方式 B：CLI 互動式控制台
```bash
python main.py
```
- 輸入 `1F`：執行全量 ETL 帳單解析與入庫。
- 輸入 `4`：執行 RFM 全方位消費分析並產出報表。
- 輸入 `3`：執行 C# 瀑布式回饋引擎試算。

---

## 🔒 5. 如何切換為您本人的真實信用卡帳單？

本專案採用**雙層 Profile 隱私隔離架構**，您的真實帳單與個資會被 Git 嚴格忽略：

1. **建立您的私有 Profile**：
   在 `profiles/` 下建立個人目錄，例如 `profiles/user_main/data/` 與 `profiles/user_main/configs/`。
2. **放入個人帳單**：
   將您的銀行 PDF/CSV 帳單放入 `profiles/user_main/data/`。
3. **切換環境變數**：
   編輯 `.env` 檔案，修改為：
   ```ini
   ACTIVE_PROFILE=user_main
   ```
4. **重新執行 ETL**：
   再次執行 `python main.py`（選 `1F`）或從 Web 控制台執行 ETL，系統即會自動切換為分析您的真實財務數據！
