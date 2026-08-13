namespace RewardEngine.Core.Models;

public enum RewardProgramSource
{
    Base,       // dim_card_rewards_base.csv
    Campaign    // dim_card_rewards_campaigns.csv(含 _private 合併資料)
}

/// <summary>
/// 對應 dim_card_rewards_base.csv 與 dim_card_rewards_campaigns.csv
/// </summary>
public record CardRewardProgram
{
    public required string BankName { get; init; }
    public required string CardType { get; init; }
    public bool IsCurrentBenefit { get; init; } = true;          // 是否為當前消費權益（可選，預設 true）
    public required string RewardProgram { get; init; }           // base_/campaign_reward_program
    public required RewardProgramSource Source { get; init; }
    /// <summary>
    /// CSV 允許空白（代表該 Program 本身無固定費率，完全依賴 BridgeRule 的 MerchantRate 覆蓋）
    /// </summary>
    public decimal? RewardRate { get; init; }                     // base_/campaign_reward_rate
    public string? RewardCycle { get; init; }                     // 先用 string，等確認列舉值再收斂成 enum
    public decimal? MinSingleTransaction { get; init; }
    public decimal? CapAmount { get; init; }
    public DateOnly? StartDate { get; init; }
    public DateOnly? EndDate { get; init; }
    public DateOnly? MaxPostingDate { get; init; }
    public string? RewardType { get; init; }
    public string? CalcMethod { get; init; }
    public string? RoundStrategy { get; init; }
}










