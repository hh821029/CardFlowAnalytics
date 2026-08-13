## 📂 檔案結構 (File Structure)

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
│   └── server.py               # [本機端伺服器] 
│ 
├── services/                   # [服務層] 負責呼叫服務對應的解析層、處理層
│   ├── config_service.py       # 服務：帳單關聯設定產生DB資料庫        
│   ├── etl_service.py          # 服務：帳單資料清洗並產生SQLite資料庫
│   ├── analysis_service.py     # 服務：從SQLite資料庫提取RFM分析要用的基本資料，並產生多視角報表
│   └── reward_service.py       # 服務：從SQLite資料庫提取回饋計算要用的資料
│  
├── parsers/                    # [解析層] 負責各銀行原始帳單轉為標準 DataFrame
│   ├── base.py                 # Parser 基類，定義統一介面
│   ├── cathay.py               # 國泰世華 (csv) 解析邏輯
│   ├── esun.py                 # 玉山銀行 (csv) 解析邏輯
│   ├── CTBC.py                 # 中國信託 (csv) 解析邏輯
│   ├── sinopac.py              # 永豐銀行 (PDF) 解析邏輯
│   └── hncb.py                 # 華南銀行 (格式偽裝) 解析邏輯
│
├── processors/                 # [處理層] 負責資料清洗、分類與商家對齊
│   ├── refiner.py              # 清洗總指揮，協調各子處理器
│   ├── classifier.py           # 自動標記交易類別 (一般、國外、退刷、繳款)
│   ├── merchant.py             # 商家名稱清洗與正規化
│   ├── mapper.py               # 欄位對應處理
│   └── rewards.py               # 回饋計算處理
│
├── loaders/                    # [載入層] 負責資料儲存、載入設定檔資料
│   ├──bills_to_db.py           # 將清洗好的帳單資料存入Bills.db
│   ├──sync_configs_to_db.py    # 將整理好的設定資料存入Configs.db
│   ├──schema_enforcer.py       # 匯入型別規則已確認資料型態是否指定，阻止針對資料型態的預測
│   ├──sqlite_loader.py         # 將資料匯入 SQLite (Bills.db、Configs.db) 
│   └──config_loader.py         # 將相關的設定資料匯入主程式執行
│
├── analytics/                  # [分析層] 負責進階數據建模
│   ├── run_rfm.py              # RFM 分析執行腳本
│   ├── rfm_modules.py          # RFM 計算引擎 (Merchant/Payment/Card)
│   ├── rfm_utils.py            # RFM 計算核心
│   ├── run_rewards.py          # 回饋金計算執行腳本
│   ├── ml_fallback.py          # 
│   ├── ml_dataset_export.py    # 
│   └── ml_category_analysis.py # 
│
├── configs/                            # [設定檔資料夾] 
│   ├── db_columns_mapping.py           # [設定檔] 資料庫欄位映射定義
│   ├── dim_cards.csv                   # [設定檔] 真實卡號放置地點(已提供可直接讀取的範例檔)
│   ├── transaction_types.yaml          # [設定檔] 銀行交易類別，排除持卡人跟銀行的交易像繳款、折抵/回饋、費用(手續費/服務費)(公開)
│   ├── dim_merchants.csv               # [設定檔] 真實交易地點，使用Regex(正則表達式)-Replacement來清洗消費明細(部分公開)
│   ├── dim_payment_process.csv         # [設定檔] 支付/處理流程，使用Regex(正則表達式)-Replacement來整理支付通路(公開)
│   ├── dim_card_rewards_base.csv       # [設定檔] 基本回饋設定(已在 .gitignore )
│   ├── dim_card_rewards_campaigns.csv  # [設定檔] 消費活動回饋設定(已在 .gitignore)
│   ├── bridge_reward_rules.csv         # [設定檔] 基本回饋設定橋接表(已在 .gitignore)
│   └── bridge_cube_selections.csv      # [設定檔] Cube權益切換橋接表(已在 .gitignore)
│
├── data/                       # [帳單csv放置處] 真實的 CSV 帳單放這邊。
│   └── (各銀行帳單)
└── output/                     # [輸出區] 存放 Bills.db、Configs.db 與 分析報表 (已在 .gitignore)

```
附註：
實際使用的資料依據config_loader.py設定的讀取狀態來處理資料。
dim_cards.csv可作為樣板自行修改。
dim_merchants.csv直接更新在欄位下方就好。

