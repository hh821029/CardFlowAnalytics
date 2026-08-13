using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

/// <summary>
/// 管理 4 大 reward_cycle (BILLING_CYCLE, TRANSACTION_DATE, CALENDAR_MONTH, CAMPAIGN_CYCLE)
/// 的循環週期 Key 生成，並進行上限 (cap_amount) 累計與截斷處理
/// </summary>
public class RewardCycleTracker(BillingCycleResolver? billingResolver = null)
{
    private readonly Dictionary<string, decimal> _accumulatedRewards = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, decimal> _accumulatedTxnAmounts = new(StringComparer.OrdinalIgnoreCase);

    public string BuildCycleKey(CardRewardProgram program, RewardTransaction txn)
    {
        string cycleType = (program.RewardCycle ?? "TRANSACTION_DATE").Trim().ToUpperInvariant();

        return cycleType switch
        {
            "BILLING_CYCLE" => BuildBillingCycleKey(program, txn),
            "CALENDAR_MONTH" => $"MONTH_{txn.BankName}_{txn.CardType}_{txn.TransactionDate:yyyy-MM}_{program.RewardProgram}",
            "CAMPAIGN_CYCLE" => $"CAMPAIGN_{program.RewardProgram}_{(program.StartDate?.ToString("yyyyMMdd") ?? "START")}_{(program.EndDate?.ToString("yyyyMMdd") ?? "END")}",
            _ => $"TXN_{txn.TransactionId}_{program.RewardProgram}" // TRANSACTION_DATE: 單筆獨立不跨筆累計
        };
    }

    private string BuildBillingCycleKey(CardRewardProgram program, RewardTransaction txn)
    {
        // BILLING_CYCLE：依據「入帳日 (PostingDate)」落入的帳單區間為準 (SSOT)
        var interval = billingResolver?.ResolveInterval(txn.BankName, txn.CardType, txn.PostingDate);

        string monthKey = interval?.StatementMonth ?? txn.PostingDate.ToString("yyyy-MM");
        return $"BILLING_{txn.BankName}_{(string.IsNullOrEmpty(txn.CardType) ? "DEFAULT" : txn.CardType)}_{monthKey}_{program.RewardProgram}";
    }

    public decimal GetAccumulated(string cycleKey)
    {
        return _accumulatedRewards.TryGetValue(cycleKey, out var val) ? val : 0m;
    }

    public decimal GetAccumulatedTxnAmount(string cycleKey)
    {
        return _accumulatedTxnAmounts.TryGetValue(cycleKey, out var val) ? val : 0m;
    }

    public (decimal AwardedAmount, bool IsCapped) ApplyCapAndAccumulate(
        CardRewardProgram program, RewardTransaction txn, decimal proposedAmount)
    {
        if (!program.CapAmount.HasValue || program.CapAmount.Value <= 0)
        {
            return (proposedAmount, false);
        }

        string cycleKey = BuildCycleKey(program, txn);
        decimal cap = program.CapAmount.Value;
        decimal current = GetAccumulated(cycleKey);

        if (current >= cap)
        {
            return (0m, true);
        }

        decimal awarded = proposedAmount;
        bool isCapped = false;

        if (current + proposedAmount > cap)
        {
            awarded = cap - current;
            isCapped = true;
        }

        _accumulatedRewards[cycleKey] = current + awarded;
        return (awarded, isCapped);
    }

    public (decimal AwardedAmount, bool IsCapped) ApplyAggregateCapAndAccumulate(
        ProgramRateResolution res, RewardTransaction txn)
    {
        var program = res.Program;
        string cycleKey = BuildCycleKey(program, txn);

        decimal oldTxnAmount = GetAccumulatedTxnAmount(cycleKey);
        decimal newTxnAmount = oldTxnAmount + txn.Amount;

        decimal cumulativeRawReward = newTxnAmount * res.EffectiveRate;

        var rewardTypeInfo = RewardTypeInfo.Resolve(program.RewardType);
        string strategy = !string.IsNullOrEmpty(program.RoundStrategy)
            ? program.RoundStrategy
            : rewardTypeInfo.RoundingStrategy;
        int digits = rewardTypeInfo.RoundingDigits;

        decimal expectedCumulativeReward = RoundStrategy.Apply(cumulativeRawReward, strategy, digits);

        decimal oldAwarded = GetAccumulated(cycleKey);
        decimal proposedIncremental = Math.Max(0m, expectedCumulativeReward - oldAwarded);

        decimal awarded = proposedIncremental;
        bool isCapped = false;

        if (program.CapAmount.HasValue && program.CapAmount.Value > 0)
        {
            decimal cap = program.CapAmount.Value;
            if (oldAwarded >= cap)
            {
                awarded = 0m;
                isCapped = true;
            }
            else if (oldAwarded + proposedIncremental > cap)
            {
                awarded = cap - oldAwarded;
                isCapped = true;
            }
        }

        _accumulatedTxnAmounts[cycleKey] = newTxnAmount;
        _accumulatedRewards[cycleKey] = oldAwarded + awarded;

        return (awarded, isCapped);
    }
}
