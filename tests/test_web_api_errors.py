import os
import sys
import datetime
import pytest
from fastapi.testclient import TestClient

# 動態加入專案根目錄至 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.server import app

client = TestClient(app)

class TestWebAPIErrors:
    """測試 Web API 與 HTTP 錯誤處理 (403/404/501/502/503/500) 與 errorlog 寫入"""

    def test_root_index_html(self):
        """測試存取 / (總控制台) 回傳 200"""
        response = client.get("/")
        assert response.status_code == 200
        assert "總控制台" in response.text

    def test_etl_html_decoupled(self):
        """測試存取 /etl_manager.html (ETL 帳單處理) 回傳 200"""
        response = client.get("/etl_manager.html")
        assert response.status_code == 200
        assert "ETL" in response.text or "帳單" in response.text

    def test_404_html_error_page(self):
        """測試存取不存在頁面觸發 404 HTML 錯誤頁面"""
        response = client.get("/nonexistent-page-path-12345", headers={"Accept": "text/html"})
        assert response.status_code == 404
        assert "404" in response.text
        assert "styles.css" in response.text
        assert "返回總控制台" in response.text

    def test_404_api_json_error(self):
        """測試 API 請求不存在端點觸發 404 JSON 回應"""
        response = client.get("/api/nonexistent-endpoint", headers={"Accept": "application/json"})
        assert response.status_code == 404
        data = response.json()
        assert data["status"] == 404
        assert "detail" in data

    def test_simulated_error_403(self):
        """測試模擬 403 存取被拒絕"""
        response = client.get("/api/error/403")
        assert response.status_code == 403

    def test_simulated_error_501(self):
        """測試模擬 501 功能尚未實作"""
        response = client.get("/api/error/501")
        assert response.status_code == 501

    def test_simulated_error_502(self):
        """測試模擬 502 閘道錯誤"""
        response = client.get("/api/error/502")
        assert response.status_code == 502

    def test_simulated_error_503(self):
        """測試模擬 503 服務不可用"""
        response = client.get("/api/error/503")
        assert response.status_code == 503

    def test_errorlog_file_created(self):
        """測試 errorlog/ 資料夾是否有生成今日日誌檔"""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        error_log_dir = os.path.join(base_dir, "errorlog")
        today_str = datetime.date.today().strftime("%Y%m%d")
        expected_log = os.path.join(error_log_dir, f"error_{today_str}.log")

        assert os.path.exists(error_log_dir), "❌ errorlog 資料夾不存在"
        assert os.path.exists(expected_log), f"❌ 今日日誌檔 {expected_log} 未被建立"
