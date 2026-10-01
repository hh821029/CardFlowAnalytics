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
from pydantic import (
    BaseModel,
    Field,
    AliasChoices,
    ConfigDict,
    field_validator,
    model_validator
)

logger = logging.getLogger(__name__)


def generate_raw_transaction_id(
    bank_no: str,
    statement_month: str,
    transaction_date: str,
    raw_merchant: str,
    payment_amount: str,
    card_no: Optional[str] = None,
    seq: int = 1
) -> str:
    """
    Stage 1 唯一識別碼生成器 (MD5 32碼)
    組合鍵：bank_no + statement_month + transaction_date + raw_merchant + payment_amount + card_no + seq
    """
    b_no = str(bank_no or "").strip().zfill(3)[-3:]
    s_mon = str(statement_month or "").strip()
    t_date = str(transaction_date or "").strip()
    m_name = str(raw_merchant or "").strip()
    p_amt = str(payment_amount or "").strip()
    c_no = str(card_no or "").strip() if card_no else ""
    s_num = str(seq)

    components = [b_no, s_mon, t_date, m_name, p_amt, c_no, s_num]
    raw_key = "".join(components)
    return hashlib.md5(raw_key.encode('utf-8')).hexdigest()


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
        description="全系統唯一交易流水識別碼 (MD5 32碼)"
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
        ...,
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
        ...,
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
        max_length=10,
        validation_alias=AliasChoices('raw_location', 'merchant_location', 'location'),
        description="原始消費國別代碼 (如 TW, JP, US)"
    )

    # 6. 特殊備份與稽核欄位
    raw_extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="銀行特有欄位備份 (如行動支付註記、專屬備註)"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="建立時間"
    )

    # ==========================================
    # Pydantic V2 欄位驗證與防禦消毒器
    # ==========================================

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


# ==========================================
# 批次驗證與 DataFrame 適配器
# ==========================================

def validate_raw_dataframe(
    df: pd.DataFrame,
    default_bank_no: Optional[str] = None,
    default_statement_month: Optional[date] = None
) -> Tuple[List[RawTransactionSchema], pd.DataFrame]:
    """
    批次驗證各銀行 Parser 輸出的 DataFrame，回傳：
    1. validated_schemas: 經過 Pydantic 嚴格檢驗的 Model 清單
    2. clean_df: 標準 raw_transactions 欄位且通過消毒的 DataFrame
    """
    if df is None or df.empty:
        return [], pd.DataFrame()

    df_working = df.copy()

    # 1. 預設值補充
    if default_bank_no and ('bank_no' not in df_working.columns or df_working['bank_no'].isna().all()):
        df_working['bank_no'] = str(default_bank_no).zfill(3)[-3:]

    if default_statement_month and ('statement_month' not in df_working.columns or df_working['statement_month'].isna().all()):
        df_working['statement_month'] = default_statement_month

    # 若缺少 raw_amount 但有 payment_amount，進行互補
    if 'raw_amount' not in df_working.columns and 'currency_amount' not in df_working.columns:
        if 'payment_amount' in df_working.columns:
            df_working['raw_amount'] = df_working['payment_amount']
        elif 'amount' in df_working.columns:
            df_working['raw_amount'] = df_working['amount']

    if 'payment_amount' not in df_working.columns and 'amount' in df_working.columns:
        df_working['payment_amount'] = df_working['amount']

    # 2. 逐列轉換與驗證
    records = df_working.to_dict(orient='records')
    validated_schemas: List[RawTransactionSchema] = []
    clean_records: List[Dict[str, Any]] = []

    # 計算同日同商家同金額的流水號 _seq
    seq_counter: Dict[str, int] = {}

    for row in records:
        try:
            # 計算流水號
            b_no = str(row.get('bank_no') or default_bank_no or "").strip()
            s_mon = str(row.get('statement_month') or default_statement_month or "").strip()
            t_date = str(row.get('transaction_date') or row.get('tx_date') or "").strip()
            m_name = str(row.get('raw_merchant') or row.get('merchant') or row.get('merchant_name') or "").strip()
            p_amt = str(row.get('payment_amount') or row.get('amount') or "").strip()
            c_no = str(row.get('card_no') or "").strip()

            key = f"{b_no}_{s_mon}_{t_date}_{m_name}_{p_amt}_{c_no}"
            seq_counter[key] = seq_counter.get(key, 0) + 1
            seq = seq_counter[key]

            # 若無 transaction_id，自動生成
            if not row.get('transaction_id') or pd.isna(row.get('transaction_id')):
                row['transaction_id'] = generate_raw_transaction_id(
                    bank_no=b_no,
                    statement_month=s_mon,
                    transaction_date=t_date,
                    raw_merchant=m_name,
                    payment_amount=p_amt,
                    card_no=c_no,
                    seq=seq
                )

            # 實例化 Pydantic 模型
            schema_inst = RawTransactionSchema.model_validate(row)
            validated_schemas.append(schema_inst)
            clean_records.append(schema_inst.model_dump())
        except Exception as e:
            logger.warning(f"⚠️ RawTransactionSchema 驗證未通過，略過髒資料: {e} | 原始內容: {row}")

    clean_df = pd.DataFrame(clean_records)
    return validated_schemas, clean_df
