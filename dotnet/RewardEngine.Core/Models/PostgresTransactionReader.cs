using Dapper;
using Npgsql;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 從 PostgreSQL (credit_card_db) 的 all_transactions 資料表讀取交易資料，轉換為 RewardTransaction 物件
/// </summary>
public static class PostgresTransactionReader
{
    private const string TableName = "rewards_transactions";

    /// <summary>
    /// 讀取所有符合條件的交易，供回饋計算引擎使用。
    /// 排除繳款、紅利折抵、各項費用等非消費性交易。
    /// </summary>
    /// <param name="connectionString">PostgreSQL 連線字串</param>
    /// <param name="bankName">指定銀行（null = 所有銀行）</param>
    /// <param name="cardType">指定卡別（null = 所有卡別）</param>
    /// <param name="from">起始交易日（含）</param>
    /// <param name="to">結束交易日（含）</param>
    /// <param name="excludeTypes">排除的交易類型（預設排除繳款/折抵/費用）</param>
    public static List<RewardTransaction> Load(
        string connectionString,
        string? bankName = null,
        string? cardType = null,
        DateOnly? from = null,
        DateOnly? to = null,
        IEnumerable<string>? excludeTypes = null)
    {
        var excluded = excludeTypes ?? ["繳款", "紅利折抵", "各項費用"];

        var conditions = new List<string>();
        var parameters = new DynamicParameters();

        var excludedList = excluded.ToList();
        if (excludedList.Count > 0)
        {
            var placeholders = string.Join(", ", excludedList.Select((_, i) => $"@excl{i}"));
            conditions.Add($"transaction_type NOT IN ({placeholders})");
            for (int i = 0; i < excludedList.Count; i++)
                parameters.Add($"excl{i}", excludedList[i]);
        }

        if (bankName is not null)
        {
            conditions.Add("bank_name = @bankName");
            parameters.Add("bankName", bankName);
        }
        if (cardType is not null)
        {
            conditions.Add("card_type = @cardType");
            parameters.Add("cardType", cardType);
        }
        if (from is not null)
        {
            conditions.Add("transaction_date >= @from");
            parameters.Add("from", from.Value.ToString("yyyy-MM-dd"));
        }
        if (to is not null)
        {
            conditions.Add("transaction_date <= @to");
            parameters.Add("to", to.Value.ToString("yyyy-MM-dd"));
        }

        var whereClause = conditions.Count > 0
            ? "WHERE " + string.Join(" AND ", conditions)
            : string.Empty;

        var sql = $"""
            SELECT *
            FROM {TableName}
            {whereClause}
            ORDER BY transaction_date, transaction_id
            """;

        try
        {
            using var conn = new NpgsqlConnection(connectionString);
            var rows = conn.Query(sql, parameters);
            return rows.Select(r => ToTransaction((IDictionary<string, object>)r)).ToList();
        }
        catch (PostgresException ex) when (ex.SqlState == "42P01")
        {
            throw new InvalidOperationException($"❌ 資料庫中尚未建立視圖 [{TableName}]。請先在 Web 控制台或 CLI 執行「🚀 產生帳單資料庫 (ETL)」載入帳單資料！", ex);
        }
    }

    private static object? GetVal(IDictionary<string, object> dict, string key)
    {
        foreach (var kvp in dict)
        {
            if (string.Equals(kvp.Key, key, StringComparison.OrdinalIgnoreCase))
                return kvp.Value;
        }
        return null;
    }

    private static RewardTransaction ToTransaction(IDictionary<string, object> r)
    {
        DateOnly ParseDate(object? d)
        {
            if (d is null || d == DBNull.Value) return DateOnly.MinValue;
            if (d is DateTime dt) return DateOnly.FromDateTime(dt);
            if (d is DateOnly doVal) return doVal;
            var str = d.ToString()!.Split(' ')[0];
            return DateOnly.TryParse(str, out var parsed) ? parsed : DateOnly.MinValue;
        }

        var amtObj = GetVal(r, "payment_amount") ?? GetVal(r, "amount") ?? 0m;
        decimal.TryParse(amtObj.ToString(), out var amt);

        var merch = GetVal(r, "merchant") ?? GetVal(r, "merchant_name");
        var merchDisp = GetVal(r, "merchant_display") ?? merch;
        var normMerch = GetVal(r, "normalized_merchant") ?? merchDisp;

        return new RewardTransaction
        {
            TransactionId    = GetVal(r, "transaction_id")?.ToString() ?? "",
            BankName         = GetVal(r, "bank_name")?.ToString() ?? "",
            CardType         = GetVal(r, "card_type")?.ToString() ?? "",
            CardNo           = GetVal(r, "card_no")?.ToString() ?? "",
            VpcType          = GetVal(r, "vpc_type")?.ToString(),
            TransactionDate  = ParseDate(GetVal(r, "transaction_date")),
            PostingDate      = ParseDate(GetVal(r, "posting_date")),
            Amount           = amt,
            TransactionType  = GetVal(r, "transaction_type")?.ToString(),
            MobilePayment    = (GetVal(r, "payment_process") ?? GetVal(r, "mobile_payment"))?.ToString(),
            EcPlatform       = GetVal(r, "ec_platform")?.ToString(),
            Merchant         = merch?.ToString(),
            MerchantDisplay  = merchDisp?.ToString(),
            NormalizedMerchant = normMerch?.ToString(),
            MerchantLocation = (GetVal(r, "merchant_location") ?? GetVal(r, "location"))?.ToString()
        };
    }
    
    public static string GetPostgresConnectionString()
    {
        var host = Environment.GetEnvironmentVariable("PG_HOST") ?? Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "127.0.0.1";
        var port = Environment.GetEnvironmentVariable("PG_PORT") ?? Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";
        var user = Environment.GetEnvironmentVariable("PG_USER") ?? Environment.GetEnvironmentVariable("POSTGRES_USER") ?? "postgres";
        var pass = Environment.GetEnvironmentVariable("PG_PASSWORD") ?? Environment.GetEnvironmentVariable("POSTGRES_PASSWORD") ?? "postgres";
        var db   = Environment.GetEnvironmentVariable("PG_DATABASE") ?? Environment.GetEnvironmentVariable("POSTGRES_DB") ?? "credit_card_db";

        return $"Host={host};Port={port};Database={db};Username={user};Password={pass}";
    }
}
