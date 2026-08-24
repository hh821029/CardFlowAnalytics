namespace RewardEngine.Core.Models;


/// <summary>
/// 一筆交易最終產出的回饋結果(Stage 4 之後，下游 RFM/報表只讀這個)
/// </summary>
public record ResolvedReward
{
    public required string TransactionId { get; init; }
    public required IReadOnlyList<ProgramRateResolution> AppliedPrograms { get; init; }
    public required decimal TotalRewardAmount { get; init; }

    /// <summary>
    /// 各 Stage 的中間配對過程紀錄，僅供 Debug / 稽核用，不影響計算結果
    /// </summary>
    public IReadOnlyList<string> StageTrace { get; init; } = [];
}
