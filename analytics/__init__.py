# analytics/__init__.py
"""
Analytics 分析核心模組
1. 統一路徑常數 (SSOT) 與自動建立目錄
2. 資料庫 rfm_transactions 視圖與 Schema 欄位一致性檢查
"""
import os
import logging
from typing import List, Tuple
import pandas as pd
import const
from etl.utils import StandardColumns
from database.loaders.db_reader import DBReader

logger = logging.getLogger(__name__)

# ==========================================
# 1. 統一路徑常數 (SSOT)
# ==========================================
BASE_OUTPUT_DIR: str = const.OUTPUT_DIR
MATRIX_OUTPUT_DIR: str = os.path.join(BASE_OUTPUT_DIR, 'matrix')
RFM_OUTPUT_DIR: str = os.path.join(BASE_OUTPUT_DIR, 'rfm')
DB_PATH: str = const.DB_PATH
CONFIG_DIR: str = const.CONFIG_DIR

# 自動建立輸出目錄
for _dir in [BASE_OUTPUT_DIR, MATRIX_OUTPUT_DIR, RFM_OUTPUT_DIR]:
    os.makedirs(_dir, exist_ok=True)

# ==========================================
# 2. Schema 欄位一致性檢查
# ==========================================
EXPECTED_RFM_COLUMNS: List[str] = StandardColumns.RFM_TRANSACTIONS

def validate_analytics_schema(db_path: str = DB_PATH) -> Tuple[bool, List[str]]:
    """
    檢查資料庫中是否存在 rfm_transactions 視圖/資料表，並驗證其欄位是否符合 StandardColumns.RFM_TRANSACTIONS。
    
    Returns:
        Tuple[bool, List[str]]: (是否通過, 缺失之欄位清單)
    """
    try:
        df_sample = DBReader.read_sql("SELECT * FROM rfm_transactions LIMIT 0", db_path=db_path)
        actual_cols = set(df_sample.columns)
        if 'merchant_name' in actual_cols and 'merchant' not in actual_cols:
            actual_cols.add('merchant')
        if 'merchant' in actual_cols and 'merchant_name' not in actual_cols:
            actual_cols.add('merchant_name')
            
        missing_cols = [c for c in EXPECTED_RFM_COLUMNS if c not in actual_cols]
        
        if missing_cols:
            logger.warning(f"⚠️ [Analytics Schema] rfm_transactions 缺少預期欄位: {missing_cols}")
            return False, missing_cols
            
        logger.debug("✅ [Analytics Schema] rfm_transactions 視圖存在且欄位驗證通過。")
        return True, []
    except Exception as e:
        logger.error(f"❌ [Analytics Schema] 無法讀取 rfm_transactions 視圖: {e}")
        return False, EXPECTED_RFM_COLUMNS

__all__ = [
    'BASE_OUTPUT_DIR',
    'MATRIX_OUTPUT_DIR',
    'RFM_OUTPUT_DIR',
    'DB_PATH',
    'CONFIG_DIR',
    'EXPECTED_RFM_COLUMNS',
    'validate_analytics_schema'
]
