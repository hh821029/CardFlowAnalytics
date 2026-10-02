# tests/test_raw_transaction_schema.py
from datetime import date
from decimal import Decimal
import pandas as pd
import pytest
from pydantic import ValidationError

from etl.schemas import (
    RawTransactionSchema,
    validate_raw_dataframe,
    TransactionIdGenerator
)


def test_schema_field_alias_mapping():
    """測試從 Parser 舊欄位別名 (merchant, currency_amount, currency_type 等) 自動映射至 Raw Schema"""
    raw_dict = {
        "transaction_id": "tx_test_01",
        "bank_no": "808",
        "statement_month": "2026-09-01",
        "transaction_date": "2026-09-15",
        "merchant": "全家便利商店",
        "currency_type": "TWD",
        "currency_amount": "150.00",
        "payment_currency": "TWD",
        "payment_amount": "150.00",
        "card_no": "1234",
        "merchant_location": "TW"
    }

    schema = RawTransactionSchema.model_validate(raw_dict)
    assert schema.raw_merchant == "全家便利商店"
    assert schema.raw_amount == Decimal("150.00")
    assert schema.raw_currency == "TWD"
    assert schema.raw_location == "TW"
    assert schema.card_no == "1234"
    assert schema.statement_month == date(2026, 9, 1)


def test_pandas_dirty_data_sanitization():
    """測試全域消毒器：將 '<NA>', 'nan', 'None.0' 等髒資料洗淨為純 None，並去除卡號與銀行代號的 .0 殘留"""
    raw_dict = {
        "transaction_id": "tx_dirty_02",
        "bank_no": "808.0",
        "statement_month": "2026/09/01",
        "transaction_date": "2026/09/16",
        "posting_date": "<NA>",
        "conversion_date": "nan",
        "raw_merchant": "麥當勞",
        "raw_amount": 250,
        "payment_amount": "250.0",
        "card_no": "5678.0",
        "raw_location": "None"
    }

    schema = RawTransactionSchema.model_validate(raw_dict)
    assert schema.bank_no == "808"
    assert schema.card_no == "5678"
    assert schema.posting_date is None
    assert schema.conversion_date is None
    assert schema.raw_location is None
    assert schema.raw_amount == Decimal("250")


def test_amount_with_comma_and_decimal_precision():
    """測試帶有逗號的金額字串正確轉為嚴格 Decimal，不遺失精度"""
    raw_dict = {
        "transaction_id": "tx_amt_03",
        "bank_no": "013",
        "statement_month": "2026-08-01",
        "transaction_date": "2026-08-20",
        "raw_merchant": "Apple Store 台北101",
        "raw_amount": "54,900.50",
        "payment_amount": "54,900.50",
        "card_no": "9999"
    }

    schema = RawTransactionSchema.model_validate(raw_dict)
    assert schema.raw_amount == Decimal("54900.50")
    assert schema.payment_amount == Decimal("54900.50")


def test_validation_error_on_missing_required_fields():
    """測試缺少必填欄位 (如 raw_merchant 或 bank_no 格式不合) 會被嚴格攔截"""
    invalid_dict = {
        "transaction_id": "tx_err_04",
        "bank_no": "8088", # 超過 3 碼
        "statement_month": "2026-09-01",
        "transaction_date": "2026-09-15",
        "raw_merchant": "", # 空字串
        "raw_amount": 100,
        "payment_amount": 100
    }

    with pytest.raises(ValidationError):
        RawTransactionSchema.model_validate(invalid_dict)


def test_account_level_items_vs_purchase_card_no_constraints():
    """測試條件式約束：帳戶層級交易 (繳款) 缺卡號合法；純消費缺卡號在 raw_extra 記錄警告"""
    # 1. 自動扣繳交易：無卡號，合法且不應報警
    payment_dict = {
        "transaction_id": "tx_acc_05",
        "bank_no": "808",
        "statement_month": "2026-09-01",
        "transaction_date": "2026-09-05",
        "raw_merchant": "自動扣繳信用卡費",
        "raw_amount": 15000,
        "payment_amount": 15000,
        "card_no": None
    }
    schema_pmt = RawTransactionSchema.model_validate(payment_dict)
    assert schema_pmt.card_no is None
    assert schema_pmt.raw_extra is None or 'anomaly_warning' not in schema_pmt.raw_extra

    # 2. 實體消費：缺失卡號，應在 raw_extra 記錄警告供後續審計
    purchase_dict = {
        "transaction_id": "tx_pur_06",
        "bank_no": "808",
        "statement_month": "2026-09-01",
        "transaction_date": "2026-09-10",
        "raw_merchant": "新光三越信義店",
        "raw_amount": 3200,
        "payment_amount": 3200,
        "card_no": None
    }
    schema_pur = RawTransactionSchema.model_validate(purchase_dict)
    assert schema_pur.card_no is None
    assert schema_pur.raw_extra is not None
    assert schema_pur.raw_extra.get('anomaly_warning') == "MISSING_CARD_NO_ON_PURCHASE"


def test_validate_raw_dataframe_batch():
    """測試 validate_raw_dataframe 批次 DataFrame 轉換與自動 ID 生成"""
    mock_data = pd.DataFrame([
        {
            "bank_no": "808",
            "statement_month": "2026-09-01",
            "transaction_date": "2026-09-12",
            "merchant": "星巴克咖啡",
            "amount": "175",
            "card_no": "1122"
        },
        {
            "bank_no": "808",
            "statement_month": "2026-09-01",
            "transaction_date": "2026-09-12",
            "merchant": "星巴克咖啡",
            "amount": "175",
            "card_no": "1122"
        }
    ])

    schemas, clean_df = validate_raw_dataframe(mock_data)
    assert len(schemas) == 2
    assert len(clean_df) == 2

    # 驗證同日同商家同金額的流水號使得 transaction_id 唯一
    id1 = clean_df.iloc[0]['transaction_id']
    id2 = clean_df.iloc[1]['transaction_id']
    assert id1 != id2
    assert clean_df.iloc[0]['raw_merchant'] == "星巴克咖啡"
    assert clean_df.iloc[0]['raw_currency'] == "TWD"


def test_assign_raw_transaction_id_direct():
    """測試 TransactionIdGenerator.assign_raw_transaction_id 核心適配器行為"""
    # 1. 既有 ID 短路跳過
    row_with_id = {"transaction_id": "existing_id_123", "merchant": "測試"}
    res_id = TransactionIdGenerator.assign_raw_transaction_id(row_with_id)
    assert res_id == "existing_id_123"
    assert row_with_id["transaction_id"] == "existing_id_123"

    # 2. 單筆預設指派 (不帶 counter 預設 seq=1)
    row_single = {
        "bank_no": "808",
        "statement_month": "2026-09-01",
        "transaction_date": "2026-09-12",
        "merchant": "星巴克",
        "amount": "150",
        "card_no": "1122"
    }
    id_single = TransactionIdGenerator.assign_raw_transaction_id(row_single)
    assert isinstance(id_single, str) and len(id_single) == 32
    assert row_single["transaction_id"] == id_single

    # 3. 帶 counter 流水號累加
    counter = {}
    row_a = dict(row_single)
    row_a.pop("transaction_id", None)
    row_b = dict(row_single)
    row_b.pop("transaction_id", None)

    id_a = TransactionIdGenerator.assign_raw_transaction_id(row_a, seq_counter=counter)
    id_b = TransactionIdGenerator.assign_raw_transaction_id(row_b, seq_counter=counter)

    assert id_a == id_single  # 第一筆 seq=1，應與無 counter 時相同
    assert id_b != id_a       # 第二筆 seq=2，流水號不同，ID 必定不同
