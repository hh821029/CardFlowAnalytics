# etl/schemas/validation.py
"""
Stage 1 (Bronze) 原始帳單資料驗證與適配器 (Raw Transaction DataFrame Validator)
負責批次校驗各銀行 Parser 輸出之 DataFrame，自動執行欄位別名收斂、
交易流水號指派、非標準欄位封裝 (raw_extra) 與 Pydantic V2 型態契約執法。
"""
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Optional, Dict, Any, List, Tuple, cast
import pandas as pd
import numpy as np

from etl.schemas.raw_transaction import RawTransactionSchema
from etl.schemas.transaction_id_generator import TransactionIdGenerator

logger = logging.getLogger(__name__)

# 標準 Stage 1 欄位名稱集合（包含常見別名，用於區分 raw_extra）
STANDARD_RAW_FIELDS = {
    'transaction_id', 'bank_no', 'statement_month', 'transaction_date',
    'posting_date', 'raw_merchant', 'raw_currency', 'raw_amount',
    'payment_currency', 'payment_amount', 'card_no', 'raw_location',
    'raw_extra', 'created_at',
    # 各種常見別名
    'merchant', 'merchant_name', 'currency_type', 'currency',
    'currency_amount', 'amount', 'pay_currency', 'pay_amount',
    'card_last_4', 'merchant_location', 'location', 'tx_date'
}


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
        df_working['bank_no'] = default_bank_no.zfill(3)[-3:]

    if default_statement_month and ('statement_month' not in df_working.columns or df_working['statement_month'].isna().all()):
        df_working['statement_month'] = default_statement_month

    # 若缺少 raw_amount 但有 payment_amount，進行互補
    p_col = df_working['payment_amount'] if 'payment_amount' in df_working.columns else df_working.get('amount')
    if 'raw_amount' in df_working.columns and p_col is not None:
        df_working['raw_amount'] = df_working['raw_amount'].combine_first(p_col)
    elif 'currency_amount' in df_working.columns and p_col is not None:
        df_working['raw_amount'] = df_working['currency_amount'].combine_first(p_col)
    elif p_col is not None:
        df_working['raw_amount'] = p_col

    if 'payment_amount' in df_working.columns and p_col is not None:
        df_working['payment_amount'] = df_working['payment_amount'].combine_first(p_col)
    elif p_col is not None:
        df_working['payment_amount'] = p_col

    records = cast(List[Dict[str, Any]], df_working.to_dict(orient='records'))
    validated_schemas: List[RawTransactionSchema] = []
    clean_records: List[Dict[str, Any]] = []
    seq_counter: Dict[str, int] = {}

    for row in records:
        try:
            # 計算流水號並明確賦值 transaction_id
            row['transaction_id'] = TransactionIdGenerator.assign_raw_transaction_id(
                row=row,
                seq_counter=seq_counter,
                default_bank_no=default_bank_no,
                default_statement_month=default_statement_month
            )

            # 收集特有欄位進入 raw_extra (如行動支付註記、vpc_type 等)
            extra_collector = {}
            if isinstance(row.get('raw_extra'), dict):
                extra_collector.update(row['raw_extra'])

            for k, v in row.items():
                if k not in STANDARD_RAW_FIELDS and not pd.isna(v) and v is not None and v != "":
                    if isinstance(v, (datetime, date, pd.Timestamp)):
                        extra_collector[k] = v.strftime('%Y-%m-%d')
                    elif isinstance(v, Decimal):
                        extra_collector[k] = float(v)
                    elif isinstance(v, (np.integer, np.int64)):
                        extra_collector[k] = int(v)
                    elif isinstance(v, (np.floating, np.float64)):
                        extra_collector[k] = float(v)
                    else:
                        extra_collector[k] = str(v)
            if extra_collector:
                row['raw_extra'] = extra_collector

            # 實例化 Pydantic 模型
            schema_inst = RawTransactionSchema.model_validate(row)
            validated_schemas.append(schema_inst)
            clean_records.append(schema_inst.model_dump())
        except Exception as e:
            logger.warning(f"⚠️ RawTransactionSchema 驗證未通過，略過髒資料: {e} | 原始內容: {row}")

    clean_df = pd.DataFrame(clean_records)
    if not clean_df.empty:
        for amt_col in ['raw_amount', 'payment_amount']:
            if amt_col in clean_df.columns:
                clean_df[amt_col] = cast(pd.Series, pd.to_numeric(clean_df[amt_col], errors='coerce')).fillna(0.0).astype(float)
        for date_col in ['statement_month', 'transaction_date', 'posting_date', 'conversion_date']:
            if date_col in clean_df.columns:
                clean_df[date_col] = clean_df[date_col].apply(
                    lambda v: v.strftime('%Y-%m-%d') if isinstance(v, (date, datetime, pd.Timestamp)) else (str(v) if pd.notna(v) and v is not None else None)
                )

    return validated_schemas, clean_df


__all__ = ['validate_raw_dataframe', 'STANDARD_RAW_FIELDS']
