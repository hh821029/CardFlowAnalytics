# 專案目錄結構與模組架構說明 (File Structure & Architecture)

## 📌 一、專案全域目錄樹 (Directory Tree)
```text
.
My-Credit-Card-ETL/
│
├── .gitignore                  #
├── README.md                   # 介紹文件
├── requirements.txt            # [環境] 專案相依套件清單
├── main.py                     # [入口點] 核心 ETL 流程控制器
├── const.py                    # [規範] 全域欄位定義與資料型態 (Single Source of Truth)
│   
├── api/
│   ├── server.py               # web進入點
│   └── routers/                # 各服務 API 進入點 
│
├── database/                   # [資料庫層] 負責與資料庫進行互動
│   ├── database_api.py         # 模組轉接點        
│   └── loaders/                # 資料庫相關的載入與管理
│
├── etl/                        # [ETL 資料處理層] 跨銀行帳單提取、洗滌與視圖管理
│   ├── etl_api.py              # ETL 流程控制器 (Facade API)
│   ├── etl_extraction.py       # 原始帳單檔案掃描與解析調度
│   ├── etl_transformation.py   # 商家/支付管道交叉洗滌與正規化
│   ├── views_manager.py        # PostgreSQL / SQLite 視圖建立與維護
│   ├── utils.py                # 欄位標準化常數定義
│   ├── parsers/                # 各銀行專用 Parser (玉山、國泰、中信、富邦、台新、星展等)
│   └── processors/             # 商家正規化、支付管道、卡片分類 (card_classifier) 與交易分類(transaction_classifier)
│
├── analytics/                  # [分析與模型層] 多時間視窗 RFM 客群與消費矩陣
│   ├── api.py                  # 分析模組統一進入點 (run_analytics)
│   ├── common/                 # 共用資料提取、過濾與排名工具
│   ├── rfm/                    # 商家、消費類別、支付方式、信用卡四大維度 RFM
│   ├── sankeyflow/             # 金流桑基圖
│   └── matrix/                 # 三層支付管道 × 消費類別之消費矩陣 (Spending Matrix)
│
├── profiles/                   # [設定檔與規則層] 個人化與公開規則分離管理
│   ├── profiles_api.py         # 設定檔同步進入點
│   ├── common/configs/         # 公開通用設定 (dim_banks, dim_payment_process 等)
│   ├── example_public/         # 公開範例 Profile
│   ├── loaders/                # ConfigLoader (支援雙層疊加與 JSON/YAML 載入)
│   └── user_main/              # 個人私有設定檔 (已透過 .gitignore 排除)
│
├── web/                        # [前端介面層] 原生 Vanilla HTML/CSS/JS 控制台
│   ├── index.html              # 總控制台首頁
│   ├── etl.html                # 帳單 ETL 處理面板
│   ├── rfm_service.html        # RFM 與 Matrix 分析視覺化面板
│   ├── reward_service.html     # 回饋計算面板
│   ├── cards_manager.html      # 信用卡視覺化管理面板
│   └── sync_config.html        # 設定檔同步面板
│
├── dotnet/                     # [高效能回饋引擎] C# .NET 8 核心回饋計算服務
│   ├── RewardEngine.Core/      # 瀑布式回饋計算演算法與規則引擎
│   └── RewardEngine.Api/       # C# Minimal API (Port 5000)
│
└── docs/                       # [專案文件] 開發日誌、架構規劃與檔案結構說明

```
## 🏛️ 二、分層架構與職責劃分 (Architecture Layers)
依據職責將目錄分類為 6 大層級，並說明呼叫方向：
1. **進入點層 (Entrypoints)**：`main.py` (CLI), `api/server.py` (Web API)
2. **Web 與控制台層 (Presentation Layer)**：`web/`, `api/routers/`
3. **資料處理與洗滌層 (ETL Layer)**：`etl/parsers/`, `etl/processors/`
4. **資料庫與基礎設施層 (Infrastructure Layer)**：`database/loaders/`
5. **商業邏輯與分析模型層 (Domain & Analytics Layer)**：`analytics/`, `dotnet/`
6. **設定與規則管理層 (Configuration & Profiles Layer)**：`profiles/`, `const.py`

## 🔄 三、資料處理生命週期 (Data Pipeline Lifecycle)
用簡單的箭頭圖呈現資料從輸入到產出的流動：
`原始帳單 (data/)` 
  ➔ `ETL 解析與商家洗滌 (etl/)` 
  ➔ `PostgreSQL / SQLite 儲存 (database/)` 
  ➔ `全維度視圖 (vw_rfm_analysis / vw_rewards_calculation)` 
  ➔ `RFM & 矩陣報表 (analytics/) / 回饋計算 (dotnet/)`
## 🔒 四、隱私安全與規則分離規範 (Rule Segregation & Security)
- **公開通用規則**：`profiles/common/configs/`
- **個人私有規則**：`profiles/user_main/`（嚴格受 `.gitignore` 排除保護）
- **暫存與產出物**：`output/`、`input/`、`data/`