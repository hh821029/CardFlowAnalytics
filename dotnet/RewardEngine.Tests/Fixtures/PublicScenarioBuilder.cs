using RewardEngine.Core.Models;

namespace RewardEngine.Tests.Fixtures;

public static class ScenarioBuilder
{
    // ---------- CardRewardProgram ----------

    public static CardRewardProgram BaseProgram(
        string program,
        decimal rate,
        string rewardId = "",
        string bankNo = "000",
        string bankName = "TestBank",
        string cardId = "",
        string cardType = "",
        int priority = 999,
        bool rewardCalBreak = true,
        DateOnly? startDate = null,
        DateOnly? endDate = null,
        string calcMethod = "PER_ITEM",
        string roundStrategy = "round",
        string rewardCycle = "monthly",
        string rewardType = "cashback") => new()
    {
        RewardId = string.IsNullOrEmpty(rewardId) ? $"base_{program}" : rewardId,
        BankNo = bankNo,
        BankName = bankName,
        CardId = cardId,
        CardType = cardType,
        Priority = priority,
        RewardCalBreak = rewardCalBreak,
        RewardProgram = program,
        Source = RewardProgramSource.Base,
        RewardRate = rate,
        RewardCycle = rewardCycle,
        StartDate = startDate,
        EndDate = endDate,
        RewardType = rewardType,
        CalcMethod = calcMethod,
        RoundStrategy = roundStrategy
    };

    public static CardRewardProgram CampaignProgram(
        string program,
        decimal rate,
        string rewardId = "",
        string bankNo = "000",
        string bankName = "TestBank",
        string cardId = "",
        string cardType = "",
        int priority = 400,
        bool rewardCalBreak = false,
        DateOnly? startDate = null,
        DateOnly? endDate = null,
        string calcMethod = "PER_ITEM",
        string roundStrategy = "round",
        string rewardCycle = "monthly",
        string rewardType = "cashback") => new()
    {
        RewardId = string.IsNullOrEmpty(rewardId) ? $"camp_{program}" : rewardId,
        BankNo = bankNo,
        BankName = bankName,
        CardId = cardId,
        CardType = cardType,
        Priority = priority,
        RewardCalBreak = rewardCalBreak,
        RewardProgram = program,
        Source = RewardProgramSource.Campaign,
        RewardRate = rate,
        RewardCycle = rewardCycle,
        StartDate = startDate,
        EndDate = endDate,
        RewardType = rewardType,
        CalcMethod = calcMethod,
        RoundStrategy = roundStrategy
    };

    // ---------- MerchantRewardPool & RewardLinkedList ----------

    public static MerchantRewardPool Pool(
        string poolId,
        string poolName = "",
        MerchantRewardRule[]? passRules = null,
        MerchantRewardRule[]? rules = null) => new()
    {
        MerchantRewardPoolsId = poolId,
        PoolName = string.IsNullOrEmpty(poolName) ? poolId : poolName,
        PassRules = passRules ?? [],
        Rules = rules ?? []
    };

    public static RewardLinkedList Link(string rewardId, string poolId) => new()
    {
        RewardId = rewardId,
        MerchantRewardPoolsId = poolId
    };


    // ---------- DailyBenefitSelection (Cube/Richart 型) ----------

    public static DailyBenefitSelection DailySelection(
        string baseRewardProgram,
        DateOnly startDate,
        DateOnly endDate,
        string? note = null) => new()
    {
        BaseRewardProgram = baseRewardProgram,
        StartDate = startDate,
        EndDate = endDate,
        Note = note
    };

    // ---------- MonthlyBenefitSelection (Unicard 型) ----------

    public static MonthlyBenefitSelection MonthlySelection(
        string rulesRewardProgram,
        string campaignRewardProgram,
        DateOnly startDate,
        DateOnly endDate,
        DateOnly maxPostingDate) => new()
    {
        RulesRewardProgram = rulesRewardProgram,
        CampaignRewardProgram = campaignRewardProgram,
        StartDate = startDate,
        EndDate = endDate,
        MaxPostingDate = maxPostingDate
    };

    // ---------- RewardTransaction ----------

    public static RewardTransaction Transaction(
        string transactionId,
        DateOnly transactionDate,
        decimal amount,
        string? bankNo = null,
        string bankName = "TestBank",
        string? cardId = null,
        string cardType = "TestCard",
        string cardNo = "0000",
        string? vpcNo = null,
        string? vpcType = null,
        DateOnly? postingDate = null,
        string transactionType = "交易",
        string? mobilePayment = null,
        string? ecPlatform = null,
        string? merchantDisplay = null,
        string? merchantLocation = null,
        string? normalizedMerchant = null) => new()
    {
        TransactionId = transactionId,
        BankNo = bankNo,
        BankName = bankName,
        CardId = cardId,
        CardType = cardType,
        CardNo = cardNo,
        VpcNo = vpcNo,
        VpcType = vpcType,
        TransactionDate = transactionDate,
        PostingDate = postingDate ?? transactionDate.AddDays(1),
        TransactionType = transactionType,
        Amount = amount,
        MobilePayment = mobilePayment,
        EcPlatform = ecPlatform,
        MerchantDisplay = merchantDisplay,
        NormalizedMerchant = normalizedMerchant,
        MerchantLocation = merchantLocation
    };
}