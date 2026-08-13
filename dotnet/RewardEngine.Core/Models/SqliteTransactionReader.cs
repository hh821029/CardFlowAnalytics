using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 交易資料讀取器 (向後相容包裝，已過渡至 PostgreSQL Npgsql)
/// </summary>
public static class SqliteTransactionReader
{
    public static List<RewardTransaction> Load(
        string dbPathOrConnStr,
        string? bankName = null,
        string? cardType = null,
        DateOnly? from = null,
        DateOnly? to = null,
        IEnumerable<string>? excludeTypes = null)
    {
        string connStr = (dbPathOrConnStr.Contains('=') || dbPathOrConnStr.StartsWith("postgresql://", StringComparison.OrdinalIgnoreCase))
            ? dbPathOrConnStr
            : GetPostgresConnectionStringFromEnv();

        return PostgresTransactionReader.Load(connStr, bankName, cardType, from, to, excludeTypes);
    }

    public static string GetPostgresConnectionStringFromEnv()
    {
        var host = Environment.GetEnvironmentVariable("PG_HOST") ?? Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "127.0.0.1";
        var port = Environment.GetEnvironmentVariable("PG_PORT") ?? Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";
        var user = Environment.GetEnvironmentVariable("PG_USER") ?? Environment.GetEnvironmentVariable("POSTGRES_USER") ?? "postgres";
        var pass = Environment.GetEnvironmentVariable("PG_PASSWORD") ?? Environment.GetEnvironmentVariable("POSTGRES_PASSWORD") ?? "postgres";
        var db   = Environment.GetEnvironmentVariable("PG_DATABASE") ?? Environment.GetEnvironmentVariable("POSTGRES_DB") ?? "credit_card_db";

        return $"Host={host};Port={port};Database={db};Username={user};Password={pass}";
    }
}
