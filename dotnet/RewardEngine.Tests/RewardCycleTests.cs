using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using RewardEngine.Tests.Fixtures;
using Xunit;

namespace RewardEngine.Tests;

public class RewardCycleTests
{
    [Fact]
    public void C01_BILLING_CYCLE_依據PostingDate劃分帳單期並按CapAmount截斷()
    {
        // 1. Arrange: 設定 BillingHistory
        var billingRecords = new List<BillingHistoryRecord>
        {
            new() { BankName = "esun", CardType = "U Bear卡", StatementMonth = "2025-01", ClosingDate = new DateOnly(2025, 2, 7), ActualClosingDate = new DateOnly(2025, 2, 7) }
        };
        var billingResolver = new BillingCycleResolver(billingRecords);
        var tracker = new RewardCycleTracker(billingResolver);

        // 設定上限 CapAmount = 150m 的 Campaign
        var campaign = ScenarioBuilder.CampaignProgram("U Bear卡網購", 0.05m, bankName: "esun", cardType: "U Bear卡") with
        {
            RewardCycle = "BILLING_CYCLE",
            CapAmount = 150m
        };

        var programs = new List<CardRewardProgram> { campaign };
        var bridgeRules = new List<RewardBridgeRule>();
        var resolver = new RewardResolver(programs, bridgeRules, cycleTracker: tracker);

        // 交易 1: 金額 2000m * 5% = 100m (未達上限 150m)
        var txn1 = ScenarioBuilder.Transaction("T01", new DateOnly(2025, 1, 15), 2000m,
            bankName: "esun", cardType: "U Bear卡", postingDate: new DateOnly(2025, 1, 16));
        var res1 = resolver.Resolve(txn1);
        Assert.Equal(100m, res1.TotalRewardAmount);
        Assert.False(res1.AppliedPrograms[0].IsCapped);

        // 交易 2: 金額 2000m * 5% = 100m (已累計 100m，加 100m 超過 150m，截斷給 50m)
        var txn2 = ScenarioBuilder.Transaction("T02", new DateOnly(2025, 1, 20), 2000m,
            bankName: "esun", cardType: "U Bear卡", postingDate: new DateOnly(2025, 1, 21));
        var res2 = resolver.Resolve(txn2);
        Assert.Equal(50m, res2.TotalRewardAmount);
        Assert.True(res2.AppliedPrograms[0].IsCapped);

        // 交易 3: 已達 150m 上限，額度歸零
        var txn3 = ScenarioBuilder.Transaction("T03", new DateOnly(2025, 1, 25), 1000m,
            bankName: "esun", cardType: "U Bear卡", postingDate: new DateOnly(2025, 1, 26));
        var res3 = resolver.Resolve(txn3);
        Assert.Equal(0m, res3.TotalRewardAmount);
        Assert.True(res3.AppliedPrograms[0].IsCapped);
    }

    [Fact]
    public void C02_CALENDAR_MONTH_依據TransactionDate日曆月截斷()
    {
        var tracker = new RewardCycleTracker();
        var campaign = ScenarioBuilder.CampaignProgram("月加碼", 0.10m, bankName: "TestBank", cardType: "TestCard") with
        {
            RewardCycle = "CALENDAR_MONTH",
            CapAmount = 100m
        };

        var resolver = new RewardResolver([campaign], [], cycleTracker: tracker);

        // 5/10 刷 800m * 10% = 80m
        var txn1 = ScenarioBuilder.Transaction("T1", new DateOnly(2026, 5, 10), 800m);
        var res1 = resolver.Resolve(txn1);
        Assert.Equal(80m, res1.TotalRewardAmount);

        // 5/20 刷 500m * 10% = 50m (截斷為 20m)
        var txn2 = ScenarioBuilder.Transaction("T2", new DateOnly(2026, 5, 20), 500m);
        var res2 = resolver.Resolve(txn2);
        Assert.Equal(20m, res2.TotalRewardAmount);

        // 6/01 進入下一個日曆月，額度重新計算
        var txn3 = ScenarioBuilder.Transaction("T3", new DateOnly(2026, 6, 1), 500m);
        var res3 = resolver.Resolve(txn3);
        Assert.Equal(50m, res3.TotalRewardAmount);
    }
}
