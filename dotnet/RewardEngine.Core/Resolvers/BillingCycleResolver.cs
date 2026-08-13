using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

/// <summary>
/// 以 dim_billing_history_private.csv 做為 SSOT (單一事實來源) 的結帳期與區間解析器
/// 根據 (bank_name, card_type, statement_month) 產出 [IntervalStart, IntervalEnd]
/// </summary>
public class BillingCycleResolver
{
    private readonly List<BillingCycleInterval> _intervals = [];

    public BillingCycleResolver(IEnumerable<BillingHistoryRecord> records)
    {
        var groups = records
            .Where(r => r.EffectiveClosingDate.HasValue)
            .GroupBy(r => (
                Bank: r.BankName.Trim().ToLowerInvariant(),
                Card: (r.CardType ?? "").Trim().ToLowerInvariant()
            ));

        foreach (var group in groups)
        {
            var sorted = group
                .OrderBy(r => r.StatementMonth)
                .ToList();

            for (int i = 0; i < sorted.Count; i++)
            {
                var curr = sorted[i];
                var currClose = curr.EffectiveClosingDate!.Value;

                DateOnly start;
                if (i > 0)
                {
                    var prevClose = sorted[i - 1].EffectiveClosingDate!.Value;
                    start = prevClose.AddDays(1);
                }
                else
                {
                    start = currClose.AddMonths(-1).AddDays(1);
                }

                _intervals.Add(new BillingCycleInterval
                {
                    BankName = curr.BankName,
                    CardType = curr.CardType,
                    StatementMonth = curr.StatementMonth,
                    IntervalStart = start,
                    IntervalEnd = currClose
                });
            }
        }
    }

    public BillingCycleInterval? ResolveInterval(string bankName, string? cardType, DateOnly transactionDate)
    {
        var normBank = bankName.Trim().ToLowerInvariant();
        var normCard = (cardType ?? "").Trim().ToLowerInvariant();

        // 1. 優先比對特定卡別 (bankName + cardType)
        var match = _intervals.FirstOrDefault(i =>
            i.BankName.Equals(normBank, StringComparison.OrdinalIgnoreCase) &&
            !string.IsNullOrEmpty(i.CardType) &&
            i.CardType.Equals(normCard, StringComparison.OrdinalIgnoreCase) &&
            transactionDate >= i.IntervalStart && transactionDate <= i.IntervalEnd);

        if (match != null) return match;

        // 2. 次優先比對銀行通用預設 (CardType 為空)
        return _intervals.FirstOrDefault(i =>
            i.BankName.Equals(normBank, StringComparison.OrdinalIgnoreCase) &&
            string.IsNullOrEmpty(i.CardType) &&
            transactionDate >= i.IntervalStart && transactionDate <= i.IntervalEnd);
    }
}
