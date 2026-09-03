## 📅 開發日記 (Dev Log)
* **2026-09-04**
   * **ETL 程式碼整理3**：
     * 整理模組之間的架構跟引用關係，並整理成便於未來理解與撰寫測試資料的流程。
   * **Analytics API 模組化重構**：
     * 將時間相依圖表與金流桑基圖資料查詢邏輯從 router 移至 `analytics.common.chart` 模組。
     * 新增 Data Mart 專用查詢工具，統一 `analytics.api.rewards_service` 與 router 的資料來源。

* **2026-09-03**：
   * 前端修正

* **2026-09-01**：
   * 視覺化圖表展示調優、DEMO 脫敏分組與商家消費波動統計分析


* **2026-08-27**
   * **RFM 視覺化依類別篩選與各領域 Top 3 商家排行**：
     - 於 [analytics_dashboard.html](file:///d:/記帳用EXCEL/MyCreditCardProjectPro/web/analytics_dashboard.html) 新增 **消費類別即時篩選下拉選單**，切換時連動縮減氣泡圖點數並更新該類別之五大客群統計數值。
     - 新增 **「🏆 各生活消費領域 Top 3 核心主力商家」** 排行表格，依便利商店、百貨量販、連鎖飲食、商圈、生活服務、電子商務等分類，自動列出累積消費金額最高的前三名主力商家與客群分群。
     - 於 [api/routers/analytics.py](file:///d:/記帳用EXCEL/MyCreditCardProjectPro/api/routers/analytics.py) 之 `/api/analytics/rfm-chart` 新增 `top_by_category` 彙算與全域 `categories` 清單回傳。
   * **前端全任務控制台與純視覺化儀表板二元化重構**：
     - **全任務控制中心 (`web/task_console.html`)**：整合所有需要 Console 串流日誌之任務（ETL 帳單處理、SSOT 設定維度同步、C# 回饋計算、RFM 價值模型、條件 SQL 匯出），並消除跨 Tab 的重複 `config_all` 按鈕。
     - **純視覺化分析儀表板 (`web/analytics_dashboard.html`, `web/time_depend_plot.html`)**：依時間維度 (趨勢與桑基圖) 與卡片/客群維度 (RFM 氣泡九宮格與回饋池) 獨立拆分，移除所有 Console 雜訊。
     - **Console 模組化 (`web/scripts/console_runner.js`)**：封裝 TaskConsole 工具物件，支援 SSE 任務調度、關鍵字上色、狀態列更新、清空與「一鍵複製日誌」。
     - 總控制台 `index.html` 與 `cards_manager.html` 等 5 大核心頁面導覽列全面對齊。
   * **RFM 商家分類修復與維度表 JOIN 機制**：
     - 修復 `analytics/rfm/modules.py` 中多時間視窗聯集導致之 `category` / `sub_category` 遺失與被「未分類」覆蓋之問題。
     - 導入全域分類映射與 `dim_merchants` 維度表 Fallback 補齊機制，確保 100% 分類資料完整。
   * **C# 回饋計算結果 Data Mart 入庫**：
     - 實作 `sync_rewards_data_mart`，將 C# 瀑布式回饋計算結果彙總寫入 `database/TransactionsAnalysis.db` 中的 `rewards_monthly_summary` 與 `rewards_pool_utilization`。

* **2026-08-26**
   * **前端 視覺化6**：
     * 前端視覺化更新，增加時間相依圖表與金流桑基圖儀表板。
   

* **2026-08-25**
   * **回饋計算更新6**：
     * 檢查dotnet回饋程式與 python ETL資料庫的整合狀況，並將明細報表輸出收束至 `output/reward_dotnet/detail/`。
   * **Legacy code整理1**：
     * 確認舊有的Legacy code的作用目的，若有新的code已經實作了相同的功能，則移除舊有的code。
         - 因應PostgreSQL資料庫做為主資料庫中心，移除原本實作在SQLite主資料庫的邏輯與 `dual_loader.py` 雙寫機制。
   * **架構決策與規劃**：
     * 確立分析結果（RFM、Spending Matrix）收集至專屬 SQLite 分析庫 (`TransactionsAnalysis.db`)，以支援後續圖表視覺化與歷史跨期比對。
   * **Git 歷史更新3**：
     * git分支整理。


* **2026-08-17**
   * **Git 歷史更新2**：重置上傳的 commit 以符合個人資料脫敏原則。
   * **ETL 流程整理15**：
     - 確立整理到 `PostgreSQL` 的資料處理流程，並依據其需求，把對應的程式碼整理到對應資料夾階層的檔案中已確立職責分離。
   * **CSS 模組化1**：
     - 完成css的檔案拆分，並依據網頁呈現的視覺功能相對位置初步統一，但細部排版尚待修正。
     - 依據功能類別設置像是給網頁body、container、


* **2026-08-09**
   * **ETL 流程更新14**：
     * 檔案遷移以符合專案結構跟微服務概念。
   * **資料庫架構3**：
     * PostgreSQL Schema：
         - 新增銀行設定(dim_banks.csv)跟信用卡產品設定(dim_credit_card_products.csv)。
         - 建立半結構化資料導入與實作，確保能够透過提取最小量的必要資料，獲得足夠的資訊。

* **2026-07-28**
   * **Docker 化架構2**：
     - 撰寫 Python FastAPI 服務專用 `Dockerfile.python` 
     - 撰寫 C# 回饋計算服務 `dotnet/RewardEngine.Api/Dockerfile`。
     - 擴充 `docker-compose.yml` 實現三容器 (`db` PostgreSQL 17 + `csharp-api` + `python-api`) 一鍵啟動與本地端網路通訊連線。
   * **簡易 API 架構權責劃分**：
     - Python FastAPI 負責前端控制台 API (BFF) 與排程任務。
     - C# Minimal API 負責核心回饋計算。
     - PostgreSQL 負責資料儲存。

* **2026-07-21**
   * **專案架構2**：
      * 引入C#作為回饋計算引擎，以取代原本的python回饋引擎，解決python回饋引擎的資料膨脹狀況。
      * API 權責劃分與 Docker 化：並新增對應的API接口接上專案，以及更新docker容器。
      * 因應SQLite讀寫限制跟連線驗證限制，開始轉換為PostgreSQL資料庫，並更新docker容器。
   * **資料庫架構2**：
      * 想法轉變：從一個單一SQLite存放所有交易資料，到多個SQLite分散儲放交易資料跟設定資料之後，開始思考建立單一PostgreSQL資料庫，把所有分散掉的資料暫時集中管理。

* **2026-06-27**
   * **ETL 流程更新13**：
      * 修復永豐PDF資料抓取錯誤。
   * **前端 視覺化4**：
      * 新增rfm服務前端頁面，並移動原本index.html的rfm相關功能到新的html。
      * 新增回饋計算服務前端頁面，並移動原本index.html的回饋計算服務到新的html。
   * **資料庫架構1**：
      * 回饋資料庫依照不同銀行分散儲存銀行規則。
   * **前端 視覺化5**：
      * 網頁前端改善，核取方塊篩選功能實作。
   * **Docker化架構1**：
      * docker-compose基礎架構建立，初步採取單一docker。

* **2026-06-06**
   * **ETL 流程更新12**：
      * 資料提取更新：將原本設定檔的pandas讀表模式，更新為SQL提取模式。
   * **前端 視覺化3**：
      * 前端首頁更新：更新核取方塊作為條件篩選。


* **2026-05-30**
   * **RFM 分析更新3**：
      * `services/analysis_service.py` 更新：Matrix 產生模組改為使用 `const.TimeWindow` 枚舉，取代硬編碼的字典陣列。
   * **回饋計算更新5**：
      * `services/rewards_service.py` 更新：資料提取邏輯整合進 SQL 查詢中，並將分析結果寫入獨立的分析資料庫。     

* **2026-05-11**
   * **ETL 流程更新11**：
      * 命名調整：將python、資料庫用的名詞調整成snake_case以便識別資料處理變數。
      * 邏輯更新：分離行動支付跟第三方支付的判斷。
      * 列舉更新：正式引入 Enum 管理核心定義。

* **2026-05-06**
   * **前端 視覺化2**：
      * 前端服務更新：設定檔可透過網頁入口載入。
   * **ETL 流程更新10**：
      * 完成設定檔資料庫製作服務。

* **2026-04-29**
   * **ETL 流程更新9**：
      * 消費明細資料正規化下放 (Parser-Level Normalization)：
         - 將幣別補全邏輯（如自動補TWD）從 Service 層下放到各銀行Parser，確保原始資料提取階段即完成標準化。
         - 補齊 TWD 幣別缺失並清洗金額雜訊。
   * **資料型態定義準則化2**：
      * 更新全域變數宣告型態：
         - 改善 const.py 與 base.py 的型態強制轉換邏輯，提升 Pipeline 穩定性。 
   * **回饋計算更新4**：
      * 初步補強瀑布式計算引擎對日期、行動支付、消費地的判斷。

* **2026-04-15**
   * **回饋計算更新3**：
      * 回饋計算流程更新成瀑布式回饋引擎，依序計算特殊活動加碼回饋→一般消費定義排除→一般消費活動加碼回饋→一般消費。細部修正中。
   * **ETL 流程更新8**：
      * Merchant_Display SSOT：將清洗後的資料明細作為後續RFM分析跟回饋計算分析的資料來源。

* **2026-03-27**
   * **回饋計算更新2**：
      * 回饋計算流程建立，內容設定調整中。
   * **資料型態定義準則化1**：
      * 定義輸入輸出的資料型態，解決資料型態衝突報錯的問題。
   * **ETL 流程更新7**：
      * 帳單月份標籤實作：透過帳單資訊產生帳單月標籤定位回饋原始資料。

* **2026-03-21**
   * **前端 視覺化1**：
      * 專案架構調整，新增前端頁面以便傳送請求。
   * **資料隱私構想3**：
      * 僅使用本機端，不連網以符合個人使用情境，並檢討專案方向。
   * **專案架構1**：
      * 採取Python-SQLite3架構，以符合資料庫的資料處理

* **2026-03-12**
   * **核心準則建立**：完成 GEMINI.md，定義編碼規範、架構完整性保護，以及最核心的「核心變更驗證規範 (Refactoring Protocol)」。
   * **ETL 流程更新6**：
      * 配置載入器實作：建立 loaders/config_loader.py，支援多重編碼嘗試 (UTF-8 → Big5 → cp950) 與 Append/Replace 讀取策略。
      * 核心架構解耦：
         - 重構 main.py：將設定檔讀取邏輯從處理器移至進入點。
         - 重構 processors/ (merchant.py, classifier.py, refiner.py)：改為注入式規則架構，不再內部讀檔。
      * 穩定性驗證：透過 A/B 測試比對 result_old.csv 與 result_new.csv，確認重構前後處理結果 100% 完全一致。

* **2026-03-07**
   * **ETL 流程更新5**：
      * 專案架構調整，並同步整理檔案命名 (parser資料夾，和資料夾內的所有檔名) 。
      * 分散parser，從一條線處理轉成依據各銀行帳單格式進行模組呼叫。
   * **回饋計算更新1**：
      * 開始撰寫回饋計算邏輯

* **2026-02-07**
   * **資料隱私構想2**：
      * 撤下 Mock Data Generator (generate_mock.py) 與隱私分流架構 (Himitsu.py)。
   * **ETL 流程更新4**：
      * 重構專案檔案命名 (merchants.csv, payment_process.csv) 以符合工程慣例。
      * 支付規則(Regex)上傳，整理商家規則(Regex)中。
   * **RFM 分析更新2**：
      * RFM記錄邏輯上傳。
   * **Git 歷史更新1**：
      * 更新Git歷史紀錄

* **2026-02-02**
   * **ETL 流程更新3**：
      * 完成 `refine.py` 第一版。
   * **資料隱私構想1**：
      * 建立 Mock Data Generator (generate_mock.py) 與隱私分流架構 (Himitsu.py)。
   * **RFM 分析更新2**：
      * 開始分離EXCEL回饋紀錄邏輯跟跟RFM紀錄邏輯
   

* **2026-01-28**
   * **ETL 流程更新2**：
      * 重構了 `refine.py` 的邏輯。
      * 補強雙號自動歸戶功能，便於判斷是否使用虛擬卡。
      * 消費明細關鍵字表(Regex)定稿

* **2026-01-20**
   * **ETL 流程更新1**：
      * 專案初始化。完成第一版 ETL 架構 (`etl.py`)。
   * **RFM 分析更新1**：
      * 變更資料流處理模式，從原本寫在Excel的回饋相關資料跟RFM關資料開始形成專案。