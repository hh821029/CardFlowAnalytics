using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public sealed class RewardResolver
{
    private readonly IReadOnlyList<CardRewardProgram> _programs;
    private readonly IReadOnlyList<MerchantRewardPool> _pools;
    private readonly IReadOnlyList<RewardLinkedList> _linkedLists;
    private readonly IBenefitSelectionStrategy? _dailySelection;
    private readonly IBenefitSelectionStrategy? _monthlySelection;
    private readonly RewardCycleTracker? _cycleTracker;
    private readonly Dictionary<string, List<MerchantRewardPool>> _rewardPoolsLookup;

    /// <summary>
    /// 全新回饋池架構建構函式 (RewardPools + RewardLinkedLists)
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
        _dailySelection = dailySelection;
        _monthlySelection = monthlySelection;
        _cycleTracker = cycleTracker;

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

    public ResolvedReward Resolve(RewardTransaction txn)
    {
        var trace = new List<string>();

        // Stage 0：每日權益選擇閘門（僅選擇制卡片如 CUBE 有值）
        var dailyRes = _dailySelection?.ResolveActiveProgram(txn);
        var lockedBasePrograms = dailyRes?.ResolvedPrograms ?? (dailyRes?.ResolvedProgram != null ? [dailyRes.ResolvedProgram] : null);

        if (lockedBasePrograms != null && lockedBasePrograms.Count > 0)
            trace.Add($"[S0-每日權益] 命中={string.Join(",", lockedBasePrograms)}" +
                      (dailyRes?.RequiresManualVerification == true ? $" ⚠️{dailyRes.VerificationReason}" : ""));
        else if (_dailySelection != null)
            trace.Add("[S0-每日權益] 無命中（未在任何選擇區間內）");

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

            if (p.Source == RewardProgramSource.Base && lockedBasePrograms != null && lockedBasePrograms.Count > 0 &&
                !lockedBasePrograms.Any(lp => string.Equals(p.RewardProgram, lp, StringComparison.OrdinalIgnoreCase)))
                return false;

            return true;
        }).ToList();

        trace.Add($"[S1-候選方案] 共{candidates.Count}筆：" +
                  string.Join(" | ", candidates.Select(p => $"{p.RewardProgram}(pri={p.Priority},{p.Source})")));

        // Stage 2 & 3：回饋池費率解析
        var candidateResolutions = new List<ProgramRateResolution>();
        foreach (var prog in candidates)
        {
            var res = EvaluateProgramWithPools(prog, txn);
            if (res != null)
            {
                candidateResolutions.Add(res);
                trace.Add($"[S2/3-回饋池] ✅ {prog.RewardProgram} → 池:{res.MatchedPool?.PoolName ?? "無池(全通路)"} | 費率:{res.EffectiveRate:F4}% | 原始金額:{res.CalculatedRewardAmount:F2}");
            }
            else
            {
                trace.Add($"[S2/3-回饋池] ❌ {prog.RewardProgram} → 未命中任何池規則，略過");
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

                var beforeCount = candidateResolutions.Count;
                candidateResolutions = candidateResolutions
                    .Where(r =>
                    {
                        var campProg = r.Program.RewardProgram;
                        if (targetSelectionRules.Contains(campProg))
                        {
                            return selectedCampaignPrograms.Contains(campProg);
                        }
                        return true;
                    })
                    .ToList();

                trace.Add($"[S4-月結篩選] 選擇:{string.Join(",", selectedCampaignPrograms)} | 過濾前:{beforeCount}筆 → 後:{candidateResolutions.Count}筆");
            }
            else
            {
                trace.Add("[S4-月結篩選] 無月結選擇區間命中，略過篩選");
            }
        }

        // Stage 5：Waterfall 優先序排序與短路截斷（Priority 升冪，數字越小越優先）
        var applied = new List<ProgramRateResolution>();
        foreach (var res in candidateResolutions.OrderBy(r => r.Program.Priority))
        {
            applied.Add(res);
            if (res.BreakTriggered)
            {
                trace.Add($"[S5-Waterfall] 加入:{res.Program.RewardProgram}(pri={res.Program.Priority}) ⛔ reward_cal_break=TRUE，截斷後續計算");
                break;
            }
            trace.Add($"[S5-Waterfall] 加入:{res.Program.RewardProgram}(pri={res.Program.Priority}) → 繼續");
        }

        if (applied.Count == 0)
            trace.Add("[S5-Waterfall] ⚠️ 無任何方案通過，最終 applied 為空");

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
                trace.Add($"[S6-週期上限] {res.Program.RewardProgram} → 計算:{res.CalculatedRewardAmount:F2} → 發放:{awarded:F2}" +
                          (isCapped ? " ⚠️ 已達上限截斷" : ""));
            }
            else
            {
                finalApplied.Add(res);
            }
        }

        var total = finalApplied.Sum(a => a.CalculatedRewardAmount);
        trace.Add($"[最終結果] 合計回饋:{total:F2} | 套用方案數:{finalApplied.Count}");

        return new ResolvedReward
        {
            TransactionId = txn.TransactionId,
            AppliedPrograms = finalApplied,
            TotalRewardAmount = total,
            StageTrace = trace
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
        // rule.BankNo 與 rule.BankName 是同一個銀行身份的兩種表達（代號 vs 名稱）。
        // txn.BankNo 可能為 null（資料庫無此欄位），因此兩者合併以 OR 比對：
        // 交易只要通過「代號清單」或「名稱清單」其中一邊即視為銀行符合。
        bool hasBankNoRule = rule.BankNo != null && rule.BankNo.Length > 0;
        bool hasBankNameRule = rule.BankName != null && rule.BankName.Length > 0;
        if (hasBankNoRule || hasBankNameRule)
        {
            bool bankNoOk   = hasBankNoRule   && (MatchesBankOrCard(rule.BankNo, txn.BankNo) || MatchesBankOrCard(rule.BankNo, txn.BankName));
            bool bankNameOk = hasBankNameRule && MatchesBankOrCard(rule.BankName, txn.BankName);
            if (!bankNoOk && !bankNameOk)
                return false;
        }

        // 卡別：CardId 與 CardType 同理，兩者互為別名，OR 合併比對
        bool hasCardIdRule   = rule.CardId != null && rule.CardId.Length > 0;
        bool hasCardTypeRule = rule.CardType != null && rule.CardType.Length > 0;
        if (hasCardIdRule || hasCardTypeRule)
        {
            bool cardIdOk   = hasCardIdRule   && (MatchesBankOrCard(rule.CardId, txn.CardId) || MatchesBankOrCard(rule.CardId, txn.CardType));
            bool cardTypeOk = hasCardTypeRule && MatchesBankOrCard(rule.CardType, txn.CardType);
            if (!cardIdOk && !cardTypeOk)
                return false;
        }


        // 3. 管道與行為屬性（支援 ALL / NONE / 清單比對）
        if (!MatchesBehaviorField(rule.PaymentProcess, txn.PaymentProcess ?? txn.MobilePayment))
            return false;
        if (!MatchesBehaviorField(rule.EcPlatform, txn.EcPlatform))
            return false;
        if (!MatchesVpcField(rule.VpcType, txn.VpcType))
            return false;

        // 4. 地理/國別限制
        if (!MatchesLocationField(rule.MerchantLocation, txn.MerchantLocation))
            return false;

        // 5. 特約商店名稱 (NormalizedMerchant / MerchantDisplay)
        if (!MatchesMerchantField(rule, txn))
            return false;

        return true;
    }

    private static bool MatchesVpcField(string[]? ruleValues, string? txnValue)
    {
        if (ruleValues == null || ruleValues.Length == 0)
            return true; // 完全不限制 (Wildcard)

        bool hasNone = ruleValues.Any(v => string.Equals(v, "NONE", StringComparison.OrdinalIgnoreCase));
        bool hasAll = ruleValues.Any(v => string.Equals(v, "ALL", StringComparison.OrdinalIgnoreCase));

        // 對於 vpc_type，"CARD" 代表實體卡一般消費（無使用虛擬卡/Token VPC），在限制規則中等同於無虛擬卡 (NONE/空值)
        bool isTxnNoVpc = string.IsNullOrWhiteSpace(txnValue) ||
                          string.Equals(txnValue, "NONE", StringComparison.OrdinalIgnoreCase) ||
                          string.Equals(txnValue, "CARD", StringComparison.OrdinalIgnoreCase);

        if (hasNone && isTxnNoVpc)
            return true;

        if (hasAll && !isTxnNoVpc)
            return true;

        if (!string.IsNullOrWhiteSpace(txnValue))
        {
            return ruleValues.Any(v => string.Equals(v, txnValue, StringComparison.OrdinalIgnoreCase));
        }

        return false;
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

    private static bool WithinDateRange(DateOnly date, DateOnly? start, DateOnly? end) =>
        (start is null || date >= start) && (end is null || date <= end);
}
