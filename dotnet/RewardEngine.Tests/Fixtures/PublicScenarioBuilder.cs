using RewardEngine.Core.Models;

namespace RewardEngine.Tests.Fixtures;

public static class ScenarioBuilder
{
    // ---------- CardRewardProgram ----------

    public static CardRewardProgram BaseProgram(
        string program,
        decimal rate,
        string bankName = "TestBank",
        string cardType = "TestCard",
        bool isCurrentBenefit = true,
        DateOnly? startDate = null,
        DateOnly? endDate = null,
        string calcMethod = "PER_ITEM",
        string roundStrategy = "round",
        string rewardCycle = "monthly",
        string rewardType = "cashback") => new()
    {
        BankName = bankName,
        CardType = cardType,
        IsCurrentBenefit = isCurrentBenefit,
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
        string bankName = "TestBank",
        string cardType = "TestCard",
        bool isCurrentBenefit = true,
        DateOnly? startDate = null,
        DateOnly? endDate = null,
        string calcMethod = "PER_ITEM",
        string roundStrategy = "round",
        string rewardCycle = "monthly",
        string rewardType = "cashback") => new()
    {
        BankName = bankName,
        CardType = cardType,
        IsCurrentBenefit = isCurrentBenefit,
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

    // ---------- RewardBridgeRule ----------

    public static RewardBridgeRule BridgeRule(
        string rulesRewardProgram,
        decimal merchantRate,
        int priority = 0,
        bool rewardCalBreak = false,
        string? vpcType = null,
        string? mobilePayment = null,
        string? ecPlatform = null,
        string? merchantDisplay = null,
        string? merchantLocation = null,
        DateOnly? startDate = null,
        DateOnly? endDate = null) => new()
    {
        RulesRewardProgram = rulesRewardProgram,
        MerchantRate = merchantRate,
        Priority = priority,
        RewardCalBreak = rewardCalBreak,
        VpcType = vpcType,
        MobilePayment = mobilePayment,
        EcPlatform = ecPlatform,
        MerchantDisplay = merchantDisplay,
        MerchantLocation = merchantLocation,
        StartDate = startDate,
        EndDate = endDate
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
        string bankName = "TestBank",
        string cardType = "TestCard",
        string cardNo = "0000",
        string? vpcNo = null,
        string? vpcType = null,
        DateOnly? postingDate = null,
        string transactionType = "交易",
        string? mobilePayment = null,
        string? ecPlatform = null,
        string? merchantDisplay = null,
        string? merchantLocation = null) => new()
    {
        TransactionId = transactionId,
        BankName = bankName,
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
        MerchantLocation = merchantLocation
    };
}