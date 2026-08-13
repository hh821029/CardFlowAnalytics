using Dapper;
using Npgsql;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 從 PostgreSQL (credit_card_db) 的 all_transactions 資料表讀取交易資料，轉換為 RewardTransaction 物件
/// </summary>
public static class PostgresTransactionReader
{
    private const string TableName = "vw_transactions_enriched";

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
            SELECT
                transaction_id    AS {nameof(RawRow.transaction_id)},
                bank_name         AS {nameof(RawRow.bank_name)},
                card_type         AS {nameof(RawRow.card_type)},
                card_no           AS {nameof(RawRow.card_no)},
                vpc_type          AS {nameof(RawRow.vpc_type)},
                transaction_date  AS {nameof(RawRow.transaction_date)},
                posting_date      AS {nameof(RawRow.posting_date)},
                payment_amount    AS {nameof(RawRow.payment_amount)},
                transaction_type  AS {nameof(RawRow.transaction_type)},
                payment_process   AS {nameof(RawRow.payment_process)},
                ec_platform       AS {nameof(RawRow.ec_platform)},
                merchant_display  AS {nameof(RawRow.merchant_display)},
                merchant_location AS {nameof(RawRow.merchant_location)}
            FROM {TableName}
            {whereClause}
            ORDER BY transaction_date, transaction_id
            """;

        try
        {
            using var conn = new NpgsqlConnection(connectionString);
            var rows = conn.Query<RawRow>(sql, parameters);
            return rows.Select(ToTransaction).ToList();
        }
        catch (PostgresException ex) when (ex.SqlState == "42P01")
        {
            throw new InvalidOperationException("❌ 資料庫中尚未建立視圖 [vw_transactions_enriched]。請先在 Web 控制台或 CLI 執行「🚀 產生帳單資料庫 (ETL)」載入帳單資料！", ex);
        }
    }

    private sealed class RawRow
    {
        public string transaction_id { get; init; } = "";
        public string bank_name { get; init; } = "";
        public string card_type { get; init; } = "";
        public string card_no { get; init; } = "";
        public string? vpc_type { get; init; }
        public object transaction_date { get; init; } = "";
        public object posting_date { get; init; } = "";
        public decimal payment_amount { get; init; }
        public string? transaction_type { get; init; }
        public string? payment_process { get; init; }
        public string? ec_platform { get; init; }
        public string? merchant_display { get; init; }
        public string? merchant_location { get; init; }
    }

    private static RewardTransaction ToTransaction(RawRow r)
    {
        DateOnly ParseDate(object? d)
        {
            if (d is null) return DateOnly.MinValue;
            if (d is DateTime dt) return DateOnly.FromDateTime(dt);
            if (d is DateOnly doVal) return doVal;
            var str = d.ToString()!.Split(' ')[0];
            return DateOnly.TryParse(str, out var parsed) ? parsed : DateOnly.MinValue;
        }

        return new RewardTransaction
        {
            TransactionId    = r.transaction_id,
            BankName         = r.bank_name,
            CardType         = r.card_type,
            CardNo           = r.card_no,
            VpcType          = r.vpc_type,
            TransactionDate  = ParseDate(r.transaction_date),
            PostingDate      = ParseDate(r.posting_date),
            Amount           = r.payment_amount,
            TransactionType  = r.transaction_type,
            MobilePayment    = r.payment_process,
            EcPlatform       = r.ec_platform,
            MerchantDisplay  = r.merchant_display,
            MerchantLocation = r.merchant_location
        };
    }
}
