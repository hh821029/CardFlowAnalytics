using RewardEngine.Core.Loaders;
using Xunit;

namespace RewardEngine.Tests;

public class PostgresTransactionReaderTests
{
    [Fact]
    public void ConnectionStringHelper_GeneratesValidDefaultPostgresConnectionString()
    {
        var connStr = SqliteTransactionReader.GetPostgresConnectionStringFromEnv();
        Assert.Contains("Host=", connStr);
        Assert.Contains("Database=", connStr);
        Assert.Contains("Username=", connStr);
    }
}
