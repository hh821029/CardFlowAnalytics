namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_reward_rules.csv
/// 定義「在什麼消費情境(通路/商家/期間)下，某個 RewardProgram 適用什麼費率」
/// </summary>
public record RewardBridgeRule
{
    public required string RulesRewardProgram { get; init; }     // Left Join key → CardRewardProgram.RewardProgram
    public string? VpcType { get; init; }
    public string? MobilePayment { get; init; }
    public string? EcPlatform { get; init; }
    public string? MerchantDisplay { get; init; }
    public string? MerchantLocation { get; init; }
    public DateOnly? StartDate { get; init; }
    public DateOnly? EndDate { get; init; }
    /// <summary>
    /// CSV 允許空白：代表此行只做條件判斷（如 break 戳斷），實際費率不覆蓋、回退由 Program 本身的 RewardRate 決定
    /// </summary>
    public decimal? MerchantRate { get; init; }
    public required int Priority { get; init; }
    public required bool RewardCalBreak { get; init; }            // ❗️ 語意待確認，見下方
}
