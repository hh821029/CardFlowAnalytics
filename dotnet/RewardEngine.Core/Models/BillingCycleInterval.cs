namespace RewardEngine.Core.Models;

/// <summary>
/// 結帳歷史表計算出之單一帳單期適用區間 [IntervalStart, IntervalEnd]
/// </summary>
public record BillingCycleInterval
{
    public required string BankName { get; init; }
    public string? CardType { get; init; }
    public required string StatementMonth { get; init; }
    public required DateOnly IntervalStart { get; init; }
    public required DateOnly IntervalEnd { get; init; }
}
