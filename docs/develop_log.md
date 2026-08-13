## 📅 開發日記 (Dev Log)

* **2026-08-09**
   * **PostgreSQL Schema 自癒與備份修復**：
     - `PostgresLoader` 新增 `_ensure_table_columns_exist` 自動補齊 Missing Column（如 `consumption_place`），並於 `mode='replace'` 採用 `DROP TABLE ... CASCADE` 自動重置視圖與 Table 結構。
   - **`bank_no` 與非數值代碼 SSOT 型態執法**：
     - `ConfigLoader` 與 `SchemaEnforcer` 強制以 `dtype=str` 與 `zfill(3)` 保留 `bank_no` 前導零，完全隔離數值運算與識別碼。
   - **多 Postgres 微服務擴充藍圖歸檔**：
     - 在 `docs/database_architecture_and_expansion.md` 新增由 `dim_banks.yaml` 控制總線驅動的多 Postgres 容器實體隔離架構藍圖。

* **2026-07-29**
   * 檔案遷移以符合專案結構跟微服務概念。

* **2026-07-28**
   * 完成 **Docker 化架構補齊**：
     - 撰寫 Python FastAPI 服務專用 `Dockerfile.python` 與 C# 回饋計算服務 `dotnet/RewardEngine.Api/Dockerfile`。
     - 擴充 `docker-compose.yml` 實現三容器 (`db` PostgreSQL 17 + `csharp-api` + `python-api`) 一鍵啟動與網路通訊連線。
   * 建立簡易 API 架構權責劃分：
     - Python FastAPI 負責前端控制台 API (BFF) 與排程任務，C# Minimal API 負責核心回饋計算。

* **2026-07-21**
   * 把python回饋引擎變成C#回饋引擎，並新增對應的API接口接上專案，以及更新docker容器。

* **2026-06-30**
   * 修復永豐PDF資料抓取錯誤。
   * 新增rfm服務前端頁面，並移動原本index.html的rfm相關功能到新的html。
   * 新增回饋計算服務前端頁面，並移動原本index.html的回饋計算服務到新的html。
   * 回饋資料庫依照不同銀行分散儲存銀行規則。
   * 網頁前端改善，核取方塊篩選功能實作。

* **2026-06-06**
   * 資料提取更新：將原本設定檔的pandas讀表模式，更新為SQL提取模式。
   * 前端首頁更新：更新核取方塊作為條件篩選。


* **2026-05-30**
    * `services/analysis_service.py` 更新：Matrix 產生模組改為使用 `const.TimeWindow` 枚舉，取代硬編碼的字典陣列。
    * `services/rewards_service.py` 更新：資料提取邏輯整合進 SQL 查詢中，並將分析結果寫入獨立的分析資料庫。     

* **2026-05-11**
   * 命名調整：將python、資料庫用的名詞調整成snake_case以便識別資料處理變數。
   * 邏輯更新：分離行動支付跟第三方支付的判斷。
   * 枚舉更新：正式引入 Enum 管理核心定義。

* **2026-05-06**
   * 前端服務更新：設定檔可透過網頁入口載入。
   * 完成設定檔資料庫製作服務。

* **2026-04-29**
   * 資料正規化下放 (Parser-Level Normalization)：
        - 將幣別補全邏輯（如自動補TWD）從 Service 層下放到各銀行Parser，確保原始資料提取階段即完成標準化。
        - 補齊 TWD 幣別缺失並清洗金額雜訊。
   * 更新全域變數宣告型態：
        - 改善 const.py 與 base.py 的型態強制轉換邏輯，提升 Pipeline 穩定性。 
   * 回饋計算流程更新，持續補強瀑布式計算引擎對日期、行動支付、消費地的判斷。

* **2026-04-15**
   * 回饋計算流程更新成瀑布式回饋引擎，依序計算特殊活動加碼回饋→一般消費定義排除→一般消費活動加碼回饋→一般消費。細部修正中。
   * Merchant_Display SSOT：將清洗後的資料明細作為後續RFM分析跟回饋計算分析的SSOT。

* **2026-03-27**
   * 回饋計算流程建立，內容設定調整中
   * 資料型態定義法律化：定義輸入輸出的資料型態，解決資料型態衝突報錯的問題。
   * 帳單月份標籤實作：透過帳單資訊產生帳單月標籤定位回饋原始資料。

* **2026-03-21**
   * 專案架構調整，新增前端頁面以便傳送請求
   * 僅使用本機端，不連網以符合個人使用情境

* **2026-03-12**
   * 行為準則建立：完成 GEMINI.md，定義編碼規範、架構完整性保護，以及最核心的「核心變更驗證規範 (Refactoring Protocol)」。
   * 配置載入器實作：建立 loaders/config_loader.py，支援多重編碼嘗試 (UTF-8 → Big5 → cp950) 與 Append/Replace 讀取策略。
   * 核心架構解耦：
       * 重構 main.py：將設定檔讀取邏輯從處理器移至進入點。
       * 重構 processors/ (merchant.py, classifier.py, refiner.py)：改為注入式規則架構，不再內部讀檔。
   * 穩定性驗證：透過 A/B 測試比對 result_old.csv 與 result_new.csv，確認重構前後處理結果 100% 完全一致。

* **2026-03-07**
    * 專案架構調整，並同步整理檔案命名 (parser資料夾，和資料夾內的所有檔名) 。
    * 分散parser，從一條線處理轉成依據各銀行帳單格式進行模組呼叫。
    * 開始撰寫回饋計算邏輯

* **2026-02-07**
    * 撤下 Mock Data Generator (generate_mock.py) 與隱私分流架構 (Himitsu.py)。
    * 重構專案檔案命名 (merchants.csv, payment_process.csv) 以符合工程慣例。
    * RFM記錄邏輯上傳。
    * 支付規則(Regex)上傳，整理商家規則(Regex)中。
    * 更新Git歷史紀錄

* **2026-02-02**
    * 建立 Mock Data Generator (generate_mock.py) 與隱私分流架構 (Himitsu.py)。
    * 開始分離EXCEL回饋紀錄邏輯跟跟RFM紀錄邏輯

* **2026-02-01**
    * 完成 `refine.py` 第一版。

* **2026-01-28**
    * 重構了 `refine.py` 的邏輯。遇到一個 Bug：有些卡號末四碼會重複，後來決定加入「卡片名稱」作為第二鍵值來解決。
    * 新增了國泰 Cube 卡的雙號自動歸戶功能。
    * 消費明細關鍵字表(Regex)定稿

* **2026-01-20**
    * 專案初始化。完成第一版 ETL 架構 (`etl.py`)。
    * 變更資料流處理模式，從原本寫在Excel的回饋相關資料跟RFM關資料開始形成專案。