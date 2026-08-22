namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_reward_pools.json內部不同資料的狀況
/// </summary>

public record MerchantRewardRule
{
    //條件約束：指定特約商店名稱
    public string[]? NormalizedMerchant { get; init; }
    //條件約束：國內外的交易地點
    public string[]? MerchantLocation { get; init; }
    //條件約束：第三方支付
    public string[]? PaymentProcess { get; init; }
    //條件約束：網路交易平台
    public string[]? EcPlatform { get; init; }
    //條件約束：虛擬卡號
    public string[]? VpcType { get; init; }
    //條件約束：卡片名稱
    public string[]? CardId { get; init; }
    //條件約束：卡片類型
    public string[]? CardType { get; init; }
    //條件約束：銀行代號+銀行名稱
    public string[]? BankNo { get; init; }
    public string[]? BankName { get; init; }
    //回饋倍率提供：若不同特店有不同回饋倍率的話，由這裡提供該規則對應的個別回饋倍率
    public decimal? MerchantRate { get; init; }
    //回饋池區間
    public DateOnly? StartDate { get; init; }
    public DateOnly? EndDate { get; init; }
    //備註
    public string? Note { get; init; }
}
