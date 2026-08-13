using RewardEngine.Core.Loaders;
using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using System.Runtime.CompilerServices;
using System.Threading.Channels;


namespace RewardEngine.Api.Services;

/// <summary>
/// 封裝 Rewards 計算流程，以 IAsyncEnumerable&lt;string&gt; 輸出 SSE log 訊息。
/// 對應 Python server.py 的 run_task_and_stream + run_rewards_calculation 邏輯。
/// </summary>
public sealed class RewardsApiService
{
    // 控制同時只能有一個任務執行（對應 Python 的 threading.Lock）
    private static readonly SemaphoreSlim _taskLock = new(1, 1);

    private readonly IConfiguration _config;
    private readonly ILogger<RewardsApiService> _logger;

    public RewardsApiService(IConfiguration config, ILogger<RewardsApiService> logger)
    {
        _config = config;
        _logger = logger;
    }

    /// <summary>
    /// 執行 Rewards 計算並即時輸出 SSE log 訊息串流。
    /// 對應 Python: /api/run/rewards
    /// </summary>
    public async IAsyncEnumerable<string> RunRewardsAsync(
        List<string>? banks,
        List<string>? cards,
        List<string>? payments,
        string? timeWindow,
        string? startDate,
        string? endDate,
        string? location,
        bool enableBillingValidation,
        bool limitByCardStart,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        const string taskName = "回饋金計算";

        // 1. 任務互斥鎖檢查（對應 Python: if _task_lock.locked()）
        if (!await _taskLock.WaitAsync(0, ct))
        {
            yield return $"data: ⚠️ [系統忙碌] 任務 '{taskName}' 無法啟動。目前已有其他任務正在執行，請稍後再試。\n\n";
            yield break;
        }

        // 2. 檢查資料庫是否存在 (SQLite 模式檢查本機檔，PostgreSQL / Dual 模式直接連線網路庫)
        var section = _config.GetSection("RewardEngine");

        var dbPath = ResolvePath(section, "DbPath", "database/TransactionsBills.db");
        var configsPath = ResolvePath(section, "ConfigsPath", "configs");
        var csvSection = section.GetSection("CsvFiles");

        var dbBackend = Environment.GetEnvironmentVariable("DB_BACKEND") ?? "postgres";
        bool isPostgresMode = string.Equals(dbBackend, "postgres", StringComparison.OrdinalIgnoreCase) 
                           || string.Equals(dbBackend, "dual", StringComparison.OrdinalIgnoreCase);

        if (!isPostgresMode && !File.Exists(dbPath))
        {
            _taskLock.Release();
            yield return $"data: ❌ [找不到資料庫] 任務 '{taskName}' 失敗。原因：找不到主資料庫檔案 ({dbPath})，請先執行 ETL 載入帳單資料。\n\n";
            yield break;
        }

        // 3. 建立 Channel 作為 log 訊息佇列（對應 Python 的 asyncio.Queue）
        var channel = Channel.CreateUnbounded<string?>(new UnboundedChannelOptions { SingleWriter = true });

        // 4. 在背景 Task 執行同步計算（對應 Python 的 threading.Thread）
        _ = Task.Run(() =>
        {
            try
            {
                channel.Writer.TryWrite($"data: --- 啟動 {taskName} (Web API 呼叫) ---\n\n");

                // 解析日期過濾條件
                DateOnly? from = null, to = null;
                if (!string.IsNullOrEmpty(startDate) && DateOnly.TryParse(startDate, out var f)) from = f;
                if (!string.IsNullOrEmpty(endDate) && DateOnly.TryParse(endDate, out var t)) to = t;

                // 載入規則與維度資料表 (PostgreSQL / CSV 備援)
                channel.Writer.TryWrite("data: ⚙️ 載入規則與維度資料表...\n\n");
                var pgConnStr = SqliteTransactionReader.GetPostgresConnectionStringFromEnv();

                List<CardRewardProgram> basePrograms;
                List<CardRewardProgram> campaignPrograms;
                List<RewardBridgeRule> bridgeRules;
                IBenefitSelectionStrategy? dailySelection = null;
                IBenefitSelectionStrategy? monthlySelection = null;
                BillingCycleResolver? billingResolver = null;

                if (isPostgresMode)
                {
                    channel.Writer.TryWrite("data: 🔌 連線 PostgreSQL 載入全量維度與計算規則...\n\n");
                    basePrograms = PostgresRuleLoader.LoadBasePrograms(pgConnStr);
                    campaignPrograms = PostgresRuleLoader.LoadCampaignsPrograms(pgConnStr);
                    bridgeRules = PostgresRuleLoader.LoadBridgeRules(pgConnStr);

                    var dailyData = PostgresRuleLoader.LoadDailySelections(pgConnStr);
                    if (dailyData.Count > 0)
                        dailySelection = new DailySelectionStrategy(dailyData, targetBankName: "cube", targetCardType: "Cube卡");

                    var monthlyData = PostgresRuleLoader.LoadMonthlySelections(pgConnStr);
                    if (monthlyData.Count > 0)
                        monthlySelection = new MonthlySelectionStrategy(monthlyData, targetBankName: "esun", targetCardType: "Unicard");

                    var billingRecords = PostgresRuleLoader.LoadBillingHistory(pgConnStr);
                    if (billingRecords.Count > 0)
                        billingResolver = new BillingCycleResolver(billingRecords);
                }
                else
                {
                    basePrograms = CsvRuleLoader.LoadBasePrograms(
                        Path.Combine(configsPath, csvSection["BasePrograms"] ?? "dim_card_rewards_base.csv"));

                    campaignPrograms = CsvRuleLoader.LoadCampaignsPrograms(
                        Path.Combine(configsPath, csvSection["CampaignsPrograms"] ?? "dim_card_rewards_campaigns.csv"));

                    var privateCampaignPath = Path.Combine(configsPath, csvSection["CampaignsProgramsPrivate"] ?? "dim_card_rewards_campaigns_private.csv");
                    if (File.Exists(privateCampaignPath))
                        campaignPrograms.AddRange(CsvRuleLoader.LoadCampaignsPrograms(privateCampaignPath));

                    bridgeRules = CsvRuleLoader.LoadBridgeRules(
                        Path.Combine(configsPath, csvSection["BridgeRules"] ?? "bridge_reward_rules.csv"));

                    var dailyPath = Path.Combine(configsPath, csvSection["DailySelections"] ?? "bridge_cube_selections_private.csv");
                    if (File.Exists(dailyPath))
                    {
                        var dailyData = CsvRuleLoader.LoadDailySelections(dailyPath);
                        dailySelection = new DailySelectionStrategy(dailyData, targetBankName: "cube", targetCardType: "Cube卡");
                    }

                    var monthlyPath = Path.Combine(configsPath, csvSection["MonthlySelections"] ?? "bridge_unicard_selections_private.csv");
                    if (File.Exists(monthlyPath))
                    {
                        var monthlyData = CsvRuleLoader.LoadMonthlySelections(monthlyPath);
                        monthlySelection = new MonthlySelectionStrategy(monthlyData, targetBankName: "esun", targetCardType: "Unicard");
                    }

                    var billingHistoryPath = Path.Combine(configsPath, csvSection["BillingHistory"] ?? "dim_billing_history_private.csv");
                    if (File.Exists(billingHistoryPath))
                    {
                        var billingRecords = CsvRuleLoader.LoadBillingHistory(billingHistoryPath);
                        billingResolver = new BillingCycleResolver(billingRecords);
                    }
                }

                var cycleTracker = new RewardCycleTracker(billingResolver);

                var allPrograms = basePrograms.Concat(campaignPrograms).ToList();
                channel.Writer.TryWrite($"data: ✅ 規則載入完成 — Base: {basePrograms.Count} 筆, Campaign: {campaignPrograms.Count} 筆, Bridge: {bridgeRules.Count} 筆\n\n");

                // 讀取交易資料（對接 PostgreSQL 集中資料庫）
                channel.Writer.TryWrite("data: ⚙️ 從 PostgreSQL 資料庫讀取交易資料...\n\n");
                var transactions = PostgresTransactionReader.Load(
                    pgConnStr,
                    bankName: banks?.Count == 1 ? banks[0] : null,
                    cardType: cards?.Count == 1 ? cards[0] : null,
                    from: from,
                    to: to);

                channel.Writer.TryWrite($"data: ✅ 讀取完成，共 {transactions.Count} 筆交易 (from PostgreSQL)\n\n");

                // 執行回饋計算（逐筆處理，特定錯誤收集後寫 errorlog，不中斷整體流程）
                channel.Writer.TryWrite("data: ⚙️ 執行回饋金計算...\n\n");
                var resolver = new RewardResolver(allPrograms, bridgeRules, dailySelection, monthlySelection, cycleTracker);

                var results = new List<ResolvedReward>();
                var errorTransactions = new List<(RewardTransaction Txn, string Reason)>();

                foreach (var txn in transactions)
                {
                    try
                    {
                        results.Add(resolver.Resolve(txn));
                    }
                    catch (Exception ex)
                    {
                        // 異常/未支援類型（如 AGGREGATE、月結爭議等）：收集至 errorlog 並即時印出 Warning，不中斷整體計算
                        errorTransactions.Add((txn, ex.Message));
                        channel.Writer.TryWrite($"data: ⚠️ [Warning/跳過] {ex.Message}\n\n");
                        _logger.LogWarning(ex, "跳過交易 {TxnId}：{Reason}", txn.TransactionId, ex.Message);
                    }
                }

                var totalReward = results.Sum(r => r.TotalRewardAmount);
                channel.Writer.TryWrite($"data: ✅ 計算完成！共計算 {results.Count} 筆，合計回饋金額 {totalReward:F2} 元\n\n");

                // 若有錯誤交易，寫入 errorlog CSV
                if (errorTransactions.Count > 0)
                {
                    var errorLogDir = ResolvePath(section, "ErrorLogPath", "output");
                    Directory.CreateDirectory(errorLogDir);
                    var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                    var errorLogPath = Path.Combine(errorLogDir, $"errorlog_{timestamp}.csv");

                    var csvLines = new List<string>
                    {
                        // 欄頭對齊 Python errorlog 格式
                        "transaction_id,transaction_date,merchant_display,merchant_location,mobile_payment,payment_amount,card_type,bank_name,transaction_type,error_reason"
                    };

                    foreach (var (txn, reason) in errorTransactions)
                    {
                        // 欄位若含逗號或換行，加雙引號包覆
                        static string Esc(string? v) =>
                            v is null ? "" :
                            v.Contains(',') || v.Contains('"') || v.Contains('\n')
                                ? $"\"{v.Replace("\"", "\"\"")}\""
                                : v;

                        csvLines.Add(string.Join(",",
                            Esc(txn.TransactionId),
                            Esc(txn.TransactionDate.ToString("yyyy-MM-dd")),
                            Esc(txn.MerchantDisplay),
                            Esc(txn.MerchantLocation),
                            Esc(txn.MobilePayment),
                            txn.Amount.ToString("F1"),
                            Esc(txn.CardType),
                            Esc(txn.BankName),
                            Esc(txn.TransactionType),
                            Esc(reason)));
                    }

                    File.WriteAllLines(errorLogPath, csvLines, System.Text.Encoding.UTF8);
                    channel.Writer.TryWrite($"data: ⚠️ 共 {errorTransactions.Count} 筆交易需人工確認，已寫入 errorlog：{Path.GetFileName(errorLogPath)}\n\n");
                    _logger.LogWarning("已寫入 errorlog：{Path}", errorLogPath);
                }

                channel.Writer.TryWrite($"data: --- {taskName} 執行完畢 ---\n\n");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "回饋金計算發生非預期錯誤");
                channel.Writer.TryWrite($"data: ❌ {taskName} 執行過程中發生非預期錯誤: {ex.Message}\n\n");
            }
            finally
            {
                channel.Writer.TryWrite(null); // null = 結束訊號（對應 Python 的 queue.put_nowait(None)）
                _taskLock.Release();
            }
        }, ct);

        // 5. 從 Channel 讀取訊息並輸出（對應 Python 的 while True: msg = await queue.get()）
        await foreach (var msg in channel.Reader.ReadAllAsync(ct))
        {
            if (msg is null) yield break;
            yield return msg;
        }
    }

    private static string ResolvePath(IConfigurationSection section, string key, string fallback)
    {
        var raw = section[key] ?? fallback;
        if (Path.IsPathRooted(raw) && (Directory.Exists(raw) || File.Exists(raw))) return raw;
        var p1 = Path.GetFullPath(raw);
        if (Directory.Exists(p1) || File.Exists(p1)) return p1;
        var clean = raw.Replace("../../", "").Replace("../", "");
        var p2 = Path.GetFullPath(clean);
        if (Directory.Exists(p2) || File.Exists(p2)) return p2;
        return p1;
    }
}
