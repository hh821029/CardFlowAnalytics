using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public sealed class MonthlySelectionStrategy(
    IReadOnlyList<MonthlyBenefitSelection> selections,
    string? targetBankName = null,
    string? targetCardType = null) : IBenefitSelectionStrategy
{
    private static bool IsApplicable(RewardTransaction txn, string? bankName, string? cardType)
    {
        // 若未指定目標發卡行/卡別（如單元測試直接測試策略），預設適用所有交易
        if (string.IsNullOrEmpty(bankName) && string.IsNullOrEmpty(cardType))
            return true;

        if (!string.IsNullOrEmpty(bankName))
        {
            bool isBankMatch = txn.BankName.Equals(bankName, StringComparison.OrdinalIgnoreCase) ||
                               (bankName.Equals("esun", StringComparison.OrdinalIgnoreCase) && (txn.BankName.Equals("esun", StringComparison.OrdinalIgnoreCase) || txn.BankName.Contains("玉山")));
            if (!isBankMatch) return false;
        }

        if (!string.IsNullOrEmpty(cardType))
        {
            bool isCardMatch = txn.CardType.Equals(cardType, StringComparison.OrdinalIgnoreCase) ||
                               txn.CardType.Contains(cardType, StringComparison.OrdinalIgnoreCase);
            if (!isCardMatch) return false;
        }

        return true;
    }

    public List<MonthlyBenefitSelection> GetActiveSelections(RewardTransaction transaction)
    {
        if (!IsApplicable(transaction, targetBankName, targetCardType))
        {
            return [];
        }

        var consumptionMonthLastDay = new DateOnly(
            transaction.TransactionDate.Year,
            transaction.TransactionDate.Month,
            DateTime.DaysInMonth(transaction.TransactionDate.Year, transaction.TransactionDate.Month));

        var matches = selections
            .Where(s => consumptionMonthLastDay >= s.StartDate && consumptionMonthLastDay <= s.EndDate)
            .ToList();

        // 依 RulesRewardProgram 分組，檢查是否有同一項目在當月設定了多筆互斥選擇
        var conflicts = matches
            .GroupBy(m => m.RulesRewardProgram)
            .Where(g => g.Count() > 1)
            .ToList();

        if (conflicts.Count > 0)
        {
            var conflictDetails = string.Join("; ", conflicts.Select(g =>
                $"{g.Key}: [{string.Join(", ", g.Select(m => $"{m.CampaignRewardProgram} ({m.StartDate:yyyy-MM-dd}~{m.EndDate:yyyy-MM-dd})"))}]"));
            throw new InvalidOperationException(
                $"交易 {transaction.TransactionId} 消費月 {transaction.TransactionDate:yyyy-MM} 命中多筆月結權益選擇衝突，資料需要人工檢查。衝突項目: {conflictDetails}");
        }

        return matches;
    }

    public BenefitResolutionResult ResolveActiveProgram(RewardTransaction transaction)
    {
        var activeSelections = GetActiveSelections(transaction);
        if (activeSelections.Count == 0)
        {
            return new BenefitResolutionResult
            {
                ResolvedProgram = null,
                RequiresManualVerification = false,
                VerificationReason = null
            };
        }

        var selection = activeSelections[0];

        if (transaction.PostingDate > selection.MaxPostingDate)
        {
            return new BenefitResolutionResult
            {
                ResolvedProgram = null,
                RequiresManualVerification = true,
                VerificationReason =
                    $"交易入帳日 {transaction.PostingDate} 晚於消費月 {transaction.TransactionDate:yyyy-MM} 的請款截止日 " +
                    $"{selection.MaxPostingDate}，是否計入本月回饋(或延後至下期)需人工確認"
            };
        }

        return new BenefitResolutionResult
        {
            ResolvedProgram = selection.RulesRewardProgram,
            RequiresManualVerification = false,
            VerificationReason = null
        };
    }
}