using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using CsvHelper;
using CsvHelper.Configuration;
using RewardEngine.Core.Models;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 提供離線或單元測試環境直接從 JSON / CSV 設定檔讀取回饋池與關聯表
/// </summary>
public static class JsonRuleLoader
{
    private static readonly JsonSerializerOptions DefaultJsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        NumberHandling = JsonNumberHandling.AllowReadingFromString
    };

    /// <summary>
    /// 從 JSON 檔案路徑讀取並反序列化 MerchantRewardPool 清單 (43個特店回饋池)
    /// </summary>
    public static List<MerchantRewardPool> LoadRewardPools(string jsonPath)
    {
        if (!File.Exists(jsonPath))
        {
            throw new FileNotFoundException($"找不到回饋池 JSON 檔案：{jsonPath}");
        }

        var json = File.ReadAllText(jsonPath, System.Text.Encoding.UTF8);
        return LoadRewardPoolsFromString(json);
    }

    /// <summary>
    /// 從 JSON 字串直接反序列化 MerchantRewardPool 清單
    /// </summary>
    public static List<MerchantRewardPool> LoadRewardPoolsFromString(string jsonContent)
    {
        if (string.IsNullOrWhiteSpace(jsonContent))
        {
            return [];
        }

        var pools = JsonSerializer.Deserialize<List<MerchantRewardPool>>(jsonContent, DefaultJsonOptions);
        return pools ?? [];
    }

    /// <summary>
    /// 從 CSV 檔案路徑載入方案與特店池的關聯對應 (bridge_reward_linked_lists.csv)
    /// </summary>
    public static List<RewardLinkedList> LoadRewardLinkedListsFromCsv(string csvPath)
    {
        if (!File.Exists(csvPath))
        {
            throw new FileNotFoundException($"找不到關聯對應 CSV 檔案：{csvPath}");
        }

        var config = new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            HasHeaderRecord = true,
            MissingFieldFound = null,
            HeaderValidated = null
        };

        using var reader = new StreamReader(csvPath, System.Text.Encoding.UTF8);
        using var csv = new CsvReader(reader, config);

        var records = new List<RewardLinkedList>();
        csv.Read();
        csv.ReadHeader();

        while (csv.Read())
        {
            var rewardId = csv.GetField("reward_id")?.Trim();
            var poolId = csv.GetField("merchant_reward_pools_id")?.Trim();

            if (!string.IsNullOrEmpty(rewardId) && !string.IsNullOrEmpty(poolId))
            {
                records.Add(new RewardLinkedList
                {
                    RewardId = rewardId,
                    MerchantRewardPoolsId = poolId
                });
            }
        }

        return records;
    }
}
