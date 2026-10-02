# etl/schemas/transaction_id_generator.py
"""
唯一鍵值生成與去重器 (Key Generator & Deduplicator)
負責在資料寫入資料庫前生成全域唯一的主鍵 (transaction_id)，並執行去重。
包含 Stage 1 (Raw Bronze 表) 與 Stage 4 (Cleaned Silver/Gold 表) 之識別碼生成邏輯。
"""
import os
import hashlib
import logging
import pandas as pd
from typing import Optional, Dict, Any, List

import const
from etl.schemas.db_col_mapper import StandardColumns

logger = logging.getLogger(__name__)


def hash_components(*parts) -> str:
    """
    全系統統一 Transaction ID 生成核心：
    將所有維度與流水號欄位去除首尾空格並串接，產出 32 碼 SHA-256 十六進位摘要
    """
    raw_key = "".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:32]

class TransactionIdGenerator:
    """
    全系統交易識別碼生成與去重器 (Key Generator & Deduplicator)
    統籌 Stage 1 (Raw Ingestion) 與 Stage 4 (Cleaned Load) 之主鍵生成邏輯。
    """
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or const.OUTPUT_DIR
        self.group_cols = StandardColumns.ID_GROUP_COLUMNS

    @classmethod
    def assign_raw_transaction_id(
        cls,
        row: Dict[str, Any],
        seq_counter: Optional[Dict[str, int]] = None,
        default_bank_no: Optional[str] = None,
        default_statement_month: Optional[Any] = None
    ) -> str:
        """
        為單筆 Raw 字典資料計算流水號 seq 並生成/指派 transaction_id。
        若未傳入 seq_counter 則單筆 seq 預設為 1。
        若 row 已具備有效 transaction_id 則直接回傳。
        """
        if row.get('transaction_id') and not pd.isna(row.get('transaction_id')):
            return str(row['transaction_id'])

        raw_bank_no = row.get('bank_no') if not pd.isna(row.get('bank_no')) else default_bank_no
        b_no = str(raw_bank_no).strip().zfill(3)[-3:] if raw_bank_no else ""

        raw_s_mon = row.get('statement_month') if not pd.isna(row.get('statement_month')) else default_statement_month
        s_mon = str(raw_s_mon).strip() if raw_s_mon else ""

        raw_t_date = row.get('transaction_date') or row.get('tx_date')
        t_date = str(raw_t_date).strip() if not pd.isna(raw_t_date) and raw_t_date else ""

        raw_m_name = row.get('raw_merchant') or row.get('merchant') or row.get('merchant_name')
        m_name = str(raw_m_name).strip() if not pd.isna(raw_m_name) and raw_m_name else ""

        raw_p_amt = row.get('payment_amount') or row.get('amount')
        p_amt = str(raw_p_amt).strip() if not pd.isna(raw_p_amt) and raw_p_amt else ""

        raw_c_no = row.get('card_no')
        c_no = str(raw_c_no).strip() if not pd.isna(raw_c_no) and raw_c_no else ""

        if seq_counter is not None:
            key = f"{b_no}_{s_mon}_{t_date}_{m_name}_{p_amt}_{c_no}"
            seq_counter[key] = seq_counter.get(key, 0) + 1
            seq = seq_counter[key]
        else:
            seq = 1

        row['transaction_id'] = hash_components(b_no, s_mon, t_date, m_name, p_amt, c_no, seq)
        return row['transaction_id']

    def _generate_transaction_id(self, row: pd.Series) -> str:
        """
        動態串接 group_cols 欄位值 + 同日流水號 _seq 生成 SHA-256 (32碼)
        """
        components = [row.get(col) for col in self.group_cols]
        components.append(row.get('_seq'))
        return hash_components(*components)

    def generate_and_deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        為 DataFrame 產生 transaction_id（若缺失），並依據 transaction_id 移除重複紀錄。
        """
        if df is None or df.empty:
            logger.warning("⚠️ 沒有資料可供處理 transaction_id。")
            return pd.DataFrame() if df is None else df

        df_work = df.copy()

        # 判斷是否全量具備有效之 transaction_id
        has_existing_id = (
            'transaction_id' in df_work.columns and
            df_work['transaction_id'].notna().all() and
            (df_work['transaction_id'].astype(str).str.strip() != '').all()
        )

        # 僅在缺少 transaction_id 時才計算分組流水號並動態生成
        if not has_existing_id:
            for col in self.group_cols:
                if col not in df_work.columns:
                    df_work[col] = None

            df_work['_seq'] = df_work.groupby(self.group_cols, dropna=False).cumcount().astype(str)
            df_work['transaction_id'] = df_work.apply(self._generate_transaction_id, axis=1)
            df_work = df_work.drop(columns=['_seq'])

        # 移除重複交易 (Deduplication)
        duplicated_mask = df_work.duplicated(subset=['transaction_id'], keep='first')
        if duplicated_mask.any():
            df_duplicates = df_work[duplicated_mask].copy()
            logger.info(f"🧹 移除了 {len(df_duplicates)} 筆重複交易紀錄。")
            
            if self.output_dir:
                os.makedirs(self.output_dir, exist_ok=True)
                debug_csv_path = os.path.join(self.output_dir, 'dropped_duplicates.csv')
                df_duplicates.to_csv(debug_csv_path, index=False, encoding='utf-8-sig')
                logger.info(f"🔍 被移除的重複資料已存至: {debug_csv_path}")

        filtered = df_work[~duplicated_mask]
        return pd.DataFrame(filtered)


__all__ = ['TransactionIdGenerator', 'hash_components']
