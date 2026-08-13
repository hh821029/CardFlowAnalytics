using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using Xunit;

namespace RewardEngine.Tests;

public class BillingCycleTests
{
    [Fact]
    public void B01_正確計算區間並按交易日期解析對應帳單月()
    {
        var records = new List<BillingHistoryRecord>
        {
            new() { BankName = "esun", CardType = "", StatementMonth = "2025-01", ClosingDate = new DateOnly(2025, 2, 7), ActualClosingDate = new DateOnly(2025, 2, 7) },
            new() { BankName = "esun", CardType = "", StatementMonth = "2025-02", ClosingDate = new DateOnly(2025, 3, 5), ActualClosingDate = new DateOnly(2025, 3, 5) }
        };

        var resolver = new BillingCycleResolver(records);

        // 2025-02-07 當天屬於 2025-01 帳單期
        var intervalJan = resolver.ResolveInterval("esun", "Unicard", new DateOnly(2025, 2, 7));
        Assert.NotNull(intervalJan);
        Assert.Equal("2025-01", intervalJan.StatementMonth);
        Assert.Equal(new DateOnly(2025, 2, 7), intervalJan.IntervalEnd);

        // 2025-02-08 屬於 2025-02 帳單期 (2025-02-08 ~ 2025-03-05)
        var intervalFeb = resolver.ResolveInterval("esun", "Unicard", new DateOnly(2025, 2, 8));
        Assert.NotNull(intervalFeb);
        Assert.Equal("2025-02", intervalFeb.StatementMonth);
        Assert.Equal(new DateOnly(2025, 2, 8), intervalFeb.IntervalStart);
    }
}
