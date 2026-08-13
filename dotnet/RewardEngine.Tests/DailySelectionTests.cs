using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using RewardEngine.Tests.Fixtures;
using Xunit;

public class DailySelectionTests
{
    [Fact]
    public void D01_一般交易在Selection中央_正確命中不觸發人工確認()
    {
        // 情境：正常交易（非跨境、非行動支付），消費日在 selection 中間
        // 預期：正確命中 program，RequiresManualVerification = false
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D01", new DateOnly(2026, 5, 15), 500m);
        // transactionType 預設 "交易"，IsCrossBorder = false, IsMobilePayment = false
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Equal("PROGRAM_A", result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);
    }

    [Fact]
    public void D02_消費日不在Selection區間_回傳null()
    {
        // 情境：消費日 6/15，selection 只到 5/31
        // 預期：ResolvedProgram = null，不需人工確認
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D02", new DateOnly(2026, 6, 15), 500m);
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Null(result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);

    }

    [Fact]
    public void D03_跨境交易距邊界零天_觸發人工確認()
    {
        // 情境：跨境交易，消費日 5/31（= EndDate），距離邊界 0 天（≤ 1）
        // 預期：命中 program，RequiresManualVerification = true
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D03", new DateOnly(2026, 5, 31), 500m,
            transactionType: "一般國外交易");  // IsCrossBorder = true
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Equal("PROGRAM_A", result.ResolvedProgram);
        Assert.True(result.RequiresManualVerification);
        Assert.Contains("跨境", result.VerificationReason);
    
    }

    [Fact]
    public void D04_跨境交易_消費日距離邊界兩天_超出緩衝一天_不觸發()
    {
        // 情境：跨境交易，消費日 5/29，距離 EndDate(5/31) = 2 天 > CrossBorderBufferDays(1)
        // 預期：命中 program，RequiresManualVerification = false
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D04", new DateOnly(2026, 5, 29), 500m,
            transactionType: "一般國外交易");
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Equal("PROGRAM_A", result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);
    
    }

    [Fact]
    public void D05_行動支付_消費日距離邊界兩天_在緩衝內_觸發人工確認()
    {
        // 情境：行動支付，消費日 5/29，距離 EndDate(5/31) = 2 天 ≤ MobilePaymentBufferDays(2)
        // 預期：命中 program，RequiresManualVerification = true
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D05", new DateOnly(2026, 5, 29), 500m,
            mobilePayment: "全支付");  // IsMobilePayment = true

        var result = strategy.ResolveActiveProgram(txn);

        Assert.Equal("PROGRAM_A", result.ResolvedProgram);
        Assert.True(result.RequiresManualVerification);
        Assert.Contains("行動支付", result.VerificationReason);    
    }

    [Fact]
    public void D06_行動支付_消費日距離邊界三天_超出緩衝一天_不觸發()
    {
        // 情境：行動支付，消費日 5/28，距離 EndDate(5/31) = 3 天 > MobilePaymentBufferDays(2)
        // 預期：命中 program，RequiresManualVerification = false
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D06", new DateOnly(2026, 5, 28), 500m,
            mobilePayment: "全支付");

        var result = strategy.ResolveActiveProgram(txn);

        Assert.Equal("PROGRAM_A", result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);
    }

    [Fact]
    public void D07_跨境行動支付同時成立_reason_說明兩者兼有()
    {
        // 情境：跨境且行動支付（例如旅遊時用 Apple Pay 刷外幣），消費日在邊界附近
        // 舉例：使用TWQR掃描方式支付PayPay日本消費
        // 預期：RequiresManualVerification = true，reason 提及跨境與行動支付
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D07", new DateOnly(2026, 5, 31), 500m,
            transactionType: "一般國外交易",
            mobilePayment: "Apple Pay");  // 兩者同時成立

        var result = strategy.ResolveActiveProgram(txn);

        Assert.True(result.RequiresManualVerification);
        Assert.Contains("跨境", result.VerificationReason);
        Assert.Contains("行動支付", result.VerificationReason);

    }

    [Fact]
    public void D08_兩個_selection_區間重疊_應拋出例外()
    {
        // 情境：5/1~5/31 和 5/15~6/15 重疊，5/20 的交易會命中兩個 selection
        // 預期：拋出 InvalidOperationException 
        var selections = new List<DailyBenefitSelection>
        {
            ScenarioBuilder.DailySelection("PROGRAM_A", new DateOnly(2026, 5, 1),  new DateOnly(2026, 5, 31)),
            ScenarioBuilder.DailySelection("PROGRAM_B", new DateOnly(2026, 5, 15), new DateOnly(2026, 6, 15))
        };
        var strategy = new DailySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("D08", new DateOnly(2026, 5, 20), 500m);
        Assert.Throws<InvalidOperationException>(() => strategy.ResolveActiveProgram(txn));
    }
}