namespace RewardEngine.Core.Models;

/// <summary>
/// 單一 Program 解析出的最終適用費率(Stage 3 的輸出單位)
/// </summary>
public record ProgramRateResolution
{
    public required CardRewardProgram Program { get; init; }
    public MerchantRewardPool? MatchedPool { get; init; }       // 命中的特店回饋池
    public MerchantRewardRule? MatchedRule { get; init; }       // 命中的池內規則
    public required decimal EffectiveRate { get; init; }
    public decimal CalculatedRewardAmount { get; init; }        // 進位/捨去與 CapAmount 截斷後的最終計算金額
    public bool IsCapped { get; init; }                         // 是否因達 CapAmount 上限而被截斷
    public bool BreakTriggered => Program.RewardCalBreak;
}