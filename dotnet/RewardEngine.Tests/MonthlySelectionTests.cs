using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using RewardEngine.Tests.Fixtures;
using Xunit;

public class MonthlySelectionTests
{
    [Fact]
    public void M01_正常月份_入帳日在截止日內_正確命中()
    {
        // 情境：5月消費，入帳 6/1，截止日 6/3 → 正常
        // 注意：消費月最後一天 5/31，需在 selection [5/1, 5/31] 內
        var selections = new List<MonthlyBenefitSelection>
        {
            ScenarioBuilder.MonthlySelection(
            rulesRewardProgram:   "Unicard指定特約商店",
            campaignRewardProgram: "Unicard指定特約商店",
            startDate:     new DateOnly(2026, 5, 1),
            endDate:       new DateOnly(2026, 5, 31),
            maxPostingDate: new DateOnly(2026, 6, 3))
        };
        var strategy = new MonthlySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("M01", new DateOnly(2026, 5, 20), 500m,
            postingDate: new DateOnly(2026, 6, 1));

        var result = strategy.ResolveActiveProgram(txn);

        Assert.Equal("Unicard指定特約商店", result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);
    }
    
    [Fact]
    public void M02_入帳日超過截止日_觸發人工確認()
    {
        // 情境：5月消費，入帳 6/5，截止日 6/3 → 需人工確認
        var selections = new List<MonthlyBenefitSelection>
        {
            ScenarioBuilder.MonthlySelection(
            rulesRewardProgram:   "Unicard指定特約商店",
            campaignRewardProgram: "Unicard指定特約商店",
            startDate:     new DateOnly(2026, 5, 1),
            endDate:       new DateOnly(2026, 5, 31),
            maxPostingDate: new DateOnly(2026, 6, 3))
        };
        var strategy = new MonthlySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("M02", new DateOnly(2026, 5, 20), 500m,
            postingDate: new DateOnly(2026, 6, 5));  // 超過截止日
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Null(result.ResolvedProgram);              // 未確認歸屬，不分配 program
        Assert.True(result.RequiresManualVerification);
        Assert.Contains("入帳日", result.VerificationReason);
        Assert.Contains("截止日", result.VerificationReason);
    }

    [Fact]
    public void M03_消費月不在任何_selection_區間_回傳_null()
    {
        // 情境：7月消費，只有 5月的 selection → 無命中
        var selections = new List<MonthlyBenefitSelection>
        {
            ScenarioBuilder.MonthlySelection(
            rulesRewardProgram:   "Unicard指定特約商店",
            campaignRewardProgram: "Unicard指定特約商店",
            startDate:     new DateOnly(2026, 5, 1),
            endDate:       new DateOnly(2026, 5, 31),
            maxPostingDate: new DateOnly(2026, 6, 3))
        };
        var strategy = new MonthlySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("M03", new DateOnly(2026, 7, 10), 500m);
        var result = strategy.ResolveActiveProgram(txn);
        Assert.Null(result.ResolvedProgram);
        Assert.False(result.RequiresManualVerification);
    }

    [Fact]
    public void M04_同權益項目的兩個_selection_月份重疊_應拋出例外()
    {
        // 情境：同一個 rulesRewardProgram (PROG_A) 的兩個 selection 區間重疊，同一消費月的最後一天命中兩個 → 例外
        var selections = new List<MonthlyBenefitSelection>
        {
            ScenarioBuilder.MonthlySelection("PROG_A", "PROG_A",
            new DateOnly(2026, 5, 1), new DateOnly(2026, 5, 31), new DateOnly(2026, 6, 3)),
            ScenarioBuilder.MonthlySelection("PROG_A", "PROG_B",
            new DateOnly(2026, 5, 15), new DateOnly(2026, 6, 14), new DateOnly(2026, 7, 3))
        };
        var strategy = new MonthlySelectionStrategy(selections);
        var txn = ScenarioBuilder.Transaction("M04", new DateOnly(2026, 5, 10), 500m);

        Assert.Throws<InvalidOperationException>(() => strategy.ResolveActiveProgram(txn));
    }    



}