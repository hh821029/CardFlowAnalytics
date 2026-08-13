using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 對應 bridge_unicard_selections_private.csv（月結權益選擇，Unicard 型）
/// </summary>
public class MonthlyBenefitSelectionMap : ClassMap<MonthlyBenefitSelection>
{
    public MonthlyBenefitSelectionMap()
    {
        Map(m => m.RulesRewardProgram).Name("rules_reward_program");
        Map(m => m.CampaignRewardProgram).Name("campaign_reward_program");
        Map(m => m.StartDate).Name("start_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.EndDate).Name("end_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.MaxPostingDate).Name("max_posting_date").TypeConverterOption.Format("yyyy-MM-dd");
    }
}
