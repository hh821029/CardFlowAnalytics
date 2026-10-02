# etl/utils.py
"""
ETL 通用輔助工具模組
"""
import os
import logging
import pandas as pd
import const

from etl.schemas.db_col_mapper import StandardColumns, STANDARD_COLUMNS

logger = logging.getLogger(__name__)

OUTPUT_DIR = const.OUTPUT_DIR


# ==========================================
# 異常報告匯出工具 (Anomaly / Crash Report)
# ==========================================
def save_anomaly_report(df: pd.DataFrame, filename: str, message: str):
    """
    將異常或未定義的交易資料匯出至 output 資料夾，供使用者檢查。
    """
    try:
        if df is None or df.empty:
            return
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        report_path = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(report_path, index=False, encoding='utf-8-sig')
        logger.warning(f"⚠️ {message}，已將診斷資料匯出至: {report_path}")
    except Exception as e:
        logger.error(f"❌ 無法匯出異常報告: {e}")


__all__ = ['save_anomaly_report', 'StandardColumns', 'STANDARD_COLUMNS']
