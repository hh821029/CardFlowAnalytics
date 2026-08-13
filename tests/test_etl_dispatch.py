import sys
import os
import pytest
import pandas as pd

# 將專案根目錄動態加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import const
from etl.etl_api import get_bank_info, get_parser
from etl.etl_extraction import extract_raw_data
from etl.etl_transformation import transform_data
from database.loaders.schema_enforcer import SchemaEnforcer

class TestETLDispatchAndSchema:
    """測試 ETL 解析分派器與 16 欄位正規化 Schema"""

    def test_bank_info_lookup_from_yaml(self):
        """測試 1: 驗證透過 dim_banks.yaml 的 bill_mapping_name 與 keywords 動態識別銀行"""
        # 1. 測試玉山銀行
        bank_esun = get_bank_info("202409_玉山信用卡帳單.csv")
        assert bank_esun is not None, "❌ 應成功識別玉山銀行"
        assert bank_esun.get("bank_id") == "esun"
        assert bank_esun.get("bank_no") == "808"

        # 2. 測試國泰世華
        bank_cathay = get_bank_info("202410_國泰世華CUBE.csv")
        assert bank_cathay is not None, "❌ 應成功識別國泰世華"
        assert bank_cathay.get("bank_id") in ["cube", "cathay"]
        assert bank_cathay.get("bank_no") == "013"

        # 3. 測試永豐銀行
        bank_sinopac = get_bank_info("202411_DAWHO_永豐帳單.pdf")
        assert bank_sinopac is not None, "❌ 應成功識別永豐銀行"
        assert bank_sinopac.get("bank_id") == "sinopac"

    def test_parser_dispatching(self):
        """測試 2: 驗證 get_parser 動態分派正確的 Parser 類別"""
        parser_esun = get_parser("玉山信用卡明細.csv")
        assert parser_esun is not None, "❌ 應正確分派 玉山 Parser"

        parser_sinopac = get_parser("永豐銀行信用卡帳單.pdf")
        assert parser_sinopac is not None, "❌ 應正確分派 永豐 Parser"

    def test_16_column_standard_schema(self):
        """測試 3: 驗證 const.STANDARD_COLUMNS 包含預期的 16 個正規化欄位"""
        assert len(const.STANDARD_COLUMNS) == 16, f"❌ STANDARD_COLUMNS 應精簡為 16 個欄位，當前為 {len(const.STANDARD_COLUMNS)}"
        
        required_16 = [
            'transaction_id', 'transaction_date', 'posting_date', 'conversion_date',
            'statement_month', 'bank_name', 'card_no', 'vpc_type', 'merchant',
            'merchant_location', 'consumption_place', 'currency_type', 'currency_amount',
            'payment_currency', 'payment_amount', 'transaction_type'
        ]
        for col in required_16:
            assert col in const.STANDARD_COLUMNS, f"❌ STANDARD_COLUMNS 缺少欄位: {col}"

    def test_schema_enforcer_on_16_columns(self):
        """測試 4: 驗證 SchemaEnforcer 針對 16 欄位資料的轉型與執法"""
        raw_data = pd.DataFrame([{
            'transaction_id': 'abc123md5hash',
            'transaction_date': '2024-10-01',
            'posting_date': '2024-10-03',
            'conversion_date': None,
            'statement_month': '2024-10',
            'bank_name': '玉山商業銀行',
            'card_no': '3833',
            'vpc_type': 'ApplePay',
            'merchant': 'PChome線上購物',
            'merchant_location': 'TW',
            'consumption_place': '台北市',
            'currency_type': 'TWD',
            'currency_amount': 1500.0,
            'payment_currency': 'TWD',
            'payment_amount': 1500.0,
            'transaction_type': '一般消費'
        }])

        enforced_df = SchemaEnforcer.enforce(raw_data)
        assert not enforced_df.empty
        assert len(enforced_df.columns) == 16
        assert enforced_df['card_no'].iloc[0] == '3833'

    def test_extract_and_transform_decoupled_pipeline(self):
        """測試 5: 驗證解耦後的 etl_extraction 與 etl_transformation 銜接與執行"""
        mock_raw = pd.DataFrame([{
            'transaction_date': '2024-10-01',
            'posting_date': '2024-10-03',
            'bank_name': '玉山商業銀行',
            'merchant': 'LINEPay-PChome線上購物',
            'payment_amount': 1000.0,
            'currency_type': 'TWD'
        }])

        transformed = transform_data(mock_raw)
        assert not transformed.empty
        assert 'transaction_date' in transformed.columns
