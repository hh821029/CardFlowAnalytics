/**
 * web/scripts/demo_data_bridge.js
 * 靜態資料安全降級橋接器 (Static Mock Fallback Bridge)
 * 專為 GitHub Pages 或無後端伺服器環境設計：
 * 當 fetch() 請求後端 API 失敗 (404 / 網路斷線 / 靜態部署) 時，
 * 自動無縫降級讀取本地 ./mock_data/*.json 靜態數據！
 */

(function () {
    const originalFetch = window.fetch;

    // API 與靜態 Mock 檔案對照表
    const API_MOCK_MAP = [
        { pattern: /\/api\/analytics\/rfm-chart/, mock: 'mock_data/rfm_chart.json' },
        { pattern: /\/api\/analytics\/dimension-volatility/, mock: 'mock_data/dimension_volatility.json' },
        { pattern: /\/api\/analytics\/payment-volatility/, mock: 'mock_data/dimension_volatility.json' },
        { pattern: /\/api\/analytics\/monthly-trend/, mock: 'mock_data/monthly_trend.json' },
        { pattern: /\/api\/analytics\/sankey-flow/, mock: 'mock_data/sankey_flow.json' },
        { pattern: /\/api\/analytics\/rewards-summary/, mock: 'mock_data/rewards_summary.json' },
        { pattern: /\/api\/analyzable-data/, mock: 'mock_data/analyzable_data.json' },
        { pattern: /\/api\/cards\/banks/, mock: 'mock_data/analyzable_data.json' },
        { pattern: /\/api\/cards\/products/, mock: 'mock_data/analyzable_data.json' }
    ];

    // 攔截並封裝 fetch
    window.fetch = async function (resource, init) {
        const url = typeof resource === 'string' ? resource : (resource ? resource.url : '');

        // 檢查是否符合需降級之 API
        const match = API_MOCK_MAP.find(m => m.pattern.test(url));

        // 1. 如果是 GitHub Pages (hostname 包含 github.io) 或 file:// 協議，直接讀取靜態 mock
        const isStaticHost = window.location.hostname.includes('github.io') || window.location.protocol === 'file:';
        if (isStaticHost && match) {
            console.log(`🌐 [GitHub Pages / Static Mode] 導向靜態預載資料: ${match.mock}`);
            return originalFetch.call(this, match.mock, init);
        }

        // 2. 一般本地環境：優先嘗試正規 API
        try {
            const response = await originalFetch.call(this, resource, init);
            // 若後端回傳 404 或 502/503，自動降級
            if (!response.ok && match) {
                console.warn(`⚠️ API 回應異常 (${response.status})，自動降級至靜態展示資料: ${match.mock}`);
                return originalFetch.call(this, match.mock, init);
            }
            return response;
        } catch (networkError) {
            // 3. 網路斷線或伺服器未啟動時，自動降級至靜態展示資料
            if (match) {
                console.warn(`🔌 後端伺服器未連線，已自動啟動無後端靜態展示模式: ${match.mock}`);
                return originalFetch.call(this, match.mock, init);
            }
            throw networkError;
        }
    };
})();
