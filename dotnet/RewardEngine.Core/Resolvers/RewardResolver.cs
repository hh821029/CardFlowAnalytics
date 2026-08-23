using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public sealed class RewardResolver
{
    private readonly IReadOnlyList<CardRewardProgram> _programs;
    private readonly IReadOnlyList<MerchantRewardPool> _pools;
    private readonly IReadOnlyList<RewardLinkedList> _linkedLists;
    private readonly IReadOnlyList<RewardBridgeRule> _bridgeRules;
    private readonly IBenefitSelectionStrategy? _dailySelection;
    private readonly IBenefitSelectionStrategy? _monthlySelection;
    private readonly RewardCycleTracker? _cycleTracker;
    private readonly Dictionary<string, List<MerchantRewardPool>> _rewardPoolsLookup;
    private readonly bool _usePoolEngine;

    /// <summary>
    /// 全新回饋池架構建構函式 (43 個 RewardPools + 103 筆 RewardLinkedLists)
    /// </summary>
    public RewardResolver(
        IReadOnlyList<CardRewardProgram> programs,
        IReadOnlyList<MerchantRewardPool> pools,
        IReadOnlyList<RewardLinkedList> linkedLists,
        IBenefitSelectionStrategy? dailySelection = null,
        IBenefitSelectionStrategy? monthlySelection = null,
        RewardCycleTracker? cycleTracker = null)
    {
        _programs = programs;
        _pools = pools;
        _linkedLists = linkedLists;
        _bridgeRules = [];
        _dailySelection = dailySelection;
        _monthlySelection = monthlySelection;
        _cycleTracker = cycleTracker;
        _usePoolEngine = true;

        var poolDict = pools.ToDictionary(p => p.MerchantRewardPoolsId, p => p, StringComparer.OrdinalIgnoreCase);
        _rewardPoolsLookup = new Dictionary<string, List<MerchantRewardPool>>(StringComparer.OrdinalIgnoreCase);

        foreach (var link in linkedLists)
        {
            if (poolDict.TryGetValue(link.MerchantRewardPoolsId, out var pool))
            {
                if (!_rewardPoolsLookup.TryGetValue(link.RewardId, out var list))
                {
                    list = [];
                    _rewardPoolsLookup[link.RewardId] = list;
                }
                list.Add(pool);
            }
        }
    }

    /// <summary>
    /// 相容舊版 Bridge 規則之建構函式
    /// </summary>
    public RewardResolver(
        IReadOnlyList<CardRewardProgram> programs,
        IReadOnlyList<RewardBridgeRule> bridgeRules,
        IBenefitSelectionStrategy? dailySelection = null,
        IBenefitSelectionStrategy? monthlySelection = null,
        RewardCycleTracker? cycleTracker = null)
    {
        _programs = programs;
        _pools = [];
        _linkedLists = [];
        _bridgeRules = bridgeRules;
        _dailySelection = dailySelection;
        _monthlySelection = monthlySelection;
        _cycleTracker = cycleTracker;
        _usePoolEngine = false;
        _rewardPoolsLookup = new Dictionary<string, List<MerchantRewardPool>>(StringComparer.OrdinalIgnoreCase);
    }

    public ResolvedReward Resolve(RewardTransaction txn)
    {
        // Stage 0：每日權益選擇閘門（僅選擇制卡片如 CUBE 有值）
        var lockedBaseProgram = _dailySelection?.ResolveActiveProgram(txn)?.ResolvedProgram;

        // Stage 1：候選方案過濾（卡別/銀行物理隔離、日期區間、每日權益鎖定）
        var candidates = _programs.Where(p =>
        {
            if (!WithinDateRange(txn.TransactionDate, p.StartDate, p.EndDate))
                return false;

            bool isBankMatch = string.Equals(p.BankNo, "ALL", StringComparison.OrdinalIgnoreCase) ||
                               string.Equals(p.BankName, "ALL", StringComparison.OrdinalIgnoreCase) ||
                               (!string.IsNullOrEmpty(txn.BankNo) && string.Equals(p.BankNo, txn.BankNo, StringComparison.OrdinalIgnoreCase)) ||
                               (!string.IsNullOrEmpty(txn.BankName) && string.Equals(p.BankName, txn.BankName, StringComparison.OrdinalIgnoreCase));
            if (!isBankMatch) return false;

            bool isCardMatch = (string.IsNullOrEmpty(p.CardId) && string.IsNullOrEmpty(p.CardType)) ||
                               string.Equals(p.CardId, "ALL", StringComparison.OrdinalIgnoreCase) ||
                               string.Equals(p.CardType, "ALL", StringComparison.OrdinalIgnoreCase) ||
                               (!string.IsNullOrEmpty(txn.CardId) && string.Equals(p.CardId, txn.CardId, StringComparison.OrdinalIgnoreCase)) ||
                               (!string.IsNullOrEmpty(txn.CardType) && string.Equals(p.CardType, txn.CardType, StringComparison.OrdinalIgnoreCase));
            if (!isCardMatch) return false;

            if (p.Source == RewardProgramSource.Base && lockedBaseProgram != null &&
                !string.Equals(p.RewardProgram, lockedBaseProgram, StringComparison.OrdinalIgnoreCase))
                return false;

            return true;
        }).ToList();

        // Stage 2 & 3：費率解析 (Pool Engine 或 Bridge Engine)
        var candidateResolutions = new List<ProgramRateResolution>();

        if (_usePoolEngine)
        {
            foreach (var prog in candidates)
            {
                var res = EvaluateProgramWithPools(prog, txn);
                if (res != null)
                {
                    candidateResolutions.Add(res);
                }
            }
        }
        else
        {
            foreach (var prog in candidates)
            {
                var res = ResolveBridgeLegacy(prog, txn);
                candidateResolutions.Add(res);
            }
        }

        // Stage 4：月結權益選擇篩選（如 Unicard 月結切換）
        if (_monthlySelection is MonthlySelectionStrategy mss)
        {
            var activeSelections = mss.GetActiveSelections(txn);
            if (activeSelections.Count > 0)
            {
                var selectedCampaignPrograms = activeSelections
                    .Select(s => s.CampaignRewardProgram)
                    .ToHashSet(StringComparer.OrdinalIgnoreCase);

                var targetSelectionRules = activeSelections
                    .Select(s => s.RulesRewardProgram)
                    .ToHashSet(StringComparer.OrdinalIgnoreCase);

                candidateResolutions = candidateResolutions
                    .Where(r =>
                    {
                        var ruleProg = r.MatchedBridgeRule?.RulesRewardProgram;
                        var campProg = r.Program.RewardProgram;
                        if (targetSelectionRules.Contains(ruleProg ?? "") || targetSelectionRules.Contains(campProg))
                        {
                            return selectedCampaignPrograms.Contains(campProg) || selectedCampaignPrograms.Contains(ruleProg ?? "");
                        }
                        return true;
                    })
                    .ToList();
            }
        }

        // Stage 5：Waterfall 優先序排序與短路截斷（Priority 升冪，數字越小越優先）
        var applied = new List<ProgramRateResolution>();
        foreach (var res in candidateResolutions.OrderBy(r => r.Program.Priority))
        {
            applied.Add(res);
            if (res.BreakTriggered)
            {
                break;
            }
        }

        // Stage 6：套用 RewardCycleTracker 進行週期上限控管與進位策略處理
        var finalApplied = new List<ProgramRateResolution>();
        foreach (var res in applied)
        {
            if (_cycleTracker != null)
            {
                var (awarded, isCapped) = string.Equals(res.Program.CalcMethod, "AGGREGATE", StringComparison.OrdinalIgnoreCase)
                    ? _cycleTracker.ApplyAggregateCapAndAccumulate(res, txn)
                    : _cycleTracker.ApplyCapAndAccumulate(res.Program, txn, res.CalculatedRewardAmount);

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

    private ProgramRateResolution? EvaluateProgramWithPools(CardRewardProgram program, RewardTransaction txn)
    {
        if (!_rewardPoolsLookup.TryGetValue(program.RewardId, out var linkedPools) || linkedPools.Count == 0)
        {
            // 若方案未掛載任何特店池，視為全通路基礎方案，直接套用方案費率
            var rate = program.RewardRate ?? 0m;
            var res = new ProgramRateResolution
            {
                Program = program,
                EffectiveRate = rate
            };
            return res with
            {
                CalculatedRewardAmount = RoundStrategy.CalculateResolutionReward(txn.Amount, res)
            };
        }

        // 遍歷所有掛載的回饋池
        foreach (var pool in linkedPools)
        {
            // 1. 先查豁免白名單 (PassRules)
            if (pool.PassRules != null && pool.PassRules.Length > 0)
            {
                var isExempted = pool.PassRules.Any(pr => MatchesPoolRule(pr, txn));
                if (isExempted)
                {
                    // 若命中豁免白名單，此池不對該交易生效（若為排除池則不排除）
                    continue;
                }
            }

            // 2. 比對正向規則清單 (Rules)
            if (pool.Rules != null && pool.Rules.Length > 0)
            {
                var matchedRule = pool.Rules.FirstOrDefault(r => MatchesPoolRule(r, txn));
                if (matchedRule != null)
                {
                    var effectiveRate = matchedRule.MerchantRate ?? program.RewardRate ?? 0m;
                    var res = new ProgramRateResolution
                    {
                        Program = program,
                        MatchedPool = pool,
                        MatchedRule = matchedRule,
                        EffectiveRate = effectiveRate
                    };
                    return res with
                    {
                        CalculatedRewardAmount = RoundStrategy.CalculateResolutionReward(txn.Amount, res)
                    };
                }
            }
        }

        return null;
    }

    private static bool MatchesPoolRule(MerchantRewardRule rule, RewardTransaction txn)
    {
        // 1. 日期區間檢核
        if (!WithinDateRange(txn.TransactionDate, rule.StartDate, rule.EndDate))
            return false;

        // 2. 銀行與卡別限制
        if (rule.BankNo != null && rule.BankNo.Length > 0)
        {
            if (!MatchesBankOrCard(rule.BankNo, txn.BankNo) && !MatchesBankOrCard(rule.BankNo, txn.BankName))
                return false;
        }
        if (rule.BankName != null && rule.BankName.Length > 0)
        {
            if (!MatchesBankOrCard(rule.BankName, txn.BankName))
                return false;
        }
        if (rule.CardId != null && rule.CardId.Length > 0)
        {
            if (!MatchesBankOrCard(rule.CardId, txn.CardId) && !MatchesBankOrCard(rule.CardId, txn.CardType))
                return false;
        }
        if (rule.CardType != null && rule.CardType.Length > 0)
        {
            if (!MatchesBankOrCard(rule.CardType, txn.CardType))
                return false;
        }

        // 3. 管道與行為屬性（支援 ALL / NONE / 清單比對）
        if (!MatchesBehaviorField(rule.PaymentProcess, txn.PaymentProcess ?? txn.MobilePayment))
            return false;
        if (!MatchesBehaviorField(rule.EcPlatform, txn.EcPlatform))
            return false;
        if (!MatchesBehaviorField(rule.VpcType, txn.VpcType))
            return false;

        // 4. 地理/國別限制
        if (!MatchesLocationField(rule.MerchantLocation, txn.MerchantLocation))
            return false;

        // 5. 特約商店名稱 (NormalizedMerchant / MerchantDisplay)
        if (!MatchesMerchantField(rule, txn))
            return false;

        return true;
    }

    private static bool MatchesBehaviorField(string[]? ruleValues, string? txnValue)
    {
        if (ruleValues == null || ruleValues.Length == 0)
            return true; // 完全不限制 (Wildcard)

        bool hasNone = ruleValues.Any(v => string.Equals(v, "NONE", StringComparison.OrdinalIgnoreCase));
        bool hasAll = ruleValues.Any(v => string.Equals(v, "ALL", StringComparison.OrdinalIgnoreCase));
        bool isTxnEmptyOrNone = string.IsNullOrWhiteSpace(txnValue) || string.Equals(txnValue, "NONE", StringComparison.OrdinalIgnoreCase);

        if (hasNone && isTxnEmptyOrNone)
            return true;

        if (hasAll && !isTxnEmptyOrNone)
            return true;

        if (!isTxnEmptyOrNone)
        {
            return ruleValues.Any(v => string.Equals(v, txnValue, StringComparison.OrdinalIgnoreCase));
        }

        return false;
    }

    private static bool MatchesLocationField(string[]? ruleValues, string? txnValue)
    {
        if (ruleValues == null || ruleValues.Length == 0)
            return true;

        bool hasNone = ruleValues.Any(v => string.Equals(v, "NONE", StringComparison.OrdinalIgnoreCase));
        bool hasAll = ruleValues.Any(v => string.Equals(v, "ALL", StringComparison.OrdinalIgnoreCase));
        bool isTxnEmptyOrNone = string.IsNullOrWhiteSpace(txnValue) || string.Equals(txnValue, "NONE", StringComparison.OrdinalIgnoreCase);

        if (hasNone && isTxnEmptyOrNone)
            return true;

        if (hasAll && !isTxnEmptyOrNone)
            return true;

        if (!isTxnEmptyOrNone)
        {
            return ruleValues.Any(v => string.Equals(v, txnValue, StringComparison.OrdinalIgnoreCase));
        }

        return false;
    }

    private static bool MatchesMerchantField(MerchantRewardRule rule, RewardTransaction txn)
    {
        var ruleMerchants = rule.NormalizedMerchant ?? rule.MerchantDisplay;
        if (ruleMerchants == null || ruleMerchants.Length == 0)
            return true;

        var txnMerchant = txn.NormalizedMerchant ?? txn.MerchantDisplay;
        bool isTxnEmptyOrNone = string.IsNullOrWhiteSpace(txnMerchant) || string.Equals(txnMerchant, "NONE", StringComparison.OrdinalIgnoreCase);

        bool hasNone = ruleMerchants.Any(v => string.Equals(v, "NONE", StringComparison.OrdinalIgnoreCase));
        bool hasAll = ruleMerchants.Any(v => string.Equals(v, "ALL", StringComparison.OrdinalIgnoreCase));

        if (hasNone && isTxnEmptyOrNone)
            return true;

        if (hasAll && !isTxnEmptyOrNone)
            return true;

        if (!isTxnEmptyOrNone)
        {
            return ruleMerchants.Any(m =>
                string.Equals(m, txn.NormalizedMerchant, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(m, txn.MerchantDisplay, StringComparison.OrdinalIgnoreCase) ||
                (txn.NormalizedMerchant != null && txn.NormalizedMerchant.Contains(m, StringComparison.OrdinalIgnoreCase)) ||
                (txn.MerchantDisplay != null && txn.MerchantDisplay.Contains(m, StringComparison.OrdinalIgnoreCase)));
        }

        return false;
    }

    private static bool MatchesBankOrCard(string[]? ruleValues, string? txnValue)
    {
        if (ruleValues == null || ruleValues.Length == 0)
            return true;

        if (ruleValues.Any(v => string.Equals(v, "ALL", StringComparison.OrdinalIgnoreCase)))
            return true;

        if (string.IsNullOrWhiteSpace(txnValue))
            return false;

        return ruleValues.Any(v => string.Equals(v, txnValue, StringComparison.OrdinalIgnoreCase));
    }

    private ProgramRateResolution ResolveBridgeLegacy(CardRewardProgram program, RewardTransaction txn)
    {
        var winner = _bridgeRules
            .Where(b => b.RulesRewardProgram == program.RewardProgram
                        && WithinDateRange(txn.TransactionDate, b.StartDate, b.EndDate)
                        && MatchesLegacy(b.VpcType, txn.VpcType)
                        && MatchesLegacy(b.MobilePayment, txn.MobilePayment)
                        && MatchesLegacy(b.EcPlatform, txn.EcPlatform)
                        && MatchesLegacy(b.NormalizedMerchant ?? b.MerchantDisplay, txn.NormalizedMerchant ?? txn.MerchantDisplay)
                        && MatchesLegacy(b.MerchantLocation, txn.MerchantLocation))
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

    private static bool MatchesLegacy(string? ruleValue, string? txnValue) =>
        string.IsNullOrEmpty(ruleValue) || ruleValue == txnValue;

    private static bool WithinDateRange(DateOnly date, DateOnly? start, DateOnly? end) =>
        (start is null || date >= start) && (end is null || date <= end);
}
