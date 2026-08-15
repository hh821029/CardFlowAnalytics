# etl/etl_api.py
"""
ETL 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
負責協調 Extract (extraction.py)、Transform (transformation.py) 與 Load (loading.py) 三大階段 Pipeline
"""
import os
import pandas as pd
import logging
from typing import Optional

# 1. 引入核心配置與常量
import const

# 2. 引入 Extract、Transform 與 Load 階段模組
from etl.extraction import extract_raw_data
from etl.transformation import transform_data
from etl.loading import load_data
from etl.utils import save_anomaly_report

# 3. 路徑設定
OUTPUT_DIR = const.OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger(__name__)


# ==========================================
# 主流程 (ETL Controller & Pipeline)
# ==========================================
def run_etl_pipeline(force: bool = True, input_dir: Optional[str] = None, db_backend: Optional[str] = None) -> bool:
    """
    執行獨立且完整的 ETL Pipeline:
    1. Extract: 掃描帳單檔案、SHA-256 去重比對、分派 Parser 提取原始資料 (etl.extraction)
    2. Transform: 調用 DataRefiner 進行商家正規化、前綴拆分與交易分類 (etl.transformation)
    3. Load: 標準欄位收斂、型態執法、流水號生成與去重、存入 CSV 與 Database (etl.loading)
    """
    logger.info(f"🚀 ETL 流程啟動 (獨立模組執行)... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    merged_df: Optional[pd.DataFrame] = None

    try:
        # --- STEP 1: Extract (讀取與解析) ---
        merged_df = extract_raw_data(force=force, input_dir=input_dir)
        if merged_df is None or merged_df.empty:
            logger.info("ℹ️ 無新資料需要處理。")
            return True

        # --- STEP 2: Transform (清洗與商業邏輯) ---
        final_df = transform_data(merged_df)

        # --- STEP 3 & 4: Load (欄位收斂、去重、入庫) ---
        success = load_data(
            final_df=final_df,
            force=force,
            db_backend=db_backend,
            output_dir=OUTPUT_DIR
        )

        return success
        
    except Exception as e:
        logger.error(f"🚨 ETL 流程發生未預期嚴重錯誤: {e}")
        if merged_df is not None:
            save_anomaly_report(merged_df, 'crash_dump_global.csv', "全域流程崩潰，已嘗試救援資料")
        return False
