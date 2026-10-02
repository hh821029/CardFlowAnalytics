# etl/etl_api.py
"""
ETL 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
負責協調 Stage 1 Extract/Ingestion、Stage 2 Refinement 與 Load 三大階段 Pipeline
"""
import os
import pandas as pd
import logging
from typing import Optional

# 1. 引入核心配置與常量
import const

# 2. 引入 Extract、Refine 與 Load 階段模組
from etl.extraction import extract_raw_data
from etl.refinement import refine_transactions, run_stage2_pipeline
from etl.loading import load_data
from etl.utils import save_anomaly_report

# 3. 路徑設定
OUTPUT_DIR = const.OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger(__name__)


# ==========================================
# 主流程 (ETL Controller & Pipeline)
# ==========================================
def run_stage1_pipeline(
    force: bool = True,
    input_dir: Optional[str] = None,
    db_backend: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    Stage 1 Pipeline (Extract & Raw Ingestion):
    1. Extract: 掃描帳單檔案、去重比對、分派 Parser 提取原始資料 (etl.extraction)
    2. Stage 1 Ingestion: 透過 Pydantic V2 驗證並同步寫入 raw_transactions 表
    回傳提取並驗證消毒後的原始 DataFrame (供後續 Stage 2 清洗使用)
    """
    logger.info(f"🚀 [Stage 1 Pipeline] 啟動原始資料提取與入庫... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    # 1. Extract (讀取與解析)
    merged_df = extract_raw_data(force=force, input_dir=input_dir)
    if merged_df is None or merged_df.empty:
        logger.info("ℹ️ 無新資料需要處理。")
        return None

    raw_clean_df: Optional[pd.DataFrame] = None

    # 2. Stage 1 Ingestion (Bronze 表同步入庫)
    try:
        from etl.schemas.raw_transaction import validate_raw_dataframe
        from database.loaders.views_manager import ViewsManager
        from database.loaders.db_factory import get_db_loader

        ViewsManager.ensure_raw_schema(db_backend=db_backend)
        raw_schemas, raw_clean_df = validate_raw_dataframe(merged_df)
        if not raw_clean_df.empty:
            loader = get_db_loader(db_backend=db_backend)
            loader.load(raw_clean_df, table_name='raw_transactions', mode='append')
            logger.info(f"💾 [Stage 1 Bronze] 已同步入庫 {len(raw_clean_df)} 筆原始資料至 raw_transactions")
    except Exception as raw_e:
        logger.warning(f"⚠️ [Stage 1 Bronze] 寫入 raw_transactions 略過或失敗 (非致命): {raw_e}")
        dump_df = raw_clean_df if (raw_clean_df is not None and not raw_clean_df.empty) else merged_df
        if dump_df is not None and not dump_df.empty:
            dump_path = os.path.join(OUTPUT_DIR, 'raw_transactions_failed_dump.csv')
            dump_df.to_csv(dump_path, index=False, encoding='utf-8-sig')
            logger.warning(f"🔍 寫入失敗之原始資料表已輸出至: {dump_path}，請前往 output/ 查看。")

    target_raw_df = raw_clean_df if (raw_clean_df is not None and not raw_clean_df.empty) else merged_df
    return target_raw_df


def run_etl_pipeline(force: bool = True, input_dir: Optional[str] = None, db_backend: Optional[str] = None) -> bool:
    """
    執行完整雙階式 ETL Pipeline (兩段式組合):
    - 段落一 (Stage 1 Pipeline):
        1. Extract: 掃描帳單檔案、去重比對、分派 Parser 提取原始資料 (etl.extraction)
        2. Stage 1 Ingestion: 透過 Pydantic V2 驗證並同步寫入 raw_transactions 表
    - 段落二 (Stage 2 Pipeline):
        3. Stage 2 Refine: 調用 refine_transactions 進行卡片歸戶、商家正規化與交易分類 (etl.refinement)
        4. Load: 標準欄位收斂、型態執法、流水號生成與去重、存入 CSV 與 Database (etl.loading)
    """
    logger.info(f"🚀 ETL 流程啟動 (獨立模組執行)... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    try:
        # --- 段落一: Stage 1 (Extract + Ingestion) ---
        raw_df = run_stage1_pipeline(force=force, input_dir=input_dir, db_backend=db_backend)
        if raw_df is None or raw_df.empty:
            logger.info("ℹ️ Stage 1 無新資料產出，流程結束。")
            return True

        # --- 段落二: Stage 2 (Refine + Load) ---
        success = run_stage2_pipeline(
            raw_df=raw_df,
            db_backend=db_backend,
            force=force
        )

        return success
        
    except Exception as e:
        logger.error(f"🚨 ETL 流程發生未預期嚴重錯誤: {e}", exc_info=True)
        return False


__all__ = ["run_etl_pipeline", "run_stage1_pipeline", "run_stage2_pipeline", "refine_transactions"]

