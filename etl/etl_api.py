# etl/etl_api.py
"""
ETL 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
負責協調 Stage 1 (Extract + Ingestion) 與 Stage 2 (Refinement + Load)
"""
import os
import pandas as pd
import logging
from typing import Optional

# 1. 引入核心配置與常量
import const

# 2. 引入 Extract 與 Refinement 階段模組
from etl.extraction import extract_raw_data
from etl.refinement import refine_transactions

# 3. 引入 Schema 驗證與資料庫工具 (Stage 1 Ingestion所需)
from etl.schemas.raw_transaction import validate_raw_dataframe
from database.loaders.views_manager import ViewsManager
from database.loaders.db_factory import get_db_loader

# 4. 引入 DB 讀取模組 (Stage 2 Refinement所需)
try:
    from database.loaders.db_reader import DBReader
except ImportError:
    DBReader = None

from etl.exceptions import save_anomaly_report

# 5. 路徑設定
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
) -> bool:
    """
    Stage 1 Pipeline (Extract & Raw Ingestion):
    1. Extract: 掃描帳單檔案、去重比對、分派 Parser 提取原始資料 (etl.extraction)
    2. Stage 1 Ingestion: 透過 Pydantic V2 驗證並同步寫入 raw_transactions 原始事實表
    """
    logger.info(f"🚀 [Stage 1 Pipeline] 啟動原始資料提取與入庫... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    # 1. Extract (讀取與解析)
    merged_df = extract_raw_data(force=force, input_dir=input_dir)
    if merged_df is None or merged_df.empty:
        logger.info("ℹ️ Stage 1 無新資料需要處理。")
        return True

    raw_clean_df: Optional[pd.DataFrame] = None

    # 2. Stage 1 Ingestion (Bronze 表同步入庫)
    try:
        ViewsManager.ensure_raw_schema(db_backend=db_backend)
        raw_schemas, raw_clean_df = validate_raw_dataframe(merged_df)
        if not raw_clean_df.empty:
            loader = get_db_loader(db_backend=db_backend)
            loader.load(raw_clean_df, table_name='raw_transactions', mode='append')
            logger.info(f"💾 [Stage 1 Bronze] 已同步入庫 {len(raw_clean_df)} 筆原始資料至 raw_transactions")
            return True
        else:
            logger.warning("⚠️ [Stage 1 Bronze] 驗證消毒後無有效資料可入庫。")
            return False
    except Exception as raw_e:
        logger.warning(f"⚠️ [Stage 1 Bronze] 寫入 raw_transactions 略過或失敗 (非致命): {raw_e}")
        dump_df = raw_clean_df if (raw_clean_df is not None and not raw_clean_df.empty) else merged_df
        if dump_df is not None and not dump_df.empty:
            dump_path = os.path.join(OUTPUT_DIR, 'raw_transactions_failed_dump.csv')
            dump_df.to_csv(dump_path, index=False, encoding='utf-8-sig')
            logger.warning(f"🔍 寫入失敗之原始資料表已輸出至: {dump_path}，請前往 output/ 查看。")
        return False

def run_stage2_pipeline(
    raw_df: Optional[pd.DataFrame] = None,
    db_backend: Optional[str] = None, 
    force: bool = True,
    db_path: Optional[str] = None
) -> bool:
    """
    Stage 2 獨立重跑管線 (免重新掃描檔案)：
    1. 自資料庫 raw_transactions 讀取未清洗的標準原始資料 (若未直接傳入 raw_df)
    2. 調用 refine_transactions 重新計算商業規則
    3. 入庫至 all_transactions / refined_transactions 並自動刷新 Views 與索引
    """
    logger.info("🚀 [Stage 2 Pipeline] 啟動商業規則重算 (Stage 2 清洗與入庫)...")

    try:
        # 1. 若未傳入 raw_df，自 raw_transactions 讀取資料
        if raw_df is None or raw_df.empty:
            if DBReader is None:
                logger.error("❌ 無法載入 DBReader 模組，請確認資料庫配置。")
                return False
            logger.info("📥 正在從資料庫讀取 [raw_transactions]...")
            raw_df = DBReader.read_sql("SELECT * FROM raw_transactions", db_path=db_path)

            if raw_df is None or raw_df.empty:
                logger.warning("⚠️ 資料庫 [raw_transactions] 表目前無資料！請先執行完整 ETL (選項 1) 解析帳單入庫。")
                return False

        logger.info(f"📊 成功獲取 {len(raw_df)} 筆原始交易資料進行 Stage 2 清洗")

        # 2. 執行純記憶體商業清洗
        refined_df = refine_transactions(raw_df)
        if refined_df is None or refined_df.empty:
            logger.error("❌ Stage 2 商業清洗後無資料產出。")
            return False

        # 3. 入庫與視圖刷新
        from etl.loading import load_data
        success = load_data(
            final_df=refined_df,
            force=force,
            db_backend=db_backend,
            output_dir=OUTPUT_DIR,
            db_path=db_path
        )

        if success:
            logger.info("🎉 [Stage 2 Pipeline] 商業規則重算與資料庫入庫刷新全部成功！")
        return success

    except Exception as e:
        logger.error(f"🚨 [Stage 2 Pipeline] 重跑流程發生異常: {e}", exc_info=True)
        return False



def run_etl_pipeline(force: bool = True, input_dir: Optional[str] = None, db_backend: Optional[str] = None) -> bool:
    """
    完整雙階式 ETL Pipeline (Stage 1 + Stage 2 組合進入點):
    1. run_stage1_pipeline: 掃描檔案、解析並入庫至 raw_transactions
    2. run_stage2_pipeline: 自 raw_transactions 重算商業特徵、歸戶分類並入庫 all_transactions 與 Views
    """
    logger.info(f"🚀 ETL 流程啟動 (獨立模組執行)... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    try:
        # 段落一: Stage 1 Pipeline (Extract + Ingestion)
        s1_success = run_stage1_pipeline(force=force, input_dir=input_dir, db_backend=db_backend)
        if not s1_success:
            logger.error("❌ Stage 1 流程執行失敗，終止後續管線。")
            return False

        # 段落二: Stage 2 Pipeline (Refine + Load，直接自 raw_transactions 讀取)
        s2_success = run_stage2_pipeline(db_backend=db_backend, force=force)
        return s2_success
        
    except Exception as e:
        logger.error(f"🚨 ETL 流程發生未預期嚴重錯誤: {e}", exc_info=True)
        return False


__all__ = ["run_etl_pipeline", "run_stage1_pipeline", "run_stage2_pipeline", "refine_transactions"]
