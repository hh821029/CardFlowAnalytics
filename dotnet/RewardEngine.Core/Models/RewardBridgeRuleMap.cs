using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

public class RewardBridgeRuleMap : ClassMap<RewardBridgeRule>
{
    public RewardBridgeRuleMap()
    {
        Map(m => m.RulesRewardProgram).Name("rules_reward_program");
        Map(m => m.VpcType).Name("vpc_type");
        Map(m => m.MobilePayment).Name("mobile_payment");
        Map(m => m.EcPlatform).Name("ec_platform");
        Map(m => m.NormalizedMerchant).Name("normalized_merchant");
        Map(m => m.MerchantDisplay).Name("merchant_display");
        Map(m => m.MerchantLocation).Name("merchant_location");
        Map(m => m.MerchantRate).Name("merchant_rate");
        Map(m => m.Priority).Name("priority");
        Map(m => m.RewardCalBreak).Name("reward_cal_break");

        // 處理日期格式 (如 2026-05-01)
        Map(m => m.StartDate).Name("start_date").TypeConverterOption.Format("yyyy-MM-dd");
        Map(m => m.EndDate).Name("end_date").TypeConverterOption.Format("yyyy-MM-dd");
    }
}
