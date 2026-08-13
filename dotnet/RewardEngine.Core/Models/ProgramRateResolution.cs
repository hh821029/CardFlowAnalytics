namespace RewardEngine.Core.Models;

/// <summary>
/// 單一 Program 解析出的最終適用費率(Stage 3 的輸出單位)
/// </summary>
public record ProgramRateResolution
{
    public required CardRewardProgram Program { get; init; }
    public RewardBridgeRule? MatchedBridgeRule { get; init; }   // null = 沒有更細的通路/商家覆蓋，退回用 Program 本身的 RewardRate
    public required decimal EffectiveRate { get; init; }
    public decimal CalculatedRewardAmount { get; init; }        // 進位/捨去與 CapAmount 截斷後的最終計算金額
    public bool IsCapped { get; init; }                         // 是否因達 CapAmount 上限而被截斷
    public bool BreakTriggered => MatchedBridgeRule?.RewardCalBreak ?? false;
}