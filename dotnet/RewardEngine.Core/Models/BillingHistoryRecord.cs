namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 configs/dim_billing_history_private.csv (或 dim_billing_history.csv)
/// 記錄每張卡片/銀行各帳單月份的預定與實際結帳日 (SSOT 單一事實來源)
/// </summary>
public record BillingHistoryRecord
{
    public required string BankName { get; init; }
    public string? CardType { get; init; }                    // 空白代表適用該銀行的預設結帳日
    public required string StatementMonth { get; init; }       // 如 "2025-01" 或 "2025-01-01"
    public DateOnly? ClosingDate { get; init; }               // 預定結帳日
    public DateOnly? ActualClosingDate { get; init; }         // 實際結帳日 (若空白則回退使用 ClosingDate)

    /// <summary>
    /// 最終採計的結帳日 (ActualClosingDate ?? ClosingDate)
    /// </summary>
    public DateOnly? EffectiveClosingDate => ActualClosingDate ?? ClosingDate;
}
