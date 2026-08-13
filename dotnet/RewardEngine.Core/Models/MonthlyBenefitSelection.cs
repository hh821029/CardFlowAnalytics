namespace RewardEngine.Core.Models;

/// <summary>
/// 對應 bridge_(Unicard類)_selection.csv
/// 月結等級的權益選擇:月底依入帳日確認整個月適用哪個 campaign_reward_program
/// </summary>
public record MonthlyBenefitSelection
{
    public required string RulesRewardProgram { get; init; }     // 之後還是要接回 bridge_reward_rules
    public required string CampaignRewardProgram { get; init; }  // 對應 CardRewardProgram(Source=Campaign).RewardProgram
    public required DateOnly StartDate { get; init; }
    public required DateOnly EndDate { get; init; }
    public required DateOnly MaxPostingDate { get; init; }         // 入帳截止日,決定該筆交易算不算進這個月
}