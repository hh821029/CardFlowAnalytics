namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_(Cube/Richart類)_selection.csv
/// 消費日等級的權益選擇:查「這一天」生效的是哪個 base_reward_program
/// </summary>
public record DailyBenefitSelection
{
    public required string BaseRewardProgram { get; init; }   // 對應 CardRewardProgram(Source=Base).RewardProgram
    public required DateOnly StartDate { get; init; }          // 該次選擇的生效起始日
    public required DateOnly EndDate { get; init; }             // 該次選擇的生效結束日(換權益前一天)
    public string? Note { get; init; }
}