using Dapper;
using Npgsql;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 從 PostgreSQL 集中資料庫 (credit_card_db) 載入維度與回饋規則資料表
/// </summary>
public static class PostgresRuleLoader
{
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
        var sql = """
            SELECT 
                bank_name, card_type, base_reward_program, 
                base_reward_rate, reward_cycle, min_single_transaction, cap_amount, 
                start_date, end_date, reward_type, calc_method, round_strategy
            FROM dim_card_rewards_base
            """;

        var rows = conn.Query(sql);
        var list = new List<CardRewardProgram>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var rr = GetVal(row, "base_reward_rate");
            var mst = GetVal(row, "min_single_transaction");
            var ca = GetVal(row, "cap_amount");

            list.Add(new CardRewardProgram
            {
                BankName = GetVal(row, "bank_name")?.ToString() ?? "",
                CardType = GetVal(row, "card_type")?.ToString() ?? "",
                IsCurrentBenefit = GetVal(row, "is_current_benefit") != null ? ParseBool(GetVal(row, "is_current_benefit")) : true,
                RewardProgram = GetVal(row, "base_reward_program")?.ToString() ?? "",
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
        var sql = """
            SELECT 
                bank_name, card_type, campaign_reward_program, 
                campaign_reward_rate, reward_cycle, min_single_transaction, cap_amount, 
                start_date, end_date, reward_type, calc_method, round_strategy
            FROM dim_card_rewards_campaigns
            """;

        var rows = conn.Query(sql);
        var list = new List<CardRewardProgram>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var rr = GetVal(row, "campaign_reward_rate");
            var mst = GetVal(row, "min_single_transaction");
            var ca = GetVal(row, "cap_amount");

            list.Add(new CardRewardProgram
            {
                BankName = GetVal(row, "bank_name")?.ToString() ?? "",
                CardType = GetVal(row, "card_type")?.ToString() ?? "",
                IsCurrentBenefit = GetVal(row, "is_current_benefit") != null ? ParseBool(GetVal(row, "is_current_benefit")) : true,
                RewardProgram = GetVal(row, "campaign_reward_program")?.ToString() ?? "",
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

    public static List<RewardBridgeRule> LoadBridgeRules(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = """
            SELECT 
                rules_reward_program, vpc_type, payment_process, ec_platform, 
                merchant_display, merchant_location, start_date, end_date, 
                merchant_rate, priority, reward_cal_break
            FROM bridge_reward_rules
            ORDER BY priority ASC
            """;

        var rows = conn.Query(sql);
        var list = new List<RewardBridgeRule>();

        foreach (var r in rows)
        {
            var row = (IDictionary<string, object>)r;
            var mr = GetVal(row, "merchant_rate");
            var pr = GetVal(row, "priority");

            list.Add(new RewardBridgeRule
            {
                RulesRewardProgram = GetVal(row, "rules_reward_program")?.ToString() ?? "",
                VpcType = GetVal(row, "vpc_type")?.ToString(),
                MobilePayment = GetVal(row, "payment_process")?.ToString(),
                EcPlatform = GetVal(row, "ec_platform")?.ToString(),
                MerchantDisplay = GetVal(row, "merchant_display")?.ToString(),
                MerchantLocation = GetVal(row, "merchant_location")?.ToString(),
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
        var sql = """
            SELECT base_reward_program, start_date, end_date, remark
            FROM bridge_cube_selections
            """;

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
                    BaseRewardProgram = GetVal(row, "base_reward_program")?.ToString() ?? "",
                    StartDate = sDate.Value,
                    EndDate = eDate.Value,
                    Note = GetVal(row, "remark")?.ToString()
                });
            }
        }
        return list;
    }

    public static List<MonthlyBenefitSelection> LoadMonthlySelections(string connectionString)
    {
        using var conn = new NpgsqlConnection(connectionString);
        var sql = """
            SELECT rules_reward_program, campaign_reward_program, start_date, end_date, max_posting_date
            FROM bridge_unicard_selections
            """;

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
                    RulesRewardProgram = GetVal(row, "rules_reward_program")?.ToString() ?? "",
                    CampaignRewardProgram = GetVal(row, "campaign_reward_program")?.ToString() ?? "",
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
        var sql = """
            SELECT bank_name, card_type, statement_month, closing_date, actual_closing_date
            FROM dim_billing_history
            """;

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
