namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_reward_linked_lists.csv
/// 定義「回饋方案 (RewardId)」與「特店回饋池 (MerchantRewardPoolsId)」的多對多關聯
/// </summary>
public record RewardLinkedList
{
    /// <summary>
    /// 回饋方案唯一識別碼 (對應 dim_card_rewards_base / dim_card_rewards_campaigns 的 RewardId)
    /// </summary>
    public required string RewardId { get; init; }
    /// <summary>
    /// 特店回饋池識別碼 (對應 bridge_reward_pools 的 MerchantRewardPoolsId)
    /// </summary>
    public required string MerchantRewardPoolsId { get; init; }
}
