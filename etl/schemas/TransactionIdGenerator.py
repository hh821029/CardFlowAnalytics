# etl/schemas/TransactionIdGenerator.py
"""
唯一鍵值生成與去重器 (Key Generator & Deduplicator)
負責在資料寫入資料庫前生成全域唯一的主鍵 (transaction_id)，並執行去重。
"""
import os
import hashlib
import logging
import pandas as pd
from typing import Optional

import const
from etl.schemas.DBColMapper import StandardColumns

logger = logging.getLogger(__name__)


class TransactionIdGenerator:
    """
    負責在資料寫入資料庫前生成全域唯一的主鍵 (transaction_id)，並執行去重。
    """
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or const.OUTPUT_DIR
        self.group_cols = StandardColumns.ID_GROUP_COLUMNS

    def _generate_transaction_id(self, row: pd.Series) -> str:
        """
        動態串接 group_cols 欄位值 + 同日流水號 _seq 生成 SHA-256 (32碼)
        """
        def safe_str(val):
            return str(val).strip() if pd.notna(val) else ""
        # 動態取得所有分組欄位的值，最後再加上 _seq
        components = [safe_str(row.get(col)) for col in self.group_cols]
        components.append(safe_str(row.get('_seq')))
        
        unique_str = "".join(components)
        return hashlib.sha256(unique_str.encode('utf-8')).hexdigest()[:32]

    def generate_and_deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        為 DataFrame 產生 _seq 與 transaction_id，並移除重複紀錄。
        """
        if df is None or df.empty:
            logger.warning("⚠️ 沒有資料可供處理 transaction_id。")
            return pd.DataFrame() if df is None else df

        df_work = df.copy()

        # 1. 生成同組交易流水號 _seq
        for col in self.group_cols:
            if col not in df_work.columns:
                df_work[col] = None

        df_work['_seq'] = df_work.groupby(self.group_cols, dropna=False).cumcount().astype(str)
        
        # 若已有非空 transaction_id 且每列皆具備，保留 Stage 1 確立之主鍵；否則動態生成
        has_existing_id = (
            'transaction_id' in df_work.columns and
            df_work['transaction_id'].notna().all() and
            (df_work['transaction_id'].astype(str).str.strip() != '').all()
        )
        if not has_existing_id:
            df_work['transaction_id'] = df_work.apply(self._generate_transaction_id, axis=1)

        # 2. 移除重複交易 (Deduplication)
        duplicated_mask = df_work.duplicated(subset=['transaction_id'], keep='first')
        if duplicated_mask.any():
            df_duplicates = df_work[duplicated_mask].copy()
            logger.info(f"🧹 移除了 {len(df_duplicates)} 筆重複交易紀錄。")
            
            if self.output_dir:
                os.makedirs(self.output_dir, exist_ok=True)
                debug_csv_path = os.path.join(self.output_dir, 'dropped_duplicates.csv')
                df_duplicates.to_csv(debug_csv_path, index=False, encoding='utf-8-sig')
                logger.info(f"🔍 被移除的重複資料已存至: {debug_csv_path}")

        # 確保型態明確為 DataFrame 且安全移除流水號暫存欄位
        filtered = df_work[~duplicated_mask]
        df_result = pd.DataFrame(filtered)

        if '_seq' in df_result.columns:
            df_result = df_result.drop(columns=['_seq'])

        return df_result


__all__ = ['TransactionIdGenerator']
