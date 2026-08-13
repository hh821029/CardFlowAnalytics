using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 對應 bridge_cube_selections_private.csv（每日權益選擇，Cube/Richart 型）
/// </summary>
public class DailyBenefitSelectionMap : ClassMap<DailyBenefitSelection>
{
    public DailyBenefitSelectionMap()
    {
        Map(m => m.BaseRewardProgram).Name("base_reward_program");
        Map(m => m.StartDate).Name("start_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.EndDate).Name("end_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.Note).Name("備註");
    }
}
