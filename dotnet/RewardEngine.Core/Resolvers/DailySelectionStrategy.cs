using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public sealed class DailySelectionStrategy(
    IReadOnlyList<DailyBenefitSelection> selections,
    string? targetBankName = null,
    string? targetCardType = null) : IBenefitSelectionStrategy
{
    // 跨境交易：無論哪個時區組合（含換日線、iCloud 愛爾蘭 UTC+0 等），
    // 台灣發卡行記錄的消費日與持卡人當地日期最多差 ±1 天
    private const int CrossBorderBufferDays = 1;

    // 行動支付（NFC/QR）：授權→請款批次→銀行入帳，已知延遲最多 2 天
    private const int MobilePaymentBufferDays = 2;

    private static bool IsApplicable(RewardTransaction txn, string? bankName, string? cardType)
    {
        // 若未指定目標發卡行/卡別（如單元測試直接測試策略），預設適用所有交易
        if (string.IsNullOrEmpty(bankName) && string.IsNullOrEmpty(cardType))
            return true;

        if (!string.IsNullOrEmpty(bankName))
        {
            bool isBankMatch = txn.BankName.Equals(bankName, StringComparison.OrdinalIgnoreCase) ||
                               (bankName.Equals("cube", StringComparison.OrdinalIgnoreCase) && (txn.BankName.Equals("cathay", StringComparison.OrdinalIgnoreCase) || txn.BankName.Contains("國泰")));
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

    public BenefitResolutionResult ResolveActiveProgram(RewardTransaction transaction)
    {
        if (!IsApplicable(transaction, targetBankName, targetCardType))
        {
            return new BenefitResolutionResult { ResolvedProgram = null, RequiresManualVerification = false };
        }

        var matches = selections
            .Where(s => transaction.TransactionDate >= s.StartDate && transaction.TransactionDate <= s.EndDate)
            .ToList();

        if (matches.Count > 1)
        {
            throw new InvalidOperationException(
                $"交易 {transaction.TransactionId} 命中多筆每日權益選擇，資料本身重疊，需要人工檢查");
        }

        var resolvedProgram = matches.Count == 1 ? matches[0].BaseRewardProgram : null;

        // 跨境與行動支付使用各自的緩衝天數判斷，互不干擾
        bool crossBorderNearBoundary  = transaction.IsCrossBorder   && IsNearBoundary(transaction.TransactionDate, CrossBorderBufferDays);
        bool mobilePayNearBoundary    = transaction.IsMobilePayment  && IsNearBoundary(transaction.TransactionDate, MobilePaymentBufferDays);
        bool nearBoundary             = crossBorderNearBoundary || mobilePayNearBoundary;

        string? verificationReason = nearBoundary
            ? BuildVerificationReason(crossBorderNearBoundary, mobilePayNearBoundary)
            : null;

        return new BenefitResolutionResult
        {
            ResolvedProgram = resolvedProgram,
            RequiresManualVerification = nearBoundary,
            VerificationReason = verificationReason
        };
    }

    private bool IsNearBoundary(DateOnly transactionDate, int bufferDays) =>
        selections.Any(s =>
            Math.Abs(transactionDate.DayNumber - s.StartDate.DayNumber) <= bufferDays ||
            Math.Abs(transactionDate.DayNumber - s.EndDate.DayNumber)   <= bufferDays);

    private static string BuildVerificationReason(bool isCrossBorder, bool isMobilePay)
    {
        if (isCrossBorder && isMobilePay)
            return "跨境 + 行動支付交易，落在權益切換邊界緩衝期內（跨境 ±1 天 / 行動支付最多 2 天），銀行記錄的消費日可能與實際刷卡日不符";

        if (isCrossBorder)
            return "跨境交易，落在權益切換邊界緩衝期（±1 天）內，銀行記錄消費日可能因時區差異（例：iCloud 愛爾蘭 UTC+0 → 台灣 UTC+8 跨午夜）與實際刷卡日差 1 天";

        return "行動支付交易，落在權益切換邊界緩衝期（2 天）內，銀行記錄消費日可能較實際刷卡日延遲 1-2 天";
    }
}
