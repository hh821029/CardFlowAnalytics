using RewardEngine.Core.Loaders;
using RewardEngine.Core.Models;
using Xunit;

namespace RewardEngine.Tests;

public class RewardPoolLoaderTests
{
    [Fact]
    public void LoadRewardPools_ShouldDeserializeAllPoolsSuccessfully()
    {
        // Arrange: 定位 bridge_reward_pools.json 路徑
        var baseDir = AppContext.BaseDirectory;
        var jsonPath = Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "..", "profiles", "common", "configs", "bridge_reward_pools.json"));

        // Act
        var pools = JsonRuleLoader.LoadRewardPools(jsonPath);

        // Assert
        Assert.NotNull(pools);
        Assert.NotEmpty(pools);

        var generalPool = pools.FirstOrDefault(p => p.MerchantRewardPoolsId == "POOL_GENERAL_EXCLUSION");
        Assert.NotNull(generalPool);
        Assert.Equal("共通非一般消費", generalPool.PoolName);
        Assert.NotEmpty(generalPool.PassRules);
        Assert.NotEmpty(generalPool.Rules);

        // 驗證 PassRules 中的字串陣列反序列化 (例如 統一超商, 全家便利商店)
        var arrayRule = generalPool.PassRules.FirstOrDefault(r => r.NormalizedMerchant != null && r.NormalizedMerchant.Length > 1);
        Assert.NotNull(arrayRule);
        Assert.Contains("統一超商", arrayRule.NormalizedMerchant!);
        Assert.Contains("全家便利商店", arrayRule.NormalizedMerchant!);

        // 驗證單一字串反序列化為單一元素陣列
        var singleStringRule = generalPool.PassRules.FirstOrDefault(r => r.NormalizedMerchant != null && r.NormalizedMerchant.Length == 1);
        Assert.NotNull(singleStringRule);
        Assert.Equal("統一超商", singleStringRule.NormalizedMerchant![0]);
    }

    [Fact]
    public void LoadRewardLinkedLists_ShouldLoadAll103LinksSuccessfully()
    {
        // Arrange: 定位 bridge_reward_linked_lists.csv 路徑
        var baseDir = AppContext.BaseDirectory;
        var csvPath = Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "..", "profiles", "common", "configs", "bridge_reward_linked_lists.csv"));

        // Act
        var links = JsonRuleLoader.LoadRewardLinkedListsFromCsv(csvPath);

        // Assert
        Assert.NotNull(links);
        Assert.NotEmpty(links);
        Assert.All(links, l =>
        {
            Assert.False(string.IsNullOrWhiteSpace(l.RewardId));
            Assert.False(string.IsNullOrWhiteSpace(l.MerchantRewardPoolsId));
        });
    }
}
