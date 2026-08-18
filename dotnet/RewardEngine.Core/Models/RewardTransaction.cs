namespace RewardEngine.Core.Models;

/// <summary>
/// 對應交易當下需要拿來比對規則的欄位(從 Bills.db 讀出後轉換而來)
/// </summary>
public record RewardTransaction
{
    public required string TransactionId { get; init; }
    public required string BankName { get; init; }
    public required string CardType { get; init; }
    public required string CardNo { get; init; }    
    public string? VpcNo { get; init; }
    public required DateOnly TransactionDate { get; init; }   // 消費日 → Cube/Richart 用這個查
    public required DateOnly PostingDate { get; init; }        // 入帳日 → Unicard 用這個查
    public required decimal Amount { get; init; }
    public string? VpcType { get; init; }
    public string? MobilePayment { get; init; }
    public string? EcPlatform { get; init; }
    public string? Merchant { get; init; }
    public string? NormalizedMerchant { get; init; }
    public string? MerchantDisplay { get; init; }
    public string? MerchantLocation { get; init; }
    public string? TransactionType { get; init; }

    private static readonly HashSet<string> _crossBorderTypes =
        ["一般國外交易", "台幣跨境交易", "一般雙幣交易"];

    public bool IsCrossBorder =>
        TransactionType is not null && _crossBorderTypes.Contains(TransactionType);
    public bool IsMobilePayment => MobilePayment != null;
}