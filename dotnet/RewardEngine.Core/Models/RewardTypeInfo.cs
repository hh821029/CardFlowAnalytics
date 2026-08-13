namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 Python const.py 的 class RewardType(Enum)
/// 定義各種回饋類型(現金、樹點、玉山E point、OpenPoint、LinePoint等)的預設單位、進位策略與小數位數
/// </summary>
public record RewardTypeInfo
{
    public required string RewardTypeName { get; init; }
    public required string RewardUnitName { get; init; }
    public required decimal ConversionRate { get; init; }
    public required string RoundingStrategy { get; init; } // "floor", "round", "ceil"
    public required int RoundingDigits { get; init; }      // 0, 2 等

    public static readonly Dictionary<string, RewardTypeInfo> KnownTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        ["CASHBACK_FLOOR"]   = new() { RewardTypeName = "CASHBACK_FLOOR",   RewardUnitName = "cashback",    ConversionRate = 1.0m, RoundingStrategy = "floor", RoundingDigits = 0 },
        ["CASHBACK_ROUND"]   = new() { RewardTypeName = "CASHBACK_ROUND",   RewardUnitName = "cashback",    ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["TREEPOINTS"]       = new() { RewardTypeName = "TREEPOINTS",       RewardUnitName = "tree_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["ESUNPOINT_FLOOR"]  = new() { RewardTypeName = "ESUNPOINT_FLOOR",  RewardUnitName = "e_points",    ConversionRate = 1.0m, RoundingStrategy = "floor", RoundingDigits = 0 },
        ["ESUNPOINT_ROUND"]  = new() { RewardTypeName = "ESUNPOINT_ROUND",  RewardUnitName = "e_points",    ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["OPENPOINT"]        = new() { RewardTypeName = "OPENPOINT",        RewardUnitName = "openpoint",   ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 2 },
        ["LINEPOINT"]        = new() { RewardTypeName = "LINEPOINT",        RewardUnitName = "line_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["HAMIPOINT"]        = new() { RewardTypeName = "HAMIPOINT",        RewardUnitName = "hami_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },

        // CSV 底層常使用的 lower_snake_case 別名
        ["cashback_floor"]   = new() { RewardTypeName = "CASHBACK_FLOOR",   RewardUnitName = "cashback",    ConversionRate = 1.0m, RoundingStrategy = "floor", RoundingDigits = 0 },
        ["cashback_round"]   = new() { RewardTypeName = "CASHBACK_ROUND",   RewardUnitName = "cashback",    ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["tree_points"]      = new() { RewardTypeName = "TREEPOINTS",       RewardUnitName = "tree_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["esun_points_floor"]= new() { RewardTypeName = "ESUNPOINT_FLOOR",  RewardUnitName = "e_points",    ConversionRate = 1.0m, RoundingStrategy = "floor", RoundingDigits = 0 },
        ["esun_points_round"]= new() { RewardTypeName = "ESUNPOINT_ROUND",  RewardUnitName = "e_points",    ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["openpoint"]        = new() { RewardTypeName = "OPENPOINT",        RewardUnitName = "openpoint",   ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 2 },
        ["line_points"]      = new() { RewardTypeName = "LINEPOINT",        RewardUnitName = "line_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 },
        ["hami_points"]      = new() { RewardTypeName = "HAMIPOINT",        RewardUnitName = "hami_points", ConversionRate = 1.0m, RoundingStrategy = "round", RoundingDigits = 0 }
    };

    public static RewardTypeInfo Resolve(string? rewardType)
    {
        if (!string.IsNullOrEmpty(rewardType) && KnownTypes.TryGetValue(rewardType, out var info))
            return info;

        return new RewardTypeInfo
        {
            RewardTypeName = rewardType ?? "DEFAULT",
            RewardUnitName = "cashback",
            ConversionRate = 1.0m,
            RoundingStrategy = "round",
            RoundingDigits = 0
        };
    }
}
