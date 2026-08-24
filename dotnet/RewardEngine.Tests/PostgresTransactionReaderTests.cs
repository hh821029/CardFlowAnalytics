using RewardEngine.Core.Loaders;
using RewardEngine.Core.Models;
using Xunit;

namespace RewardEngine.Tests;

public class PostgresTransactionReaderTests
{
    [Fact]
    public void ConnectionStringHelper_GeneratesValidDefaultPostgresConnectionString()
    {
        var connStr = PostgresTransactionReader.GetPostgresConnectionString();
        Assert.Contains("Host=", connStr);
        Assert.Contains("Database=", connStr);
        Assert.Contains("Username=", connStr);
    }
}
