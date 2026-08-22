using System.Text.Json;
using System.Text.Json.Serialization;
using Dapper;
using Npgsql;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 從 PostgreSQL 集中資料庫 (credit_card_db) 載入維度與回饋規則資料表
/// </summary>
public static class PostgresRuleLoader
{
    private static readonly JsonSerializerOptions DefaultJsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        NumberHandling = JsonNumberHandling.AllowReadingFromString
    };

    private static object? GetVal(IDictionary<string, object> dict, string key)
    {
        foreach (var kvp in dict)
        {
            if (string.Equals(kvp.Key, key, StringComparison.OrdinalIgnoreCase))
                return kvp.Value;
        }
        return null;
    }

    private static DateOnly? ParseDateOnly(object? val)
    {
        if (val is null || val == DBNull.Value) return null;
        if (val is DateTime dt) return DateOnly.FromDateTime(dt);
        if (val is DateOnly doVal) return doVal;
        var s = val.ToString()!.Trim();
        if (string.IsNullOrEmpty(s)) return null;
        var datePart = s.Split(' ')[0];
        return DateOnly.TryParse(datePart, out var d) ? d : null;
    }

    private static bool ParseBool(object? val)
    {
        if (val is null || val == DBNull.Value) return false;
        if (val is bool b) return b;
        var s = val.ToString()!.Trim().ToLower();
        return s is "true" or "1" or "t" or "y" or "yes";
    }

    public static List<CardRewardProgram> LoadBasePrograms(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM dim_card_rewards_base";

        var rows = conn.Query(sql);
        var list = new List<CardRewardProgram>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var rewardId = (GetVal(row, "base_reward_id") ?? GetVal(row, "reward_id"))?.ToString() ?? "";
            var cardId = GetVal(row, "card_id")?.ToString() ?? "";
            var bankNo = GetVal(row, "bank_no")?.ToString() ?? "";
            var priorityVal = GetVal(row, "priority") ?? GetVal(row, "base_priority");
            var rr = GetVal(row, "base_reward_rate") ?? GetVal(row, "reward_rate");
            var mst = GetVal(row, "min_single_transaction");
            var ca = GetVal(row, "cap_amount");

            list.Add(new CardRewardProgram
            {
                RewardId = rewardId,
                BankNo = bankNo,
                BankName = GetVal(row, "bank_name")?.ToString() ?? "",
                CardId = cardId,
                CardType = GetVal(row, "card_type")?.ToString() ?? "",
                Priority = priorityVal != null && int.TryParse(priorityVal.ToString(), out var p) ? p : 999,
                RewardCalBreak = ParseBool(GetVal(row, "reward_cal_break") ?? GetVal(row, "base_reward_cal_break")),
                RewardProgram = (GetVal(row, "base_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                Source = RewardProgramSource.Base,
                RewardRate = rr != null && decimal.TryParse(rr.ToString(), out var rate) ? rate : null,
                RewardCycle = GetVal(row, "reward_cycle")?.ToString(),
                MinSingleTransaction = mst != null && decimal.TryParse(mst.ToString(), out var minTxn) ? minTxn : null,
                CapAmount = ca != null && decimal.TryParse(ca.ToString(), out var cap) ? cap : null,
                StartDate = ParseDateOnly(GetVal(row, "start_date")),
                EndDate = ParseDateOnly(GetVal(row, "end_date")),
                MaxPostingDate = ParseDateOnly(GetVal(row, "max_posting_date")),
                RewardType = GetVal(row, "reward_type")?.ToString(),
                CalcMethod = GetVal(row, "calc_method")?.ToString(),
                RoundStrategy = GetVal(row, "round_strategy")?.ToString()
            });
        }
        return list;
    }

    public static List<CardRewardProgram> LoadCampaignsPrograms(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM dim_card_rewards_campaigns";

        var rows = conn.Query(sql);
        var list = new List<CardRewardProgram>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var rewardId = (GetVal(row, "campaigns_reward_id") ?? GetVal(row, "campaign_reward_id") ?? GetVal(row, "reward_id"))?.ToString() ?? "";
            var cardId = GetVal(row, "card_id")?.ToString() ?? "";
            var bankNo = GetVal(row, "bank_no")?.ToString() ?? "";
            var priorityVal = GetVal(row, "priority") ?? GetVal(row, "campaign_priority");
            var rr = GetVal(row, "campaign_reward_rate") ?? GetVal(row, "reward_rate");
            var mst = GetVal(row, "min_single_transaction");
            var ca = GetVal(row, "cap_amount");

            list.Add(new CardRewardProgram
            {
                RewardId = rewardId,
                BankNo = bankNo,
                BankName = GetVal(row, "bank_name")?.ToString() ?? "",
                CardId = cardId,
                CardType = GetVal(row, "card_type")?.ToString() ?? "",
                Priority = priorityVal != null && int.TryParse(priorityVal.ToString(), out var p) ? p : 999,
                RewardCalBreak = ParseBool(GetVal(row, "reward_cal_break") ?? GetVal(row, "campaign_reward_cal_break")),
                RewardProgram = (GetVal(row, "campaign_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                Source = RewardProgramSource.Campaign,
                RewardRate = rr != null && decimal.TryParse(rr.ToString(), out var rate) ? rate : null,
                RewardCycle = GetVal(row, "reward_cycle")?.ToString(),
                MinSingleTransaction = mst != null && decimal.TryParse(mst.ToString(), out var minTxn) ? minTxn : null,
                CapAmount = ca != null && decimal.TryParse(ca.ToString(), out var cap) ? cap : null,
                StartDate = ParseDateOnly(GetVal(row, "start_date")),
                EndDate = ParseDateOnly(GetVal(row, "end_date")),
                MaxPostingDate = ParseDateOnly(GetVal(row, "max_posting_date")),
                RewardType = GetVal(row, "reward_type")?.ToString(),
                CalcMethod = GetVal(row, "calc_method")?.ToString(),
                RoundStrategy = GetVal(row, "round_strategy")?.ToString()
            });
        }
        return list;
    }

    /// <summary>
    /// 從 bridge_reward_linked_lists 資料表載入方案與特店回饋池之多對多關聯
    /// </summary>
    public static List<RewardLinkedList> LoadRewardLinkedLists(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT reward_id, merchant_reward_pools_id FROM bridge_reward_linked_lists";

        var rows = conn.Query(sql);
        var list = new List<RewardLinkedList>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var rewardId = GetVal(row, "reward_id")?.ToString()?.Trim();
            var poolId = GetVal(row, "merchant_reward_pools_id")?.ToString()?.Trim();

            if (!string.IsNullOrEmpty(rewardId) && !string.IsNullOrEmpty(poolId))
            {
                list.Add(new RewardLinkedList
                {
                    RewardId = rewardId,
                    MerchantRewardPoolsId = poolId
                });
            }
        }
        return list;
    }

    /// <summary>
    /// 從 bridge_reward_pools 資料表載入特店回饋池，並將 JSONB 欄位反序列化為強型別物件
    /// </summary>
    public static List<MerchantRewardPool> LoadRewardPools(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT merchant_reward_pools_id, pool_name, pass_rules, rules FROM bridge_reward_pools";

        var rows = conn.Query(sql);
        var list = new List<MerchantRewardPool>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var poolId = GetVal(row, "merchant_reward_pools_id")?.ToString()?.Trim() ?? "";
            var poolName = GetVal(row, "pool_name")?.ToString()?.Trim() ?? "";

            var passRulesObj = GetVal(row, "pass_rules");
            var rulesObj = GetVal(row, "rules");

            MerchantRewardRule[] passRules = [];
            MerchantRewardRule[] rules = [];

            if (passRulesObj != null)
            {
                var passJson = passRulesObj is string s ? s : passRulesObj.ToString();
                if (!string.IsNullOrWhiteSpace(passJson))
                {
                    passRules = JsonSerializer.Deserialize<MerchantRewardRule[]>(passJson, DefaultJsonOptions) ?? [];
                }
            }

            if (rulesObj != null)
            {
                var rulesJson = rulesObj is string s ? s : rulesObj.ToString();
                if (!string.IsNullOrWhiteSpace(rulesJson))
                {
                    rules = JsonSerializer.Deserialize<MerchantRewardRule[]>(rulesJson, DefaultJsonOptions) ?? [];
                }
            }

            list.Add(new MerchantRewardPool
            {
                MerchantRewardPoolsId = poolId,
                PoolName = poolName,
                PassRules = passRules,
                Rules = rules
            });
        }
        return list;
    }

    public static List<RewardBridgeRule> LoadBridgeRules(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM bridge_reward_rules ORDER BY priority ASC";

        var rows = conn.Query(sql);
        var list = new List<RewardBridgeRule>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var mr = GetVal(row, "merchant_rate");
            var pr = GetVal(row, "priority");
            var merchVal = GetVal(row, "merchant_display") ?? GetVal(row, "normalized_merchant") ?? GetVal(row, "merchant");

            list.Add(new RewardBridgeRule
            {
                RulesRewardProgram = (GetVal(row, "rules_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                VpcType = GetVal(row, "vpc_type")?.ToString(),
                MobilePayment = (GetVal(row, "payment_process") ?? GetVal(row, "mobile_payment"))?.ToString(),
                EcPlatform = GetVal(row, "ec_platform")?.ToString(),
                NormalizedMerchant = GetVal(row, "normalized_merchant")?.ToString(),
                MerchantDisplay = merchVal?.ToString(),
                MerchantLocation = (GetVal(row, "merchant_location") ?? GetVal(row, "location"))?.ToString(),
                StartDate = ParseDateOnly(GetVal(row, "start_date")),
                EndDate = ParseDateOnly(GetVal(row, "end_date")),
                MerchantRate = mr != null && decimal.TryParse(mr.ToString(), out var rate) ? rate : null,
                Priority = pr != null && int.TryParse(pr.ToString(), out var pVal) ? pVal : 999,
                RewardCalBreak = ParseBool(GetVal(row, "reward_cal_break"))
            });
        }
        return list;
    }

    public static List<DailyBenefitSelection> LoadDailySelections(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM bridge_cube_selections";

        var rows = conn.Query(sql);
        var list = new List<DailyBenefitSelection>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var sDate = ParseDateOnly(GetVal(row, "start_date"));
            var eDate = ParseDateOnly(GetVal(row, "end_date"));
            if (sDate.HasValue && eDate.HasValue)
            {
                list.Add(new DailyBenefitSelection
                {
                    BaseRewardProgram = (GetVal(row, "base_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                    StartDate = sDate.Value,
                    EndDate = eDate.Value,
                    Note = (GetVal(row, "remark") ?? GetVal(row, "note"))?.ToString()
                });
            }
        }
        return list;
    }

    public static List<MonthlyBenefitSelection> LoadMonthlySelections(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM bridge_unicard_selections";

        var rows = conn.Query(sql);
        var list = new List<MonthlyBenefitSelection>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var sDate = ParseDateOnly(GetVal(row, "start_date"));
            var eDate = ParseDateOnly(GetVal(row, "end_date"));
            var mDate = ParseDateOnly(GetVal(row, "max_posting_date"));
            if (sDate.HasValue && eDate.HasValue && mDate.HasValue)
            {
                list.Add(new MonthlyBenefitSelection
                {
                    RulesRewardProgram = (GetVal(row, "rules_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                    CampaignRewardProgram = (GetVal(row, "campaign_reward_program") ?? GetVal(row, "reward_program"))?.ToString() ?? "",
                    StartDate = sDate.Value,
                    EndDate = eDate.Value,
                    MaxPostingDate = mDate.Value
                });
            }
        }
        return list;
    }

    public static List<BillingHistoryRecord> LoadBillingHistory(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = "SELECT * FROM dim_billing_history";

        var rows = conn.Query(sql);
        var list = new List<BillingHistoryRecord>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            list.Add(new BillingHistoryRecord
            {
                BankName = GetVal(row, "bank_name")?.ToString() ?? "",
                CardType = GetVal(row, "card_type")?.ToString(),
                StatementMonth = GetVal(row, "statement_month")?.ToString() ?? "",
                ClosingDate = ParseDateOnly(GetVal(row, "closing_date")),
                ActualClosingDate = ParseDateOnly(GetVal(row, "actual_closing_date"))
            });
        }
        return list;
    }
}
