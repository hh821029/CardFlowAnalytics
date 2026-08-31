import sys
import os
import pytest
from fastapi.testclient import TestClient

# 將專案根目錄動態加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.server import app

client = TestClient(app)

class TestAPIRouters:
    """測試重構後的 FastAPI APIRouter 註冊與端點響應"""

    def test_analyzable_data_endpoint(self):
        """測試 /api/analyzable-data 取得維度下拉資料"""
        response = client.get("/api/analyzable-data")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "banks" in data
        assert "cards" in data
        assert "payment_processes" in data

    def test_route_registration(self):
        """測試所有 APIRouter 路由是否成功掛載至 FastAPI app"""
        routes = [route.path for route in app.routes if hasattr(route, "path")]
        
        expected_routes = [
            "/api/run/etl",
            "/api/run/config_all",
            "/api/run/config_card",
            "/api/run/config_reward",
            "/api/run/analytics",
            "/api/run/rewards",
            "/api/run/query_export",
            "/api/analyzable-data"
        ]
        
        for route in expected_routes:
            assert route in routes, f"❌ 路由 [{route}] 未能成功註冊於 FastAPI"
