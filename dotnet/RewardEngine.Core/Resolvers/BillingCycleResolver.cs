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
                Bank: (r.BankNo ?? r.BankName ?? "").Trim().ToLowerInvariant(),
                Card: (r.CardId ?? r.CardType ?? "").Trim().ToLowerInvariant()
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
                    BankNo = curr.BankNo,
                    BankName = curr.BankName,
                    CardId = curr.CardId,
                    CardType = curr.CardType,
                    StatementMonth = curr.StatementMonth,
                    IntervalStart = start,
                    IntervalEnd = currClose
                });
            }
        }
    }

    public BillingCycleInterval? ResolveInterval(string bankNo, string? cardId, DateOnly transactionDate)
    {
        var normBank = (bankNo ?? "").Trim().ToLowerInvariant();
        var normCard = (cardId ?? "").Trim().ToLowerInvariant();

        // 1. 優先比對特定卡別 (bankNo + cardId，兼顧 BankName / CardType 容錯)
        if (!string.IsNullOrEmpty(normCard))
        {
            var match = _intervals.FirstOrDefault(i =>
                MatchBank(i, normBank) &&
                MatchCard(i, normCard) &&
                transactionDate >= i.IntervalStart && transactionDate <= i.IntervalEnd);

            if (match != null) return match;
        }

        // 2. 次優先比對銀行通用預設 (CardId/CardType 為空)
        return _intervals.FirstOrDefault(i =>
            MatchBank(i, normBank) &&
            string.IsNullOrEmpty(i.CardId) && string.IsNullOrEmpty(i.CardType) &&
            transactionDate >= i.IntervalStart && transactionDate <= i.IntervalEnd);
    }

    private static bool MatchBank(BillingCycleInterval i, string normBank) =>
        (!string.IsNullOrEmpty(i.BankNo) && i.BankNo.Trim().ToLowerInvariant() == normBank) ||
        (!string.IsNullOrEmpty(i.BankName) && i.BankName.Trim().ToLowerInvariant() == normBank);

    private static bool MatchCard(BillingCycleInterval i, string normCard) =>
        (!string.IsNullOrEmpty(i.CardId) && i.CardId.Trim().ToLowerInvariant() == normCard) ||
        (!string.IsNullOrEmpty(i.CardType) && i.CardType.Trim().ToLowerInvariant() == normCard);
}
