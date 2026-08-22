namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_reward_pools.json
/// </summary>
public record MerchantRewardPool
{
    //回饋池ID
    public required string MerchantRewardPoolsId { get; init; }
    //回饋池名稱
    public required string PoolName { get; init; }
    //豁免規則：若消費紀錄符合任一規則，則不適用此回饋池的規則
    public required MerchantRewardRule[] PassRules { get; init; }
    //一般規則：若消費紀錄符合任一規則，則會套用此回饋池的回饋倍率（若規則有定義的話），否則沿用原有的回饋倍率
    public required MerchantRewardRule[] Rules { get; init; }
}


