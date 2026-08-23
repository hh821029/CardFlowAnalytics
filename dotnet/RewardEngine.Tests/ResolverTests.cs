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
            ScenarioBuilder.CampaignProgram(program: "TEST_CAMPAIGN", rate: 0.05m, priority: 400, rewardCalBreak: true),
            ScenarioBuilder.BaseProgram(program: "TEST_BASE", rate: 0.01m, priority: 999, rewardCalBreak: true)
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
            ScenarioBuilder.CampaignProgram(program: "Unicard指定特約商店", rate: 0.025m, priority: 400, rewardCalBreak: false,
                bankName: "esun", cardType: "Unicard", rewardType: "cashback_round"),
            ScenarioBuilder.BaseProgram(program: "Unicard一般消費", rate: 0.01m, priority: 988, rewardCalBreak: true,
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
        // 情境：Campaign A (priority=300, break=true), Campaign B (priority=400, break=false)
        // 預期：A 先執行（數字小優先），break 後 B 不執行，Base 不執行
        // 驗證 Priority 排序方向正確（OrderBy 升冪）
        var programs = new List<CardRewardProgram>
        {
            ScenarioBuilder.CampaignProgram("CAMPAIGN_A", 0.03m, priority: 300, rewardCalBreak: true),
            ScenarioBuilder.CampaignProgram("CAMPAIGN_B", 0.05m, priority: 400, rewardCalBreak: false),
            ScenarioBuilder.BaseProgram("TEST_BASE", 0.01m, priority: 999, rewardCalBreak: true)
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
            ScenarioBuilder.CampaignProgram("CAMPAIGN_X", 0.03m, priority: 400, rewardCalBreak: false),
            ScenarioBuilder.BaseProgram("TEST_BASE", 0.01m, priority: 999, rewardCalBreak: true)
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

    [Fact]
    public void R10_回饋池架構_純Base方案掛載通用排除池_非超商正常回饋_超商被排除且截斷()
    {
        var exclusionPool = ScenarioBuilder.Pool(
            poolId: "POOL_GENERAL_EXCLUSION",
            rules:
            [
                new MerchantRewardRule
                {
                    NormalizedMerchant = ["統一超商", "全家便利商店"],
                    MerchantRate = 0.0m
                }
            ]);

        var baseProg = ScenarioBuilder.BaseProgram("玉山一般消費", 0.01m,
            rewardId: "esun_base", bankNo: "808", bankName: "esun", cardType: "Unicard", priority: 988);

        var exclusionProg = ScenarioBuilder.BaseProgram("共通非一般消費", 0.0m,
            rewardId: "all_general_exclusion", bankNo: "ALL", bankName: "ALL", priority: 499, rewardCalBreak: true);

        var links = new List<RewardLinkedList>
        {
            ScenarioBuilder.Link("all_general_exclusion", "POOL_GENERAL_EXCLUSION")
        };

        var resolver = new RewardResolver([exclusionProg, baseProg], [exclusionPool], links);

        // 1. 一般餐廳消費：未命中排除池，順利獲得 1% 回饋 (1000 * 1% = 10)
        var txnNormal = ScenarioBuilder.Transaction("T10_Normal", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", merchantDisplay: "鼎泰豐");
        var resNormal = resolver.Resolve(txnNormal);
        Assert.Equal(10m, resNormal.TotalRewardAmount);
        Assert.Single(resNormal.AppliedPrograms);
        Assert.Equal("玉山一般消費", resNormal.AppliedPrograms[0].Program.RewardProgram);

        // 2. 7-11 超商消費：命中排除池 0% 且 RewardCalBreak，截斷後續 Base 方案
        var txn711 = ScenarioBuilder.Transaction("T10_711", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", merchantDisplay: "統一超商");
        var res711 = resolver.Resolve(txn711);
        Assert.Equal(0m, res711.TotalRewardAmount);
        Assert.Single(res711.AppliedPrograms);
        Assert.Equal("共通非一般消費", res711.AppliedPrograms[0].Program.RewardProgram);
    }

    [Fact]
    public void R11_回饋池架構_聯名卡命中PassRules豁免放行_不被排除池阻擋()
    {
        var exclusionPool = ScenarioBuilder.Pool(
            poolId: "POOL_GENERAL_EXCLUSION",
            passRules:
            [
                new MerchantRewardRule
                {
                    NormalizedMerchant = ["統一超商"],
                    CardType = ["Uniopen聯名卡"],
                    BankNo = ["822"]
                }
            ],
            rules:
            [
                new MerchantRewardRule
                {
                    NormalizedMerchant = ["統一超商", "全家便利商店"],
                    MerchantRate = 0.0m
                }
            ]);

        var uniopenBase = ScenarioBuilder.BaseProgram("Uniopen一般消費", 0.01m,
            rewardId: "ctbc_uniopen_base", bankNo: "822", bankName: "ctbc", cardType: "Uniopen聯名卡", priority: 987);

        var exclusionProg = ScenarioBuilder.BaseProgram("共通非一般消費", 0.0m,
            rewardId: "all_general_exclusion", bankNo: "ALL", bankName: "ALL", priority: 499, rewardCalBreak: true);

        var links = new List<RewardLinkedList>
        {
            ScenarioBuilder.Link("all_general_exclusion", "POOL_GENERAL_EXCLUSION")
        };

        var resolver = new RewardResolver([exclusionProg, uniopenBase], [exclusionPool], links);

        // Uniopen 聯名卡在 7-11 消費：命中 PassRules 豁免，排除池不生效，成功拿到 1% 回饋
        var txn = ScenarioBuilder.Transaction("T11", new DateOnly(2026, 5, 10), 1000m,
            bankNo: "822", bankName: "ctbc", cardId: "ctbc_uniopen", cardType: "Uniopen聯名卡", merchantDisplay: "統一超商");
        var res = resolver.Resolve(txn);

        Assert.Equal(10m, res.TotalRewardAmount);
        Assert.Single(res.AppliedPrograms);
        Assert.Equal("Uniopen一般消費", res.AppliedPrograms[0].Program.RewardProgram);
    }

    [Fact]
    public void R12_回饋池架構_ALL哨兵值正面表列_必須使用行動支付始能命中()
    {
        var mobilePayPool = ScenarioBuilder.Pool(
            poolId: "POOL_MOBILE_PAY",
            rules:
            [
                new MerchantRewardRule
                {
                    PaymentProcess = ["ALL"],
                    MerchantRate = 0.05m
                }
            ]);

        var campProg = ScenarioBuilder.CampaignProgram("行動支付加碼", 0.05m,
            rewardId: "camp_mobile", bankNo: "808", bankName: "esun", cardType: "Unicard", priority: 300);

        var links = new List<RewardLinkedList>
        {
            ScenarioBuilder.Link("camp_mobile", "POOL_MOBILE_PAY")
        };

        var resolver = new RewardResolver([campProg], [mobilePayPool], links);

        // 1. 有使用行動支付 (LINE Pay)：命中 ALL 正面表列 ➔ 獲得 5%
        var txnMobile = ScenarioBuilder.Transaction("T12_Mobile", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", mobilePayment: "LINE Pay");
        var resMobile = resolver.Resolve(txnMobile);
        Assert.Equal(50m, resMobile.TotalRewardAmount);

        // 2. 實體刷卡 (無行動支付)：未命中 ALL ➔ 0 元
        var txnPhysical = ScenarioBuilder.Transaction("T12_Physical", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", mobilePayment: null);
        var resPhysical = resolver.Resolve(txnPhysical);
        Assert.Equal(0m, resPhysical.TotalRewardAmount);
        Assert.Empty(resPhysical.AppliedPrograms);
    }

    [Fact]
    public void R13_回饋池架構_NONE哨兵值反向排除_無行動支付始能命中()
    {
        var physicalOnlyPool = ScenarioBuilder.Pool(
            poolId: "POOL_PHYSICAL_ONLY",
            rules:
            [
                new MerchantRewardRule
                {
                    PaymentProcess = ["NONE"],
                    MerchantRate = 0.02m
                }
            ]);

        var prog = ScenarioBuilder.CampaignProgram("純實體刷卡回饋", 0.02m,
            rewardId: "camp_physical", bankNo: "808", bankName: "esun", cardType: "Unicard", priority: 300);

        var links = new List<RewardLinkedList>
        {
            ScenarioBuilder.Link("camp_physical", "POOL_PHYSICAL_ONLY")
        };

        var resolver = new RewardResolver([prog], [physicalOnlyPool], links);

        // 1. 實體刷卡 (mobilePayment = null)：命中 NONE ➔ 獲得 2%
        var txnPhysical = ScenarioBuilder.Transaction("T13_Physical", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", mobilePayment: null);
        var resPhysical = resolver.Resolve(txnPhysical);
        Assert.Equal(20m, resPhysical.TotalRewardAmount);

        // 2. 行動支付 (mobilePayment = "全支付")：不符合 NONE ➔ 0 元
        var txnMobile = ScenarioBuilder.Transaction("T13_Mobile", new DateOnly(2026, 5, 10), 1000m,
            bankName: "esun", cardType: "Unicard", mobilePayment: "全支付");
        var resMobile = resolver.Resolve(txnMobile);
        Assert.Equal(0m, resMobile.TotalRewardAmount);
        Assert.Empty(resMobile.AppliedPrograms);
    }

    [Fact]
    public void R14_回饋池架構_跨行物理隔離_中信卡不會命中玉山Base方案()
    {
        var esunBase = ScenarioBuilder.BaseProgram("玉山Base", 0.01m,
            rewardId: "esun_base", bankNo: "808", bankName: "esun", cardType: "Unicard", priority: 999);

        var resolver = new RewardResolver([esunBase], [], []);

        // 中信卡交易 (BankNo 822)
        var txnCtbc = ScenarioBuilder.Transaction("T14_Ctbc", new DateOnly(2026, 5, 10), 1000m,
            bankName: "ctbc", cardType: "Uniopen聯名卡");

        var res = resolver.Resolve(txnCtbc);
        Assert.Equal(0m, res.TotalRewardAmount);
        Assert.Empty(res.AppliedPrograms);
    }

    [Fact]
    public void R15_回饋池架構_ALL通用方案_全行信用卡自動掛載()
    {
        var universalProg = ScenarioBuilder.BaseProgram("全行通用促刷", 0.005m,
            rewardId: "all_promo", bankNo: "ALL", bankName: "ALL", priority: 500, rewardCalBreak: false);

        var resolver = new RewardResolver([universalProg], [], []);

        // 任意銀行交易（如國泰 Cube）均能掛載此 ALL 方案
        var txnCathay = ScenarioBuilder.Transaction("T15", new DateOnly(2026, 5, 10), 1000m,
            bankName: "cathay", cardType: "Cube卡");

        var res = resolver.Resolve(txnCathay);
        Assert.Equal(5m, res.TotalRewardAmount);
        Assert.Single(res.AppliedPrograms);
    }
}

