using System.Globalization;
using CsvHelper;
using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

public static class CsvRuleLoader
{
    public static List<CardRewardProgram> LoadBasePrograms(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null, // 允許選填欄位為空白
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);
        
        csv.Context.RegisterClassMap<BaseCardRewardProgramMap>();
        return csv.GetRecords<CardRewardProgram>().ToList();
    }

    public static List<CardRewardProgram> LoadCampaignsPrograms(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null, // 允許選填欄位為空白
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);
        
        csv.Context.RegisterClassMap<CampaignCardRewardProgramMap>();
        return csv.GetRecords<CardRewardProgram>().ToList();
    }

    public static List<RewardBridgeRule> LoadBridgeRules(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        csv.Context.RegisterClassMap<RewardBridgeRuleMap>();
        return csv.GetRecords<RewardBridgeRule>().ToList();
    }

    public static List<DailyBenefitSelection> LoadDailySelections(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        csv.Context.RegisterClassMap<DailyBenefitSelectionMap>();
        return csv.GetRecords<DailyBenefitSelection>().ToList();
    }

    public static List<MonthlyBenefitSelection> LoadMonthlySelections(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        csv.Context.RegisterClassMap<MonthlyBenefitSelectionMap>();
        return csv.GetRecords<MonthlyBenefitSelection>().ToList();
    }

    public static List<BillingHistoryRecord> LoadBillingHistory(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        csv.Context.RegisterClassMap<BillingHistoryRecordMap>();
        return csv.GetRecords<BillingHistoryRecord>().ToList();
    }

    public static List<RewardLinkedList> LoadRewardLinkedLists(string csvPath)
    {
        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        var list = new List<RewardLinkedList>();
        csv.Read();
        csv.ReadHeader();
        while (csv.Read())
        {
            var rewardId = csv.GetField("reward_id")?.Trim();
            var poolId = csv.GetField("merchant_reward_pools_id")?.Trim();
            if (!string.IsNullOrEmpty(rewardId) && !string.IsNullOrEmpty(poolId))
            {
                list.Add(new RewardLinkedList
                {
                    RewardId = rewardId,
                    MerchantRewardPoolsId = poolId
                });
            }
        }
        return list;
    }
}
