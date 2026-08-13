# etl/etl_api.py
"""
ETL 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
提供獨立且高內聚的帳單解析、正規化與資料入庫 Pipeline
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Dict, Any

# 1. 引入核心配置與常量
import const

# 2. 引入資料庫載入器與工具
try:
    from database.loaders.db_factory import get_db_loader
    from database.loaders.sqlite_loader import SQLiteLoader
    from etl.bills_to_db import BillsToDB
    from database.loaders.schema_enforcer import SchemaEnforcer
except ImportError:
    get_db_loader = None
    SQLiteLoader = None
    BillsToDB = None
    SchemaEnforcer = None

# 3. 引入拆分後的 Extract 與 Transform 階段模組
from etl.etl_extraction import (
    extract_raw_data,
    save_anomaly_report
)
from etl.etl_transformation import transform_data

# 4.路徑設定
DATA_DIR = const.DATA_DIR
OUTPUT_DIR = const.OUTPUT_DIR
CONFIG_DIR = const.CONFIG_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger(__name__)



# ==========================================
# 主流程 (ETL Controller & Pipeline)
# ==========================================
def run_etl_pipeline(force: bool = True, input_dir: Optional[str] = None, db_backend: Optional[str] = None) -> bool:
    """
    執行獨立且完整的 ETL Pipeline:
    1. 掃描帳單並進行 SHA-256 去重檢查 (etl_extraction)
    2. 呼叫對應銀行的 Parser 提取原始資料 (etl_extraction)
    3. 呼叫 DataRefiner 進行商家正規化與前綴處理 (etl_transformation)
    4. 入庫至 PostgreSQL / SQLite 資料庫
    """
    logger.info(f"🚀 ETL 流程啟動 (獨立模組執行)... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    merged_df: Optional[pd.DataFrame] = None

    try:
        # --- STEP 1: Extract (讀取與解析) ---
        merged_df = extract_raw_data(force=force, input_dir=input_dir)
        if merged_df is None or merged_df.empty:
            # 即使本次執行跳過所有檔案，也主動確保 PostgreSQL 視圖被建立
            try:
                if get_db_loader:
                    loader = get_db_loader(db_backend=db_backend)
                    if hasattr(loader, 'create_enriched_view'):
                        loader.create_enriched_view()
            except Exception as e:
                logger.debug(f"跳過視圖檢查: {e}")
            return True

        # --- STEP 2: Transform (清洗與商業邏輯) ---
        final_df = transform_data(merged_df)
        
        # --- STEP 3: Filter & Sort (最終整理) ---
        available_cols = [c for c in const.STANDARD_COLUMNS if c in final_df.columns]
        sliced_df = final_df[available_cols]
        if isinstance(sliced_df, pd.DataFrame):
            final_df = sliced_df
        else:
            final_df = pd.DataFrame(sliced_df)
 
        if SchemaEnforcer:
            final_df = SchemaEnforcer.enforce(final_df)
        
        if const.COL_TXN_DATE in final_df.columns:
            try:
                final_df = final_df.sort_values(by=const.COL_TXN_DATE)
            except Exception as e:
                logger.error(f"❌ 排序失敗: {e}")

        # --- STEP 4: Load (存檔) & 寫入資料庫 ---
        csv_output_path = os.path.join(OUTPUT_DIR, 'result_final.csv')
        final_df.to_csv(csv_output_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 清洗完成，已輸出至 {csv_output_path}")

        if (get_db_loader is not None or SQLiteLoader is not None) and BillsToDB:
            logger.info("📦 準備載入資料庫...")
            processor = BillsToDB(OUTPUT_DIR)
            db_df = processor.prepare_data(final_df)

            if get_db_loader is not None:
                loader = get_db_loader(db_backend=db_backend)
            elif SQLiteLoader is not None:
                loader = SQLiteLoader(db_path=const.DB_PATH)
            else:
                raise ImportError("無法取得任何有效的 DB Loader")

            db_mode = 'replace' if force else 'append'
            loader.load(
                db_df, 
                table_name='all_transactions', 
                mode=db_mode,
                indices=['transaction_date', 'merchant_name', 'card_no', 'transaction_id']
            )

            # 顯式觸發視圖管理 (若為 PostgreSQL Loader)
            if hasattr(loader, '_get_engine'):
                try:
                    from etl.views_manager import create_all_views
                    create_all_views(loader._get_engine())
                except Exception as ve:
                    logger.debug(f"視圖自動觸發提示: {ve}")
        else:
            logger.warning("⚠️ 載入器缺失，略過資料庫寫入。")

        return True
        
    except Exception as e:
        logger.error(f"🚨 ETL 流程發生未預期嚴重錯誤: {e}")
        if merged_df is not None:
            save_anomaly_report(merged_df, 'crash_dump_global.csv', "全域流程崩潰，已嘗試救援資料")
        return False
