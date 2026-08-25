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

        // 2. 檢查資料庫是否存在 (SQLite 模式檢查本機檔，PostgreSQL 模式直接連線網路庫)
        var section = _config.GetSection("RewardEngine");

        var dbPath = ResolvePath(section, "DbPath", "database/TransactionsBills.db");
        var configsPath = ResolvePath(section, "ConfigsPath", "configs");
        var csvSection = section.GetSection("CsvFiles");

        var dbBackend = Environment.GetEnvironmentVariable("DB_BACKEND") ?? "postgres";
        bool isPostgresMode = string.Equals(dbBackend, "postgres", StringComparison.OrdinalIgnoreCase);

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

                // 取得 PostgreSQL 連線字串
                var pgConnStr = PostgresTransactionReader.GetPostgresConnectionString();

                // 1. 檢查 PostgreSQL 核心必備資料表是否存在
                channel.Writer.TryWrite("data: 🔍 檢查 PostgreSQL 資料庫資料表完整性...\n\n");
                var requiredTables = new[]
                {
                    "rewards_transactions",
                    "dim_card_rewards_base",
                    "dim_card_rewards_campaigns",
                    "bridge_reward_linked_lists",
                    "bridge_reward_pools"
                };

                var missingTables = PostgresRuleLoader.CheckRequiredTables(pgConnStr, requiredTables);
                if (missingTables.Count > 0)
                {
                    channel.Writer.TryWrite($"data: ❌ [資料庫表缺失] 找不到必要資料表 [{string.Join(", ", missingTables)}]。\n\n");
                    channel.Writer.TryWrite("data: 💡 請先在 Web 控制台執行「🚀 產生帳單資料庫 (ETL)」並執行配置同步 (sync_configs_to_db)。\n\n");
                    return;
                }

                // 2. 載入方案、規則池與關聯表
                channel.Writer.TryWrite("data: ⚙️ 載入回饋方案與回饋池 (Pools & Linked Lists)...\n\n");
                var basePrograms = PostgresRuleLoader.LoadBasePrograms(pgConnStr);
                var campaignPrograms = PostgresRuleLoader.LoadCampaignsPrograms(pgConnStr);
                var allPrograms = basePrograms.Concat(campaignPrograms).ToList();
                var pools = PostgresRuleLoader.LoadRewardPools(pgConnStr);
                var linkedLists = PostgresRuleLoader.LoadRewardLinkedLists(pgConnStr);

                var billingRecords = PostgresRuleLoader.LoadBillingHistory(pgConnStr);
                var billingResolver = billingRecords.Count > 0 ? new BillingCycleResolver(billingRecords) : null;
                var cycleTracker = new RewardCycleTracker(billingResolver);

                channel.Writer.TryWrite($"data: ✅ 規則載入完成 — Base: {basePrograms.Count} 筆, Campaign: {campaignPrograms.Count} 筆, Pools: {pools.Count} 個, Links: {linkedLists.Count} 筆\n\n");

                // 3. 讀取交易資料（對接 PostgreSQL 交易事實表）
                channel.Writer.TryWrite("data: ⚙️ 從 PostgreSQL 資料庫讀取交易資料...\n\n");
                var transactions = PostgresTransactionReader.Load(
                    pgConnStr,
                    bankName: banks?.Count == 1 ? banks[0] : null,
                    cardType: cards?.Count == 1 ? cards[0] : null,
                    from: from,
                    to: to);

                channel.Writer.TryWrite($"data: ✅ 讀取完成，共 {transactions.Count} 筆交易 (from PostgreSQL)\n\n");

                // 4. 動態檢查交易中的卡別，判定是否需要載入每日切換策略 (Cube卡 / Richart卡)
                IBenefitSelectionStrategy? dailySelection = null;
                var dailyStrategies = new List<IBenefitSelectionStrategy>();

                var distinctCardTypes = transactions
                    .Select(t => t.CardType)
                    .Where(c => !string.IsNullOrWhiteSpace(c))
                    .ToHashSet(StringComparer.OrdinalIgnoreCase);

                bool hasCube = distinctCardTypes.Any(c => c.Contains("Cube", StringComparison.OrdinalIgnoreCase));
                bool hasRichart = distinctCardTypes.Any(c => c.Contains("Richart", StringComparison.OrdinalIgnoreCase));

                if (hasCube)
                {
                    var cubeData = PostgresRuleLoader.LoadDailySelections(pgConnStr, "bridge_cube_selections");
                    if (cubeData.Count > 0)
                    {
                        dailyStrategies.Add(new DailySelectionStrategy(cubeData, targetBankName: "cube", targetCardType: "Cube卡"));
                        channel.Writer.TryWrite($"data: ℹ️ 偵測到 Cube卡 交易，已載入國泰 CUBE 每日切換記錄 ({cubeData.Count} 筆)\n\n");
                    }
                }

                if (hasRichart)
                {
                    var richartData = PostgresRuleLoader.LoadDailySelections(pgConnStr, "bridge_richart_selections");
                    if (richartData.Count > 0)
                    {
                        dailyStrategies.Add(new DailySelectionStrategy(richartData, targetBankName: "taishin", targetCardType: "Richart卡"));
                        channel.Writer.TryWrite($"data: ℹ️ 偵測到 Richart卡 交易，已載入台新 Richart 每日切換記錄 ({richartData.Count} 筆)\n\n");
                    }
                }

                if (dailyStrategies.Count == 1)
                {
                    dailySelection = dailyStrategies[0];
                }
                else if (dailyStrategies.Count > 1)
                {
                    dailySelection = new CompositeDailySelectionStrategy(dailyStrategies);
                }

                // 5. 實例化全新回饋池引擎
                channel.Writer.TryWrite("data: ⚙️ 實例化全新回饋池計算引擎並執行計算...\n\n");
                var resolver = new RewardResolver(
                    programs: allPrograms,
                    pools: pools,
                    linkedLists: linkedLists,
                    dailySelection: dailySelection,
                    monthlySelection: null,
                    cycleTracker: cycleTracker);

                var resolvedItems = new List<(RewardTransaction Txn, ResolvedReward Result)>();
                var errorTransactions = new List<(RewardTransaction Txn, string Reason)>();

                foreach (var txn in transactions)
                {
                    try
                    {
                        var res = resolver.Resolve(txn);
                        resolvedItems.Add((txn, res));
                    }
                    catch (Exception ex)
                    {
                        // 異常/未支援類型（如 AGGREGATE、月結爭議等）：收集至 errorlog 並即時印出 Warning，不中斷整體計算
                        errorTransactions.Add((txn, ex.Message));
                        channel.Writer.TryWrite($"data: ⚠️ [Warning/跳過] {ex.Message}\n\n");
                        _logger.LogWarning(ex, "跳過交易 {TxnId}：{Reason}", txn.TransactionId, ex.Message);
                    }
                }

                var totalReward = resolvedItems.Sum(r => r.Result.TotalRewardAmount);
                channel.Writer.TryWrite($"data: ✅ 計算完成！共計算 {resolvedItems.Count} 筆，合計回饋金額 {totalReward:F2} 元\n\n");

                // 匯出回饋池套用明細 CSV 報表
                var outputDir = ResolvePath(section, "OutputPath", "output");
                ExportRewardAuditCsv(outputDir, resolvedItems, channel.Writer);

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

    private static void ExportRewardAuditCsv(
        string outputDir,
        List<(RewardTransaction Txn, ResolvedReward Result)> items,
        ChannelWriter<string?> writer)
    {
        Directory.CreateDirectory(outputDir);
        var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        var detailedPath = Path.Combine(outputDir, $"reward_calculation_detailed_{timestamp}.csv");
        var latestPath = Path.Combine(outputDir, "reward_calculation_detailed.csv");

        static string Esc(string? v) =>
            v is null ? "" :
            v.Contains(',') || v.Contains('"') || v.Contains('\n')
                ? $"\"{v.Replace("\"", "\"\"")}\""
                : v;

        var lines = new List<string>
        {
            "transaction_id,transaction_date,posting_date,bank_name,card_type,merchant_display,normalized_merchant,mobile_payment,payment_amount,reward_program,reward_type,reward_cycle,pool_id,pool_name,matched_rule_merchant,matched_rule_payment,effective_rate,calculated_reward,total_txn_reward,is_capped,cap_amount,stage_trace"
        };

        foreach (var (txn, res) in items)
        {
            var stageTraceText = res.StageTrace.Count > 0
                ? Esc(string.Join(" ➜ ", res.StageTrace))
                : "";

            if (res.AppliedPrograms.Count == 0)
            {
                lines.Add(string.Join(",",
                    Esc(txn.TransactionId),
                    Esc(txn.TransactionDate.ToString("yyyy-MM-dd")),
                    Esc(txn.PostingDate.ToString("yyyy-MM-dd")),
                    Esc(txn.BankName),
                    Esc(txn.CardType),
                    Esc(txn.MerchantDisplay),
                    Esc(txn.NormalizedMerchant),
                    Esc(txn.MobilePayment),
                    txn.Amount.ToString("F1"),
                    Esc("未匹配方案"),
                    "",
                    "",
                    "N/A",
                    Esc("無回饋池"),
                    "",
                    "",
                    "0.0000",
                    "0.00",
                    res.TotalRewardAmount.ToString("F2"),
                    "FALSE",
                    "",
                    stageTraceText));
            }
            else
            {
                foreach (var prog in res.AppliedPrograms)
                {
                    var matchedRuleMerchant = prog.MatchedRule?.MerchantDisplay != null
                        ? string.Join(";", prog.MatchedRule.MerchantDisplay)
                        : (prog.MatchedRule?.NormalizedMerchant != null ? string.Join(";", prog.MatchedRule.NormalizedMerchant) : "");

                    var matchedRulePayment = prog.MatchedRule?.PaymentProcess != null
                        ? string.Join(";", prog.MatchedRule.PaymentProcess)
                        : "";

                    lines.Add(string.Join(",",
                        Esc(txn.TransactionId),
                        Esc(txn.TransactionDate.ToString("yyyy-MM-dd")),
                        Esc(txn.PostingDate.ToString("yyyy-MM-dd")),
                        Esc(txn.BankName),
                        Esc(txn.CardType),
                        Esc(txn.MerchantDisplay),
                        Esc(txn.NormalizedMerchant),
                        Esc(txn.MobilePayment),
                        txn.Amount.ToString("F1"),
                        Esc(prog.Program.RewardProgram),
                        Esc(prog.Program.RewardType),
                        Esc(prog.Program.RewardCycle),
                        Esc(prog.MatchedPool?.MerchantRewardPoolsId ?? "BASE_PROGRAM"),
                        Esc(prog.MatchedPool?.PoolName ?? "全通路基礎方案"),
                        Esc(matchedRuleMerchant),
                        Esc(matchedRulePayment),
                        prog.EffectiveRate.ToString("F4"),
                        prog.CalculatedRewardAmount.ToString("F2"),
                        res.TotalRewardAmount.ToString("F2"),
                        prog.IsCapped ? "TRUE" : "FALSE",
                        prog.Program.CapAmount.HasValue ? prog.Program.CapAmount.Value.ToString("F0") : "",
                        stageTraceText));
                }
            }
        }

        File.WriteAllLines(detailedPath, lines, System.Text.Encoding.UTF8);
        File.WriteAllLines(latestPath, lines, System.Text.Encoding.UTF8);
        writer.TryWrite($"data: 📊 回饋池套用明細報表已輸出至：{Path.GetFileName(detailedPath)}\n\n");
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
