using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public sealed class RewardResolver(
    IReadOnlyList<CardRewardProgram> programs,
    IReadOnlyList<RewardBridgeRule> bridgeRules,
    IBenefitSelectionStrategy? dailySelection = null,
    IBenefitSelectionStrategy? monthlySelection = null,
    RewardCycleTracker? cycleTracker = null)
{
    public ResolvedReward Resolve(RewardTransaction txn)
    {
        // Stage 0：權益選擇閘門（僅選擇制卡片會有值）
        var lockedBaseProgram = dailySelection?.ResolveActiveProgram(txn)?.ResolvedProgram;

        var lockedCampaignRulesProgram = monthlySelection?.ResolveActiveProgram(txn);

        // Stage 1：Base（依卡別/日期/當前權益/鎖定權益取得候選方案）
        var baseCandidates = programs
            .Where(p => p.Source == RewardProgramSource.Base
                        && p.BankName == txn.BankName
                        && p.CardType == txn.CardType
                        && p.IsCurrentBenefit
                        && WithinDateRange(txn.TransactionDate, p.StartDate, p.EndDate)
                        && (lockedBaseProgram == null || p.RewardProgram == lockedBaseProgram))
            .ToList();

        // Stage 2：Campaign（可疊加）
        var campaignPrograms = programs
            .Where(p => p.Source == RewardProgramSource.Campaign
                        && p.BankName == txn.BankName
                        && p.CardType == txn.CardType
                        && p.IsCurrentBenefit
                        && WithinDateRange(txn.TransactionDate, p.StartDate, p.EndDate))
            .ToList();

        // Stage 3：逐一做 Bridge 費率解析
        var baseResolutions = baseCandidates
            .Select(bp => ResolveBridge(bp, txn))
            .ToList();
        var campaignResolutions = campaignPrograms
            .Select(cp => ResolveBridge(cp, txn))
            .ToList();

        // Stage 4：若該卡別有 MonthlySelection（如 Unicard 月結切換），僅排除同項目未被選中的競品 Campaign，常駐型加碼活動照常保留
        if (monthlySelection is MonthlySelectionStrategy mss)
        {
            var activeSelections = mss.GetActiveSelections(txn);
            if (activeSelections.Count > 0)
            {
                var selectedCampaignPrograms = activeSelections
                    .Select(s => s.CampaignRewardProgram)
                    .ToHashSet();

                var targetSelectionRules = activeSelections
                    .Select(s => s.RulesRewardProgram)
                    .ToHashSet();

                campaignResolutions = campaignResolutions
                    .Where(r => {
                        var ruleProg = r.MatchedBridgeRule?.RulesRewardProgram;
                        var campProg = r.Program.RewardProgram;
                        // 若屬月結選擇項目，僅保留當月被選中的 Campaign；非月結選擇項目（常駐加碼）全部保留
                        if (targetSelectionRules.Contains(ruleProg ?? "") || targetSelectionRules.Contains(campProg))
                        {
                            return selectedCampaignPrograms.Contains(campProg) || selectedCampaignPrograms.Contains(ruleProg ?? "");
                        }
                        return true;
                    })
                    .ToList();
            }
        }

        // Stage 4：break 短路 —— 先 Campaign（依 priority 升冪，數字越小越優先），再 Base
        var applied = new List<ProgramRateResolution>();
        var broke = false;

        foreach (var cr in campaignResolutions.OrderBy(r => r.MatchedBridgeRule?.Priority ?? int.MaxValue))
        {
            applied.Add(cr);
            if (cr.BreakTriggered) { broke = true; break; }
        }

        if (!broke)
        {
            foreach (var br in baseResolutions.OrderBy(r => r.MatchedBridgeRule?.Priority ?? int.MaxValue))
            {
                applied.Add(br);
                if (br.BreakTriggered) break;
            }
        }

        // Stage 5：套用 RewardCycleTracker 進行上限 (cap_amount) 累計與截斷處理 (含 AGGREGATE 累計與進位處理)
        var finalApplied = new List<ProgramRateResolution>();
        foreach (var res in applied)
        {
            if (cycleTracker is not null)
            {
                var (awarded, isCapped) = string.Equals(res.Program.CalcMethod, "AGGREGATE", StringComparison.OrdinalIgnoreCase)
                    ? cycleTracker.ApplyAggregateCapAndAccumulate(res, txn)
                    : cycleTracker.ApplyCapAndAccumulate(res.Program, txn, res.CalculatedRewardAmount);

                finalApplied.Add(res with { CalculatedRewardAmount = awarded, IsCapped = isCapped });
            }
            else
            {
                finalApplied.Add(res);
            }
        }

        var total = finalApplied.Sum(a => a.CalculatedRewardAmount);

        return new ResolvedReward
        {
            TransactionId = txn.TransactionId,
            AppliedPrograms = finalApplied,
            TotalRewardAmount = total
        };
    }

    private ProgramRateResolution ResolveBridge(CardRewardProgram program, RewardTransaction txn)
    {
        var winner = bridgeRules
            .Where(b => b.RulesRewardProgram == program.RewardProgram
                        && WithinDateRange(txn.TransactionDate, b.StartDate, b.EndDate)
                        && Matches(b.VpcType, txn.VpcType)
                        && Matches(b.MobilePayment, txn.MobilePayment)
                        && Matches(b.EcPlatform, txn.EcPlatform)
                        && Matches(b.MerchantDisplay, txn.MerchantDisplay)
                        && Matches(b.MerchantLocation, txn.MerchantLocation))
            .OrderBy(b => b.Priority)
            .FirstOrDefault();

        var effectiveRate = winner?.MerchantRate ?? program.RewardRate ?? 0m;

        var resolution = new ProgramRateResolution
        {
            Program = program,
            MatchedBridgeRule = winner,
            EffectiveRate = effectiveRate
        };

        return resolution with
        {
            CalculatedRewardAmount = RoundStrategy.CalculateResolutionReward(txn.Amount, resolution)
        };
    }

    private static bool Matches(string? ruleValue, string? txnValue) =>
        string.IsNullOrEmpty(ruleValue) || ruleValue == txnValue;   // 空值 = 萬用

    private static bool WithinDateRange(DateOnly date, DateOnly? start, DateOnly? end) =>
        (start is null || date >= start) && (end is null || date <= end);
}