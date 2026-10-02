# etl/schemas/raw_transaction.py
"""
Stage 1 (Bronze) 原始帳單資料契約層 (Raw Transaction Schema & Sanitizer)
基於 Pydantic V2 建立嚴格型態防火牆，徹底根絕 Pandas 空值與字串型別污染。
"""
from datetime import date, datetime
from decimal import Decimal
import hashlib
import re
from typing import Optional, Dict, Any, List, Tuple
import logging
import pandas as pd
import numpy as np
from pydantic import (
    BaseModel,
    Field,
    AliasChoices,
    ConfigDict,
    field_validator,
    model_validator
)


logger = logging.getLogger(__name__)


class RawTransactionSchema(BaseModel):
    """
    Stage 1 原始對齊事實契約 (Bronze Layer Schema)
    對應資料庫 raw_transactions 實體表
    """
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True
    )

    # 1. 唯一鍵值與歸屬維度
    transaction_id: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="全系統唯一交易流水識別碼 (SHA-256 前32碼)"
    )
    bank_no: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="3 碼銀行代碼 (如 808, 013, 822)"
    )
    statement_month: date = Field(
        ...,
        validation_alias=AliasChoices('statement_month', 'bill_month'),
        description="帳單歸屬月份 (YYYY-MM-01)"
    )

    # 2. 日期維度
    transaction_date: date = Field(
        ...,
        validation_alias=AliasChoices('transaction_date', 'tx_date'),
        description="消費日期"
    )
    posting_date: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices('posting_date', 'post_date'),
        description="入帳日期 (可為空)"
    )
    conversion_date: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices('conversion_date', 'conv_date'),
        description="外幣折算日期 (可為空)"
    )

    # 3. 原始商家資訊
    raw_merchant: str = Field(
        ...,
        min_length=1,
        max_length=500,
        validation_alias=AliasChoices('raw_merchant', 'merchant', 'merchant_name'),
        description="銀行原始明細/摘要文字 (原汁原味)"
    )

    # 4. 幣別與金額 (強型態 Decimal)
    raw_currency: str = Field(
        default="TWD",
        max_length=3,
        validation_alias=AliasChoices('raw_currency', 'currency_type', 'currency'),
        description="原始交易幣別 (如 TWD, USD, JPY)"
    )
    raw_amount: Decimal = Field(
        default=Decimal(0),
        validation_alias=AliasChoices('raw_amount', 'currency_amount', 'amount'),
        description="原始交易金額"
    )
    payment_currency: str = Field(
        default="TWD",
        max_length=3,
        validation_alias=AliasChoices('payment_currency', 'pay_currency'),
        description="應繳折算幣別 (如 TWD, USD)"
    )
    payment_amount: Decimal = Field(
        default=Decimal(0),
        validation_alias=AliasChoices('payment_amount', 'pay_amount'),
        description="應繳折算金額"
    )

    # 5. 卡片與消費地識別
    card_no: Optional[str] = Field(
        default=None,
        max_length=4,
        validation_alias=AliasChoices('card_no', 'card_last_4'),
        description="卡號末四碼 (非刷卡帳戶明細可為空)"
    )
    raw_location: Optional[str] = Field(
        default="TW",
        max_length=100,
        validation_alias=AliasChoices('raw_location', 'merchant_location', 'location', 'consumption_place'),
        description="原始消費國別或地點代碼 (如 TW, JP, US, JPN CHIYODA-KU)"
    )

    # 6. 特殊備份與稽核欄位
    raw_extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="銀行特有欄位備份 (如行動支付註記、專屬備註)"
    )
    created_at: Optional[datetime] = Field(
        default_factory=datetime.now,
        description="建立時間"
    )

    # ==========================================
    # Pydantic V2 欄位驗證與防禦消毒器
    # ==========================================

    @model_validator(mode='before')
    @classmethod
    def ensure_amounts_fallback(cls, data: Any) -> Any:
        """雙向金額互補：若原始金額或應繳金額其中一者缺失，以另一者自動補齊；若皆缺失則設為 0"""
        if isinstance(data, dict):
            r_amt = data.get('raw_amount') if data.get('raw_amount') is not None else data.get('currency_amount')
            p_amt = data.get('payment_amount') if data.get('payment_amount') is not None else (data.get('pay_amount') if data.get('pay_amount') is not None else data.get('amount'))

            def is_invalid(val):
                if val is None:
                    return True
                if isinstance(val, (float, np.floating)) and pd.isna(val):
                    return True
                s = str(val).strip().lower()
                return s in ['', 'nan', '<na>', 'none', 'nat', 'null']

            r_inv = is_invalid(r_amt)
            p_inv = is_invalid(p_amt)

            if r_inv and not p_inv:
                data['raw_amount'] = p_amt
            elif p_inv and not r_inv:
                data['payment_amount'] = r_amt
                data['pay_amount'] = r_amt
            elif r_inv and p_inv:
                data['raw_amount'] = 0
                data['payment_amount'] = 0
                data['pay_amount'] = 0

            # 幣別防禦補全
            if is_invalid(data.get('raw_currency')) and is_invalid(data.get('currency_type')):
                data['raw_currency'] = 'TWD'
            if is_invalid(data.get('payment_currency')) and is_invalid(data.get('pay_currency')):
                data['payment_currency'] = 'TWD'
        return data



    @field_validator('*', mode='before')
    @classmethod
    def sanitize_pandas_artifacts(cls, v: Any) -> Any:
        """
        全域型態防禦：將 Pandas 遺留的 '<NA>', 'nan', 'None', 空字串等統一洗淨為純 None
        """
        if v is None:
            return None
        
        # 處理 Pandas / NumPy NA/NaN
        if pd.isna(v):
            return None

        # 處理字串型態
        if isinstance(v, str):
            cleaned = v.strip()
            if cleaned.lower() in ['<na>', 'nan', 'none', 'nat', 'null', 'none.0', '']:
                return None
            return cleaned

        return v

    @field_validator('bank_no', mode='before')
    @classmethod
    def sanitize_bank_no(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().replace('.0', '')
        return s.zfill(3)[-3:] if s else None

    @field_validator('card_no', mode='before')
    @classmethod
    def sanitize_card_no(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().replace('.0', '')
        if not s or s.lower() in ['none', 'nan', '<na>']:
            return None
        # 取純數字末四碼或原始末四碼
        digits = re.findall(r'\d+', s)
        if digits:
            num_str = "".join(digits)
            return num_str.zfill(4)[-4:]
        return s[:4]

    @field_validator('statement_month', 'transaction_date', 'posting_date', 'conversion_date', mode='before')
    @classmethod
    def parse_flexible_date(cls, v: Any) -> Optional[date]:
        if v is None:
            return None
        if pd.isna(v):
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, (datetime, pd.Timestamp)):
            return v.date()

        s = str(v).strip()
        if not s or s.lower() in ['<na>', 'nan', 'none', 'nat', 'null', 'none.0', '']:
            return None

        # 嘗試一般日期解析
        try:
            # 支援 YYYY/MM/DD 或 YYYY-MM-DD
            dt = pd.to_datetime(s)
            if pd.isna(dt):
                return None
            return dt.date()
        except Exception:
            # 支援民國年如 112/08/15
            match = re.match(r'^(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})', s)
            if match:
                y, m, d = match.groups()
                year = int(y) + 1911 if int(y) < 1911 else int(y)
                return date(year, int(m), int(d))
            raise ValueError(f"無法解析日期格式: {v}")

    @field_validator('raw_amount', 'payment_amount', mode='before')
    @classmethod
    def parse_flexible_decimal(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if pd.isna(v):
            return None
        if isinstance(v, Decimal):
            return v
        if isinstance(v, (int, float)):
            return Decimal(str(v))

        s = str(v).strip().replace(',', '')
        if not s or s.lower() in ['<na>', 'nan', 'none', 'nat', 'null', 'none.0', '']:
            return None
        try:
            return Decimal(s)
        except Exception as e:
            raise ValueError(f"無法轉換為 Decimal 數值: {v} ({e})")

    @field_validator('raw_currency', 'payment_currency', mode='before')
    @classmethod
    def normalize_currency(cls, v: Any) -> str:
        if v is None:
            return "TWD"
        s = str(v).strip().upper()
        if not s or s in ['NTD', 'NT$', 'NT']:
            return "TWD"
        return s[:3]

    @model_validator(mode='after')
    def validate_business_constraints(self) -> 'RawTransactionSchema':
        """
        條件式約束校驗 (ADR 決策 2)：
        若是刷卡消費但 card_no 缺失，標記於 raw_extra 供審計
        """
        # 判斷是否為帳戶層級交易 (繳款、折抵、年費)
        merchant_lower = self.raw_merchant.lower()
        is_account_level = any(kw in merchant_lower for kw in [
            '繳款', '自動扣繳', '折抵', '紅利', '回饋金', '年費', '利息'
        ])

        if not is_account_level and not self.card_no:
            # 若為消費明細卻缺失卡號，記錄於 extra 字典中
            if self.raw_extra is None:
                self.raw_extra = {}
            self.raw_extra['anomaly_warning'] = "MISSING_CARD_NO_ON_PURCHASE"

        return self


__all__ = ['RawTransactionSchema']

