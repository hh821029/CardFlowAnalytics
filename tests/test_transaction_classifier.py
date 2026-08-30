# tests/unit/test_transaction_classifier.py
import pytest
import pandas as pd
import numpy as np
import const
from etl.processors.classifier import TransactionClassifier
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

@pytest.fixture
def sample_config():
    """提供標準的關鍵字配置字典"""
    return {
        'payment_keywords': ['自動扣繳', '本行轉帳', 'ATM繳款', '超商繳款'],
        'credit_keywords': ['紅利折抵', '小樹點折抵', '現金回饋折抵'],
        'fee_keywords': ['國外交易手續費', '利息', '年費', '手續費'],
    }


@pytest.fixture
def classifier(sample_config):
    """初始化交易分類器實例"""
    return TransactionClassifier(config_dir="", config=sample_config)


class TestTransactionClassifierOrderAndPriority:
    """
    驗證業務順序與優先級：
    1. 繳款/轉帳 ➔ 2. 紅利與折抵 ➔ 3. 各項費用 ➔ 4. 退刷 ➔ 5. 國外交易 (台幣跨境/一般國外/雙幣) ➔ 6. 一般交易
    """

    def test_payment_priority_over_refund_and_foreign(self, classifier):
        """
        [優先級 1] 繳款/轉帳 優先於 退刷 與 國外交易：
        即使金額為負數且地點非 TW，只要符合繳款關鍵字，應被判定為「繳款」，並將地點重置為 TW、清除卡號。
        """
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "ACH自動扣繳 - 帳單結清",
                const.COL_LOCATION: "US",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: -10000.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: -10000.0,
                const.COL_CARD_NO: "1234",
                const.COL_CARD_TYPE: "玉山熊本熊卡",
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.PAYMENT.label
        assert result.iloc[0][const.COL_LOCATION] == "TW"
        assert pd.isna(result.iloc[0][const.COL_CARD_NO])
        assert pd.isna(result.iloc[0][const.COL_CARD_TYPE])

    def test_credit_priority_over_refund(self, classifier):
        """
        [優先級 2] 紅利與折抵 優先於 退刷：
        紅利折抵通常在帳單上呈現為負數金額，應被判定為「紅利折抵」而非「退刷」。
        """
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "小樹點折抵消費",
                const.COL_LOCATION: "TW",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: -300.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: -300.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.REDEMPTION.label
        assert result.iloc[0][const.COL_LOCATION] == "TW"

    def test_fee_priority_over_refund(self, classifier):
        """
        [優先級 3] 各項費用 優先於 退刷：
        若費用項目金額為負數（如手續費減免沖正），因費用關鍵字優先比對，應被標記為「各項費用」。
        """
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "國外交易手續費減免",
                const.COL_LOCATION: "TW",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: -15.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: -15.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.FEE.label
        assert result.iloc[0][const.COL_LOCATION] == "TW"

    def test_refund_priority_over_foreign(self, classifier):
        """
        [優先級 4] 退刷 優先於 國外交易：
        在國外店家進行退貨（非 TW 地區且金額為負數），應優先標記為「退刷」，而非國外交易。
        """
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "APPLE.COM/BILL",
                const.COL_LOCATION: "US",
                const.COL_CURRENCY: "USD",
                const.COL_CURR_AMOUNT: -30.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: -950.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.REFUND.label


class TestTransactionClassifierRules:
    """
    個別規則與邊界測試：
    - 繳款、紅利折抵、各項費用資料清洗
    - 退刷判定
    - 國外交易細分（台幣跨境、一般國外、雙幣）
    - 一般交易
    - 既有標記不被覆蓋
    """

    def test_mark_payment_data_sanitization(self, classifier):
        """測試繳款時的欄位補充與淨空邏輯"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "本行轉帳繳款",
                const.COL_LOCATION: "US",  # 應被修正為 TW
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: 5000.0,
                const.COL_PAY_CURR: "",    # 應從 currency_type 複製
                const.COL_PAY_AMOUNT: np.nan,  # 應從 currency_amount 複製
                const.COL_CARD_NO: "9999", # 應被淨空
                const.COL_CARD_TYPE: "卡片A",  # 應被淨空
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        row = result.iloc[0]
        assert row[const.COL_TXN_TYPE] == const.TransactionType.PAYMENT.label
        assert row[const.COL_LOCATION] == "TW"
        assert row[const.COL_PAY_CURR] == "TWD"
        assert row[const.COL_PAY_AMOUNT] == 5000.0
        assert pd.isna(row[const.COL_CARD_NO])
        assert pd.isna(row[const.COL_CARD_TYPE])

    def test_mark_credits_data_sanitization(self, classifier):
        """測試紅利折抵時的消費地與金額補齊"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "紅利折抵",
                const.COL_LOCATION: "JP",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: -100.0,
                const.COL_PAY_CURR: None,
                const.COL_PAY_AMOUNT: None,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        row = result.iloc[0]
        assert row[const.COL_TXN_TYPE] == const.TransactionType.REDEMPTION.label
        assert row[const.COL_LOCATION] == "TW"
        assert row[const.COL_PAY_CURR] == "TWD"
        assert row[const.COL_PAY_AMOUNT] == -100.0

    def test_mark_fees_data_sanitization(self, classifier):
        """測試各項費用之幣別與金額互補"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "國外交易手續費",
                const.COL_LOCATION: "US",
                const.COL_CURRENCY: "",
                const.COL_CURR_AMOUNT: 35.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: 35.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        row = result.iloc[0]
        assert row[const.COL_TXN_TYPE] == const.TransactionType.FEE.label
        assert row[const.COL_LOCATION] == "TW"
        assert row[const.COL_CURRENCY] == "TWD"
        assert row[const.COL_PAY_CURR] == "TWD"

    def test_mark_foreign_twd(self, classifier):
        """測試國外台幣跨境交易：Location != 'TW' 且原幣與結算幣皆為 TWD"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "Agoda Company Pte Ltd",
                const.COL_LOCATION: "SG",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: 3200.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: 3200.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.FOREIGN_TWD.label

    def test_mark_foreign_general(self, classifier):
        """測試一般國外交易：Location != 'TW' 且原幣與結算幣不同 (如 JPY vs TWD)"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "DON QUIJOTE SHINJUKU",
                const.COL_LOCATION: "JP",
                const.COL_CURRENCY: "JPY",
                const.COL_CURR_AMOUNT: 15000.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: 3150.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.FOREIGN.label

    def test_mark_foreign_dual(self, classifier):
        """測試一般雙幣交易：Location != 'TW' 且原幣與結算幣同為外幣 (如 USD vs USD)"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "Amazon.com Services LLC",
                const.COL_LOCATION: "US",
                const.COL_CURRENCY: "USD",
                const.COL_CURR_AMOUNT: 120.0,
                const.COL_PAY_CURR: "USD",
                const.COL_PAY_AMOUNT: 120.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.FOREIGN_DUAL.label

    def test_mark_general(self, classifier):
        """測試一般國內交易：Location 為 TW，且為正數消費"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "全聯福利中心 - 大安店",
                const.COL_LOCATION: "TW",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: 650.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: 650.0,
                const.COL_TXN_TYPE: "",
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.GENERAL.label

    def test_preserve_existing_transaction_type(self, classifier):
        """測試已存在分類標記時，不被後續規則覆蓋"""
        df = pd.DataFrame([
            {
                const.COL_MERCHANT: "全家便利商店",
                const.COL_LOCATION: "TW",
                const.COL_CURRENCY: "TWD",
                const.COL_CURR_AMOUNT: 0.0,
                const.COL_PAY_CURR: "TWD",
                const.COL_PAY_AMOUNT: 0.0,
                const.COL_TXN_TYPE: const.TransactionType.VERIFY.label,  # 已被 Parser 標記為驗證/零元
            }
        ])

        result = classifier.process(df)
        assert result.iloc[0][const.COL_TXN_TYPE] == const.TransactionType.VERIFY.label

    def test_empty_dataframe_handling(self, classifier):
        """測試空 DataFrame 處理能力"""
        df_empty = pd.DataFrame()
        result = classifier.process(df_empty)
        assert result.empty
