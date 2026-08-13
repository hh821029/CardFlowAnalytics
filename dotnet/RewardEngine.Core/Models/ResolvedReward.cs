namespace RewardEngine.Core.Models;


/// <summary>
/// 一筆交易最終產出的回饋結果(Stage 4 之後，下游 RFM/報表只讀這個)
/// </summary>
public record ResolvedReward
{
    public required string TransactionId { get; init; }
    public required IReadOnlyList<ProgramRateResolution> AppliedPrograms { get; init; }
    public required decimal TotalRewardAmount { get; init; }
}
