using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

/// <summary>
/// 處理回饋金進位與捨去邏輯（支援 floor, round, ceil 及指定小數位數）
/// </summary>
public static class RoundStrategy
{
    public static decimal Apply(decimal amount, string? strategy, int digits = 0)
    {
        var factor = (decimal)Math.Pow(10, digits);
        var scaled = amount * factor;

        string normalized = (strategy ?? "round").Trim().ToLowerInvariant();

        decimal roundedScaled = normalized switch
        {
            "floor" or "down" => Math.Floor(scaled),
            "ceil" or "ceiling" or "up" => Math.Ceiling(scaled),
            _ => Math.Round(scaled, 0, MidpointRounding.AwayFromZero)
        };

        return roundedScaled / factor;
    }

    public static decimal CalculateResolutionReward(decimal txnAmount, ProgramRateResolution resolution)
    {
        var rawReward = txnAmount * resolution.EffectiveRate;
        var program = resolution.Program;

        var rewardTypeInfo = RewardTypeInfo.Resolve(program.RewardType);
        
        // 優先採用 Program 設定的 RoundStrategy；若無則採用 RewardTypeInfo 的預設進位策略
        string strategy = !string.IsNullOrEmpty(program.RoundStrategy)
            ? program.RoundStrategy
            : rewardTypeInfo.RoundingStrategy;

        int digits = rewardTypeInfo.RoundingDigits;

        return Apply(rawReward, strategy, digits);
    }
}
