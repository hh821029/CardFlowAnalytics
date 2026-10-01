# etl/transformation.py
"""
ETL 模組 - Transform (向後相容過渡轉接層)
將邏輯完全委派至 etl.refinement 模組，以落實 Stage 2 (Silver) 解耦架構
"""
import pandas as pd
from typing import Optional

from etl.refinement import DataRefiner, refine_transactions, run_stage2_pipeline


def transform_data(merged_df: pd.DataFrame) -> pd.DataFrame:
    """
    相容舊版介面：呼叫 Stage 2 refine_transactions
    """
    return refine_transactions(merged_df)


__all__ = ["DataRefiner", "transform_data", "refine_transactions", "run_stage2_pipeline"]
