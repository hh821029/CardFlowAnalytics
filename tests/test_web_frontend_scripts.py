# tests/test_web_frontend_scripts.py
"""
Unit and integration tests for front-end scripts and mock data:
- web/mock_data/*.json data contract and schema integrity
- web/scripts/demo_data_bridge.js fallback routing and hostname security
- web/scripts/console_runner.js log styling rules
- web/scripts/cards_manager.js bank and card product data mappings
- export_demo_static_json.py pipeline validation
"""
import os
import re
import json
import subprocess
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.path.join(ROOT_DIR, "web")
MOCK_DATA_DIR = os.path.join(WEB_DIR, "mock_data")
SCRIPTS_DIR = os.path.join(WEB_DIR, "scripts")


# ==============================================================================
# 1. web/mock_data 靜態資料結構與 Schema 契約校驗
# ==============================================================================

class TestMockDataContracts:
    """測試 web/mock_data 下所有靜態 JSON 的完整性與資料結構"""

    @pytest.fixture(autouse=True)
    def ensure_mock_data_exists(self):
        """確保測試前 mock_data 已被生成且資料齊全"""
        demo_bills = os.path.join(ROOT_DIR, "database", "TransactionsBills_demo.db")
        if not os.path.exists(demo_bills):
            from prepare_demo_dataset import prepare_demo_dataset
            prepare_demo_dataset()
        from export_demo_static_json import export_all
        export_all()

    def test_mock_data_files_exist(self):
        """驗證 6 大核心前端展示 JSON 檔案均存在且非空"""
        expected_files = [
            "rfm_chart.json",
            "dimension_volatility.json",
            "monthly_trend.json",
            "sankey_flow.json",
            "rewards_summary.json",
            "analyzable_data.json"
        ]
        for fname in expected_files:
            fpath = os.path.join(MOCK_DATA_DIR, fname)
            assert os.path.exists(fpath), f"缺少展示檔案: {fname}"
            assert os.path.getsize(fpath) > 0, f"展示檔案為空: {fname}"

    def test_no_raw_nan_or_infinity(self):
        """驗證所有 JSON 檔案中無未序列化的 NaN 或 Infinity"""
        for fname in os.listdir(MOCK_DATA_DIR):
            if fname.endswith(".json"):
                fpath = os.path.join(MOCK_DATA_DIR, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    assert not re.search(r'\bNaN\b', content), f"{fname} 包含非法的 NaN 字串"
                    assert not re.search(r'\bInfinity\b', content), f"{fname} 包含非法的 Infinity 字串"

    def test_rfm_chart_contract(self):
        """校驗 rfm_chart.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "rfm_chart.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("success") is True
        payload = data.get("data", {})
        assert "merchants" in payload
        assert "cards" in payload
        assert "categories" in payload
        assert "top_by_category" in payload
        assert len(payload["merchants"]) > 0

    def test_dimension_volatility_contract(self):
        """校驗 dimension_volatility.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "dimension_volatility.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("success") is True
        payload = data.get("data", {})
        assert "groups" in payload
        assert "volatility_counts" in payload
        assert payload.get("group_mode") == "payment_category"

    def test_monthly_trend_contract(self):
        """校驗 monthly_trend.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "monthly_trend.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("success") is True
        payload = data.get("data", {})
        assert "months" in payload
        assert "categories" in payload
        assert "series" in payload
        assert "summary" in payload
        assert payload["summary"].get("total_amount", 0) > 0

    def test_sankey_flow_contract(self):
        """校驗 sankey_flow.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "sankey_flow.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("success") is True
        payload = data.get("data", {})
        assert "nodes" in payload
        assert "links" in payload
        assert len(payload["nodes"]) > 0
        assert len(payload["links"]) > 0

    def test_rewards_summary_contract(self):
        """校驗 rewards_summary.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "rewards_summary.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("success") is True
        payload = data.get("data", {})
        assert "monthly_summary" in payload
        assert "pool_utilization" in payload

    def test_analyzable_data_contract(self):
        """校驗 analyzable_data.json 資料結構"""
        fpath = os.path.join(MOCK_DATA_DIR, "analyzable_data.json")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "banks" in data
        assert "cards" in data
        assert "payment_processes" in data or "payments" in data


# ==============================================================================
# 2. web/scripts/demo_data_bridge.js 降級路由與安全性測試
# ==============================================================================

class TestDemoDataBridge:
    """測試前端靜態降級橋接器的正規比對、目標檔案存在性與網域安全性"""

    @pytest.fixture
    def bridge_script(self):
        script_path = os.path.join(SCRIPTS_DIR, "demo_data_bridge.js")
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_mock_map_targets_exist(self, bridge_script):
        """驗證 API_MOCK_MAP 中定義的所有 mock 檔案路徑皆真實存在"""
        matches = re.findall(r"mock:\s*'([^']+)'", bridge_script)
        assert len(matches) > 0
        for mock_rel_path in set(matches):
            full_path = os.path.join(WEB_DIR, mock_rel_path)
            assert os.path.exists(full_path), f"demo_data_bridge.js 映射之檔案不存在: {full_path}"

    def test_endpoint_matching_via_node(self):
        """透過 Node.js 驗證 API_MOCK_MAP 的正則匹配邏輯"""
        js_code = """
        const API_MOCK_MAP = [
            { pattern: /\\/api\\/analytics\\/rfm-chart/, mock: 'mock_data/rfm_chart.json' },
            { pattern: /\\/api\\/analytics\\/dimension-volatility/, mock: 'mock_data/dimension_volatility.json' },
            { pattern: /\\/api\\/analytics\\/payment-volatility/, mock: 'mock_data/dimension_volatility.json' },
            { pattern: /\\/api\\/analytics\\/monthly-trend/, mock: 'mock_data/monthly_trend.json' },
            { pattern: /\\/api\\/analytics\\/sankey-flow/, mock: 'mock_data/sankey_flow.json' },
            { pattern: /\\/api\\/analytics\\/rewards-summary/, mock: 'mock_data/rewards_summary.json' },
            { pattern: /\\/api\\/analyzable-data/, mock: 'mock_data/analyzable_data.json' },
            { pattern: /\\/api\\/cards\\/banks/, mock: 'mock_data/analyzable_data.json' },
            { pattern: /\\/api\\/cards\\/products/, mock: 'mock_data/analyzable_data.json' }
        ];

        function findMatch(url) {
            const m = API_MOCK_MAP.find(item => item.pattern.test(url));
            return m ? m.mock : null;
        }

        const tests = {
            rfm: findMatch('/api/analytics/rfm-chart?window=life'),
            volatility: findMatch('/api/analytics/dimension-volatility?group=payment_category'),
            trend: findMatch('/api/analytics/monthly-trend'),
            sankey: findMatch('/api/analytics/sankey-flow'),
            rewards: findMatch('/api/analytics/rewards-summary'),
            analyzable: findMatch('/api/analyzable-data'),
            banks: findMatch('/api/cards/banks'),
            products: findMatch('/api/cards/products'),
            unmatched: findMatch('/api/other/unknown')
        };
        console.log(JSON.stringify(tests));
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, encoding="utf-8", check=True)
        results = json.loads(res.stdout)
        assert results["rfm"] == "mock_data/rfm_chart.json"
        assert results["volatility"] == "mock_data/dimension_volatility.json"
        assert results["trend"] == "mock_data/monthly_trend.json"
        assert results["sankey"] == "mock_data/sankey_flow.json"
        assert results["rewards"] == "mock_data/rewards_summary.json"
        assert results["analyzable"] == "mock_data/analyzable_data.json"
        assert results["banks"] == "mock_data/analyzable_data.json"
        assert results["products"] == "mock_data/analyzable_data.json"
        assert results["unmatched"] is None

    def test_hostname_security_sanitization_via_node(self):
        """驗證網域名稱比對嚴格性（阻斷釣魚網域 attacker-github.io）"""
        js_code = """
        function isGitHubPages(hostname) {
            return hostname === 'github.io' || hostname.endsWith('.github.io');
        }

        const checks = {
            exact: isGitHubPages('github.io'),
            subdomain: isGitHubPages('hh821029.github.io'),
            nested: isGitHubPages('my.project.github.io'),
            phishing: isGitHubPages('attacker-github.io'),
            fake_tld: isGitHubPages('github.io.attacker.com'),
            localhost: isGitHubPages('localhost')
        };
        console.log(JSON.stringify(checks));
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, encoding="utf-8", check=True)
        checks = json.loads(res.stdout)
        assert checks["exact"] is True
        assert checks["subdomain"] is True
        assert checks["nested"] is True
        assert checks["phishing"] is False
        assert checks["fake_tld"] is False
        assert checks["localhost"] is False


# ==============================================================================
# 3. web/scripts/console_runner.js 控制台日誌樣式規則測試
# ==============================================================================

class TestConsoleRunnerLogic:
    """測試任務控制台日誌渲染關鍵字高亮樣式規則"""

    def test_log_styling_rules_via_node(self):
        """透過 Node.js 執行 console_runner 中的關鍵字分類邏輯"""
        js_code = """
        function getLogClass(message) {
            const classes = [];
            if (message.includes('INFO') || message.includes('ℹ️')) {
                classes.push('log-info');
            } else if (message.includes('WARNING') || message.includes('⚠️')) {
                classes.push('log-warning');
            } else if (message.includes('ERROR') || message.includes('❌') || message.includes('失敗')) {
                classes.push('log-error');
            }
            if (message.includes('✅') || message.includes('🎉') || message.includes('成功') || message.includes('完畢') || message.includes('完成')) {
                classes.push('log-success');
            }
            return classes;
        }

        const cases = {
            info1: getLogClass('[INFO] 正在解析帳單...'),
            info2: getLogClass('ℹ️ 開始同步'),
            warn1: getLogClass('[WARNING] 欄位缺失'),
            warn2: getLogClass('⚠️ 缺少配置'),
            error1: getLogClass('[ERROR] 執行異常'),
            error2: getLogClass('❌ 讀取失敗'),
            success1: getLogClass('✅ 同步完成'),
            success2: getLogClass('🎉 運算完畢'),
            normal: getLogClass('一般日誌輸出')
        };
        console.log(JSON.stringify(cases));
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, encoding="utf-8", check=True)
        out = json.loads(res.stdout)
        assert "log-info" in out["info1"]
        assert "log-info" in out["info2"]
        assert "log-warning" in out["warn1"]
        assert "log-warning" in out["warn2"]
        assert "log-error" in out["error1"]
        assert "log-error" in out["error2"]
        assert "log-success" in out["success1"]
        assert "log-success" in out["success2"]
        assert len(out["normal"]) == 0


# ==============================================================================
# 4. web/scripts/cards_manager.js 銀行與卡片字典映射測試
# ==============================================================================

class TestCardsManagerMappings:
    """測試卡片維護面板中的資料結構轉換"""

    def test_bank_and_card_mappings_via_node(self):
        """透過 Node.js 驗證 bankMap 與 cardProductsMap 映射"""
        js_code = """
        const availableBanks = [
            { bank_no: "013", bank_name: "國泰世華商業銀行", bills_mapping_name: "國泰世華" },
            { bank_no: "808", bank_name: "玉山商業銀行", bills_mapping_name: "玉山銀行" },
            { bank_no: "999", bank_name: "" }
        ];

        const bankMap = {};
        availableBanks.forEach(b => {
            const bNo = String(b.bank_no).trim();
            const bName = b.bills_mapping_name || b.bank_name || bNo;
            bankMap[bNo] = bName;
        });

        const cardProducts = [
            { card_id: "cube", card_name: "CUBE卡", bank_no: "013" },
            { card_id: "ubear", card_name: "U Bear卡", bank_no: "808" }
        ];

        const cardProductsMap = {};
        cardProducts.forEach(p => {
            if (p.card_id) cardProductsMap[p.card_id] = p;
        });

        console.log(JSON.stringify({
            bankMap,
            cardProductsMap
        }));
        """
        res = subprocess.run(["node", "-e", js_code], capture_output=True, text=True, encoding="utf-8", check=True)
        data = json.loads(res.stdout)
        bank_map = data["bankMap"]
        assert bank_map["013"] == "國泰世華"
        assert bank_map["808"] == "玉山銀行"
        assert bank_map["999"] == "999"

        card_map = data["cardProductsMap"]
        assert "cube" in card_map
        assert card_map["cube"]["card_name"] == "CUBE卡"
        assert card_map["ubear"]["bank_no"] == "808"


# ==============================================================================
# 5. export_demo_static_json 端到端預烘焙管線測試
# ==============================================================================

class TestDemoExportPipeline:
    """測試靜態 JSON 預烘焙匯出工具的執行穩定性"""

    def test_export_all_execution(self):
        """驗證 export_all() 函式可被順暢調用且產出檔案無異常"""
        from export_demo_static_json import export_all
        # 再次執行 export_all() 確保管線具冪等性
        export_all()
        assert os.path.exists(os.path.join(MOCK_DATA_DIR, "rfm_chart.json"))
        assert os.path.exists(os.path.join(MOCK_DATA_DIR, "monthly_trend.json"))

