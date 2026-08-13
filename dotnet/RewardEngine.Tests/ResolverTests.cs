using RewardEngine.Core.Models;
using RewardEngine.Core.Resolvers;
using RewardEngine.Tests.Fixtures;
using Xunit;

namespace RewardEngine.Tests;

public class ResolverTests
{
    [Fact]
    public void R01_純Base交易_沒有Campaign沒有Bridge覆蓋_套用Program本身費率()
    {
        var programs = new List<CardRewardProgram> { ScenarioBuilder.BaseProgram(program: "TEST_BASE", rate: 0.01m) };
        var bridgeRules = new List<RewardBridgeRule>();  // 空，測試「無 bridge 命中退回 Program 費率」的假設

        var resolver = new RewardResolver(programs, bridgeRules);
        var txn = ScenarioBuilder.Transaction("T001", new DateOnly(2026, 5, 10), 1000m);

        var result = resolver.Resolve(txn);

        Assert.Equal(10m, result.TotalRewardAmount);  // 1000 * 1%
    }


    [Fact]
    public void R02_Campaign命中且RewardCalBreak_Base完全不計算()
    {
        var programs = new List<CardRewardProgram>
        {
          ScenarioBuilder.BaseProgram(program: "TEST_BASE", rate: 0.01m),
          ScenarioBuilder.BaseProgram(program: "TEST_CAMPAIGN", rate: 0.05m) with { Source = RewardProgramSource.Campaign }
        };
        var bridgeRules = new List<RewardBridgeRule>
        {
            new() { RulesRewardProgram = "TEST_CAMPAIGN", MerchantRate = 0.05m, Priority = 10, RewardCalBreak = true }
        };

        var resolver = new RewardResolver(programs, bridgeRules);
        var txn = ScenarioBuilder.Transaction("T002", new DateOnly(2026, 5, 10), 1000m);

        var result = resolver.Resolve(txn);

        Assert.Equal(50m, result.TotalRewardAmount);       // 只有 5%，不是 5%+1%
        Assert.Single(result.AppliedPrograms);               // 確認 Base 沒被加進 applied 清單
    }

    [Fact]
    public void R03_真實案例_Unicard全支付_Base加Campaign各自計算後疊加()
    {
        // Unicard 計算模型：Campaign 命中但 rewardCalBreak = false，Base 繼續疊加
        //   850 × 2.5% = 21.25  → 四捨五入至整數 = 21
        //   850 ×  1%  =  8.5   → 四捨五入至整數 =  9
        //   含 RoundStrategy 的正確答案 = 21 + 9 = 30m
        var programs = new List<CardRewardProgram>
        {
            ScenarioBuilder.BaseProgram(program: "Unicard一般消費", rate: 0.01m,
                bankName: "esun", cardType: "Unicard", rewardType: "cashback_round"),
            ScenarioBuilder.CampaignProgram(program: "Unicard指定特約商店", rate: 0.025m,
                bankName: "esun", cardType: "Unicard", rewardType: "cashback_round")
        };
        var bridgeRules = new List<RewardBridgeRule>
        {
            ScenarioBuilder.BridgeRule(rulesRewardProgram: "Unicard指定特約商店", merchantRate: 0.025m,
                priority: 5, mobilePayment: "全支付")
            // rewardCalBreak 預設 false：Campaign 命中不斷路，Base 繼續疊加
        };

        var resolver = new RewardResolver(programs, bridgeRules);
        var txn = ScenarioBuilder.Transaction(
            "真實交易ID或匿名化後的代號",
            transactionDate: new DateOnly(2026, 5, 12),
            amount: 850m,
            bankName: "esun", cardType: "Unicard",
            mobilePayment: "全支付");

        var result = resolver.Resolve(txn);

        Assert.Equal(30m, result.TotalRewardAmount);     // 正確套用 RoundStrategy：21 + 9 = 30m
        Assert.Equal(2, result.AppliedPrograms.Count);   // Campaign + Base 均應套用
    }

    [Theory]
    [InlineData("floor", 10.8, 10)]
    [InlineData("round", 10.5, 11)]
    [InlineData("ceil", 10.1, 11)]
    public void R06_RoundStrategy各種進位策略驗證(string strategy, decimal inputAmount, decimal expected)
    {
        var result = RoundStrategy.Apply(inputAmount, strategy, digits: 0);
        Assert.Equal(expected, result);
    }


    [Fact]
    public void R04_多個_Campaign_低_priority_的先_break_高_priority_的不執行()
    {
        // 情境：Campaign A (priority=5, break=true), Campaign B (priority=10, break=false)
        // 預期：A 先執行（數字小優先），break 後 B 不執行，Base 不執行
        // 驗證 Priority 排序方向正確（OrderBy 升冪）
        var programs = new List<CardRewardProgram>
        {
            ScenarioBuilder.BaseProgram("TEST_BASE", 0.01m),
            ScenarioBuilder.CampaignProgram("CAMPAIGN_A", 0.03m),
            ScenarioBuilder.CampaignProgram("CAMPAIGN_B", 0.05m)
        };
        var bridgeRules = new List<RewardBridgeRule>
        {
            ScenarioBuilder.BridgeRule("CAMPAIGN_A", 0.03m, priority: 5,  rewardCalBreak: true),
            ScenarioBuilder.BridgeRule("CAMPAIGN_B", 0.05m, priority: 10, rewardCalBreak: false)
        };
        var resolver = new RewardResolver(programs, bridgeRules);
        var txn = ScenarioBuilder.Transaction("R04", new DateOnly(2026, 5, 10), 1000m);

        var result = resolver.Resolve(txn);

        Assert.Equal(30m, result.TotalRewardAmount);   // 只有 CAMPAIGN_A 3%
        Assert.Single(result.AppliedPrograms);         // 只有 A，B 和 Base 都被截斷

    }

    [Fact]
    public void R05_Priority相同_Campaign無bridge命中時_退回_program本身費率()
    {
        // 情境：Campaign 存在，但 bridge rule 的 merchantDisplay 不匹配
        // 預期：bridge 未命中，退回 Campaign program 本身費率，無 break
        var programs = new List<CardRewardProgram>
        {
            ScenarioBuilder.BaseProgram("TEST_BASE", 0.01m),
            ScenarioBuilder.CampaignProgram("CAMPAIGN_X", 0.03m)
        };
        var bridgeRules = new List<RewardBridgeRule>
        {
            ScenarioBuilder.BridgeRule("CAMPAIGN_X", 0.05m, priority: 1,
                merchantDisplay: "特定商家A")  // txn 的 merchantDisplay 是 null，不匹配
        };
        var resolver = new RewardResolver(programs, bridgeRules);
        var txn = ScenarioBuilder.Transaction("R05", new DateOnly(2026, 5, 10), 1000m);

        var result = resolver.Resolve(txn);
        Assert.Equal(40m, result.TotalRewardAmount);  // 退回 Campaign 3% + Base 1% = 4% = 40m
        Assert.Equal(2, result.AppliedPrograms.Count);
    }

    [Fact]
    public void R07_AGGREGATE單筆與多筆累計進位差異驗證()
    {
        // 情境：兩筆 150 元交易，費率 3% (0.03)，進位策略為 floor
        // 單筆PER_ITEM計算：150 * 0.03 = 4.5 -> floor 4 元；兩筆各 4 元 = 8 元
        // AGGREGATE週期累計計算：
        //   第1筆：150 * 0.03 = 4.5 -> floor 4 元 (累計 4 元)
        //   第2筆：(150 + 150) * 0.03 = 9.0 -> floor 9 元，扣除已發 4 元 = 5 元
        //   兩筆總和 = 4 + 5 = 9 元 (展現 AGGREGATE 與 PER_ITEM 的 1 元差異)

        var program = ScenarioBuilder.BaseProgram(
            program: "AGGREGATE_TEST",
            rate: 0.03m,
            calcMethod: "AGGREGATE",
            roundStrategy: "floor",
            rewardCycle: "CALENDAR_MONTH"
        );

        var tracker = new RewardCycleTracker();
        var resolver = new RewardResolver([program], [], cycleTracker: tracker);

        var txn1 = ScenarioBuilder.Transaction("T1", new DateOnly(2026, 5, 10), 150m);
        var txn2 = ScenarioBuilder.Transaction("T2", new DateOnly(2026, 5, 15), 150m);

        var res1 = resolver.Resolve(txn1);
        Assert.Equal(4m, res1.TotalRewardAmount);
        Assert.Equal(4m, res1.AppliedPrograms[0].CalculatedRewardAmount);

        var res2 = resolver.Resolve(txn2);
        Assert.Equal(5m, res2.TotalRewardAmount);
        Assert.Equal(5m, res2.AppliedPrograms[0].CalculatedRewardAmount);

        // 兩筆總和 4 + 5 = 9 元
        Assert.Equal(9m, res1.TotalRewardAmount + res2.TotalRewardAmount);
    }

    [Fact]
    public void R08_AGGREGATE搭配CapAmount上限截斷驗證()
    {
        // 情境：費率 3% (0.03)，AGGREGATE 累計，floor 進位，CapAmount 上限 10 元
        //   第1筆 150 元: 累計 150 * 0.03 = 4.5 -> floor 4 元。發放 4 元 (未達Cap)
        //   第2筆 300 元: 累計 450 * 0.03 = 13.5 -> floor 13 元。 raw增量 = 13 - 4 = 9 元。
        //                但 Cap=10，剩餘額度 10 - 4 = 6 元。發放 6 元，IsCapped = true。
        //   第3筆 100 元: 已達 Cap=10 元。發放 0 元，IsCapped = true。

        var program = ScenarioBuilder.BaseProgram(
            program: "AGGREGATE_CAP_TEST",
            rate: 0.03m,
            calcMethod: "AGGREGATE",
            roundStrategy: "floor",
            rewardCycle: "CALENDAR_MONTH"
        ) with { CapAmount = 10m };

        var tracker = new RewardCycleTracker();
        var resolver = new RewardResolver([program], [], cycleTracker: tracker);

        var txn1 = ScenarioBuilder.Transaction("T1", new DateOnly(2026, 5, 10), 150m);
        var txn2 = ScenarioBuilder.Transaction("T2", new DateOnly(2026, 5, 15), 300m);
        var txn3 = ScenarioBuilder.Transaction("T3", new DateOnly(2026, 5, 20), 100m);

        var res1 = resolver.Resolve(txn1);
        Assert.Equal(4m, res1.TotalRewardAmount);
        Assert.False(res1.AppliedPrograms[0].IsCapped);

        var res2 = resolver.Resolve(txn2);
        Assert.Equal(6m, res2.TotalRewardAmount);
        Assert.True(res2.AppliedPrograms[0].IsCapped);

        var res3 = resolver.Resolve(txn3);
        Assert.Equal(0m, res3.TotalRewardAmount);
        Assert.True(res3.AppliedPrograms[0].IsCapped);

        Assert.Equal(10m, tracker.GetAccumulated(tracker.BuildCycleKey(program, txn1)));
    }

    [Fact]
    public void R09_AGGREGATE無CycleTracker時退回單筆計算()
    {
        var program = ScenarioBuilder.BaseProgram(
            program: "AGGREGATE_NO_TRACKER",
            rate: 0.03m,
            calcMethod: "AGGREGATE",
            roundStrategy: "floor"
        );

        var resolver = new RewardResolver([program], []);
        var txn = ScenarioBuilder.Transaction("T1", new DateOnly(2026, 5, 10), 150m);

        var res = resolver.Resolve(txn);
        Assert.Equal(4m, res.TotalRewardAmount);
    }
}

