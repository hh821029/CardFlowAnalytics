using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 對應 dim_card_rewards_base.csv
/// 欄標: bank_name, card_type, 是否為當前消費權益, base_reward_program, base_reward_rate, ...
/// </summary>
public class BaseCardRewardProgramMap : ClassMap<CardRewardProgram>
{
    public BaseCardRewardProgramMap()
    {
        Map(m => m.BankName).Name("bank_name");
        Map(m => m.CardType).Name("card_type");
        Map(m => m.IsCurrentBenefit).Name("是否為當前消費權益").Optional();
        Map(m => m.RewardProgram).Name("base_reward_program");
        Map(m => m.RewardRate).Name("base_reward_rate");
        Map(m => m.RewardCycle).Name("reward_cycle");
        Map(m => m.MinSingleTransaction).Name("min_single_transaction");
        Map(m => m.CapAmount).Name("cap_amount");
        Map(m => m.RewardType).Name("reward_type");
        Map(m => m.CalcMethod).Name("calc_method");
        Map(m => m.RoundStrategy).Name("round_strategy");

        Map(m => m.StartDate).Name("start_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.EndDate).Name("end_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.MaxPostingDate).Name("max_posting_date").TypeConverterOption.Format("yyyy-MM-dd");

        Map(m => m.Source).Constant(RewardProgramSource.Base);
    }
}

/// <summary>
/// 對應 dim_card_rewards_campaigns.csv 及 _private 合併
/// 欄標: bank_name, card_type, 是否為當前消費權益, campaign_reward_program, campaign_reward_rate, ...
/// </summary>
public class CampaignCardRewardProgramMap : ClassMap<CardRewardProgram>
{
    public CampaignCardRewardProgramMap()
    {
        Map(m => m.BankName).Name("bank_name");
        Map(m => m.CardType).Name("card_type");
        Map(m => m.IsCurrentBenefit).Name("是否為當前消費權益").Optional();
        Map(m => m.RewardProgram).Name("campaign_reward_program");
        Map(m => m.RewardRate).Name("campaign_reward_rate");
        Map(m => m.RewardCycle).Name("reward_cycle");
        Map(m => m.MinSingleTransaction).Name("min_single_transaction");
        Map(m => m.CapAmount).Name("cap_amount");
        Map(m => m.RewardType).Name("reward_type");
        Map(m => m.CalcMethod).Name("calc_method");
        Map(m => m.RoundStrategy).Name("round_strategy");

        Map(m => m.StartDate).Name("start_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.EndDate).Name("end_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.MaxPostingDate).Name("max_posting_date").TypeConverterOption.Format("yyyy-MM-dd");

        Map(m => m.Source).Constant(RewardProgramSource.Campaign);
    }
}

/// <summary>
/// 向後相容別名：保留讓旧模組不會崩，實際使用 BaseCardRewardProgramMap
/// </summary>
public class CardRewardProgramMap : BaseCardRewardProgramMap { }
