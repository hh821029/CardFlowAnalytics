import sys
import os
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.server import app
import const

client = TestClient(app)

class TestAuthAndCardsJsonAPI:
    """測試 Auth 登入與卡片 JSON 圖形化 CRUD 端點"""

    def test_auth_login_example_public(self):
        """測試以 'example_public' 登入切換至 example_public"""
        response = client.post("/api/auth/login", json={"username": "example_public"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["profile_id"] == "example_public"
        assert const.ACTIVE_PROFILE_NAME == "example_public"

    def test_auth_login_main(self):
        """測試以 'main' 登入切換至 user_main"""
        response = client.post("/api/auth/login", json={"username": "main"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["profile_id"] == "user_main"
        assert const.ACTIVE_PROFILE_NAME == "user_main"

    def test_auth_status(self):
        """測試 /api/auth/status 端點"""
        response = client.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert "active_profile" in data

    def test_get_cards_json(self):
        """測試 GET /api/cards/json 讀取卡片設定"""
        response = client.get("/api/cards/json")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data["cards"], list)

    def test_get_banks(self):
        """測試 GET /api/cards/banks 讀取全量銀行維度"""
        response = client.get("/api/cards/banks")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data["banks"], list)
        assert len(data["banks"]) > 0

    def test_get_card_products(self):
        """測試 GET /api/cards/products 讀取卡片產品維度表"""
        response = client.get("/api/cards/products")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data["products"], list)
        assert len(data["products"]) > 0

    def test_post_cards_json_validation(self):
        """測試 POST /api/cards/json 寫入與 Atomic Save"""
        from api.routers.cards_json import get_cards_json_path
        target_path = get_cards_json_path()
        backup_content = None
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                backup_content = f.read()

        valid_card = [
            {
                "card_id": "test_card_id",
                "bank_no": "013",
                "card_type": "測試卡片",
                "card_history": [
                    {
                        "card_no": "9999",
                        "card_network": "VISA",
                        "smart_card_type": "NONE",
                        "status": "active",
                        "card_start_date": "2024-01-01",
                        "is_active": True,
                        "vpc_pay": [{"vpc_no": "9999", "vpc_type": "CARD"}]
                    }
                ]
            }
        ]
        invalid_bank_card = [
            {
                "card_id": "test_card_id",
                "bank_no": "test",
                "card_type": "測試卡片",
                "card_history": []
            }
        ]

        try:
            # 1. 測試非 list 傳入會報 400 錯
            response_err = client.post("/api/cards/json", json={"invalid": "dict"})
            assert response_err.status_code == 400

            # 2. 測試不符合 dim_banks.yaml 之 bank_no (如 'test') 傳入會報 400 錯
            response_bank_err = client.post("/api/cards/json", json=invalid_bank_card)
            assert response_bank_err.status_code == 400
            assert "不合法的銀行代碼" in response_bank_err.json()["detail"]

            # 3. 測試正常寫入 (開啟 sync_db=False 避免測試環境 DB 連線波動)
            response = client.post("/api/cards/json?sync_db=false", json=valid_card)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["count"] == 1
        finally:
            # 測試後恢復原始檔案內容
            if backup_content is not None:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)
            elif os.path.exists(target_path):
                os.remove(target_path)
            const.ACTIVE_PROFILE_NAME = "example_public"

