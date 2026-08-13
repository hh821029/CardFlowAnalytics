using RewardEngine.Core.Models;

namespace RewardEngine.Core.Resolvers;

public interface IBenefitSelectionStrategy
{
    /// <summary>
    /// 回傳這筆交易當下「唯一生效」的 program 識別碼；沒有選擇制或找不到對應資料回傳 null
    /// </summary>
    BenefitResolutionResult ResolveActiveProgram(RewardTransaction transaction);
}

