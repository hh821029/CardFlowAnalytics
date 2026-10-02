# etl/etl_api.py
"""
ETL 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
負責協調 Stage 1 (Extract + Ingestion) 與 Stage 2 (Refinement + Load)
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Dict, Any, Tuple, NamedTuple, cast

# 1. 引入核心配置與常量
import const

# 2. 引入 Extract 與 Refinement 階段模組
from etl.parsers.dispatcher import extract_raw_data_stream, extract_file
from etl.refinement import refine_transactions

# 3. 引入 Schema 驗證與資料庫工具 (Stage 1 Ingestion所需)
from etl.schemas.validation import validate_raw_dataframe
from database.loaders.views_manager import ViewsManager
from database.loaders.db_factory import get_db_loader

# 4. 引入 DB 讀取與檔案登記模組
try:
    from database.loaders.db_reader import DBReader
except ImportError:
    DBReader = None

try:
    from profiles.loaders.file_registry import FileRegistryManager
except ImportError:
    FileRegistryManager = None

from etl.exceptions import save_anomaly_report

# 5. 路徑設定
OUTPUT_DIR = const.OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger(__name__)


class Stage1Result(NamedTuple):
    """
    Stage 1 / Extraction 執行結果物件 (支援 Unpack 與布林真假值相容判定)
    - 解構賦值: success, df = run_extraction_pipeline()
    - 條件判定: if not run_extraction_pipeline():
    """
    success: bool
    df: Optional[pd.DataFrame] = None

    def __bool__(self) -> bool:
        return self.success


# ==========================================
# 主流程 (ETL Controller & Pipeline)
# ==========================================
def run_extraction_pipeline(
    force: bool = True,
    input_dir: Optional[str] = None,
    db_backend: Optional[str] = None,
    db_path: Optional[str] = None
) -> Stage1Result:
    """
    Stage 1 Pipeline (Extraction & Per-File Raw Ingestion):
    1. Extract: 逐檔串流掃描帳單檔案、去重比對、分派 Parser 提取原始資料 (etl.parsers.dispatcher.extract_raw_data_stream)
    2. Stage 1 Ingestion: 逐檔透過 Pydantic V2 驗證並同步寫入 raw_transactions (具備單檔容錯隔離 Fault Isolation)
    回傳: Stage1Result(success=bool, df=Optional[pd.DataFrame])
    """
    logger.info(f"🚀 [Extraction Pipeline] 啟動原始資料提取與逐檔入庫... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")

    # 1. 確保 raw_transactions 表結構與 v_raw_transactions 視圖存在
    try:
        ViewsManager.ensure_raw_schema(db_backend=db_backend, db_path=db_path)
    except Exception as schema_err:
        logger.error(f"❌ [Stage 1 Bronze] 初始化 raw_transactions 表結構失敗: {schema_err}", exc_info=True)
        return Stage1Result(success=False, df=None)

    # 2. 準備 DB Loader 與 FileRegistryManager
    loader = get_db_loader(db_backend=db_backend, db_path=db_path)
    registry_mgr = FileRegistryManager(db_path=db_path) if FileRegistryManager else None

    success_files = 0
    skipped_files = 0
    failed_files = 0
    all_clean_dfs: List[pd.DataFrame] = []

    # 3. 逐檔串流提取與入庫 (Per-File Processing)
    for item in extract_raw_data_stream(force=force, input_dir=input_dir, registry_mgr=registry_mgr):
        filename = item.get('filename', 'unknown')
        file_hash = item.get('file_hash')
        file_size = item.get('file_size', 0)
        bank_id = item.get('bank_id')
        status = item.get('status')
        file_df = item.get('df')

        # (1) 已存在且略過
        if status == 'SKIPPED':
            skipped_files += 1
            continue

        # (2) 解析層失敗 (單檔隔離，記錄失敗但不中斷整體管線)
        if status == 'FAILED':
            failed_files += 1
            if registry_mgr and file_hash:
                registry_mgr.register_file(
                    file_hash=file_hash,
                    filename=filename,
                    file_size=file_size,
                    bank_id=bank_id,
                    record_count=0,
                    status='FAILED'
                )
            continue

        # (3) 解析成功但為空表
        if file_df is None or file_df.empty:
            success_files += 1
            if registry_mgr and file_hash:
                registry_mgr.register_file(
                    file_hash=file_hash,
                    filename=filename,
                    file_size=file_size,
                    bank_id=bank_id,
                    record_count=0,
                    status='SUCCESS'
                )
            continue

        # (4) 進行 Pydantic V2 嚴格型態驗證與資料庫寫入
        try:
            raw_schemas, clean_file_df = validate_raw_dataframe(file_df)
            if clean_file_df is None or clean_file_df.empty:
                logger.warning(f"⚠️ [Stage 1 Bronze] 檔案 {filename} 驗證後無有效資料可入庫。")
                continue

            # 冪等性防護 (Idempotent DB Load)：若為 SQLite，排除已存在於 raw_transactions 的主鍵
            target_to_insert: pd.DataFrame = clean_file_df
            effective_backend = getattr(loader, 'backend', None) or db_backend or 'sqlite'
            if effective_backend == 'sqlite' and DBReader is not None:
                try:
                    existing_ids_df = DBReader.read_sql("SELECT transaction_id FROM raw_transactions", db_path=db_path)
                    if existing_ids_df is not None and not existing_ids_df.empty and 'transaction_id' in existing_ids_df.columns:
                        existing_ids_set = set(existing_ids_df['transaction_id'].astype(str))
                        new_mask = ~clean_file_df['transaction_id'].astype(str).isin(list(existing_ids_set))
                        target_to_insert = cast(pd.DataFrame, clean_file_df[new_mask])
                except Exception as check_e:
                    logger.debug(f"查詢既有 transaction_id 略過: {check_e}")
                    target_to_insert = clean_file_df

            # 寫入資料庫
            if not target_to_insert.empty:
                loader.load(target_to_insert, table_name='raw_transactions', mode='append')
                logger.info(f"💾 [Stage 1 Bronze] 檔案 {filename} 已成功入庫 {len(target_to_insert)} 筆資料至 raw_transactions")
            else:
                logger.info(f"ℹ️ [Stage 1 Bronze] 檔案 {filename} 中所有交易皆已存在於 raw_transactions，略過重複寫入。")

            # 登記檔案註冊表 SUCCESS
            if registry_mgr and file_hash:
                registry_mgr.register_file(
                    file_hash=file_hash,
                    filename=filename,
                    file_size=file_size,
                    bank_id=bank_id,
                    record_count=len(clean_file_df),
                    status='SUCCESS'
                )

            all_clean_dfs.append(clean_file_df)
            success_files += 1

        except Exception as file_e:
            failed_files += 1
            logger.warning(f"⚠️ [Stage 1 Bronze] 檔案 {filename} 處理或入庫失敗 (已隔離): {file_e}")
            save_anomaly_report(file_df, f"failed_raw_{filename}.csv", f"檔案 {filename} 入庫失敗診斷備份")
            if registry_mgr and file_hash:
                registry_mgr.register_file(
                    file_hash=file_hash,
                    filename=filename,
                    file_size=file_size,
                    bank_id=bank_id,
                    record_count=0,
                    status='FAILED'
                )

    # 4. 統計與回傳
    logger.info(f"📊 [Stage 1 逐檔處理統計] 成功: {success_files} 個, 略過: {skipped_files} 個, 失敗: {failed_files} 個")
    
    if failed_files > 0 and success_files == 0 and skipped_files == 0:
        logger.error("❌ [Stage 1 Bronze] 所有帳單檔案均處理失敗。")
        return Stage1Result(success=False, df=None)

    total_clean_df = pd.concat(all_clean_dfs, ignore_index=True) if all_clean_dfs else None
    return Stage1Result(success=True, df=total_clean_df)


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
    完整雙階式 ETL Pipeline (Extraction + Refinement 組合進入點):
    1. run_extraction_pipeline: 逐檔串流掃描、解析並安全隔離入庫至 raw_transactions
    2. run_stage2_pipeline: 將 Stage 1 驗證產物直接在記憶體傳遞給 Stage 2 (若無則自 DB 讀取全量)
    """
    logger.info(f"🚀 ETL 流程啟動 (獨立模組執行)... {'(強制全量重新解析)' if force else '(啟用檔案去重檢查)'}")
    
    try:
        # 段落一: Stage 1 Pipeline (Extract + Ingestion)
        s1_res = run_extraction_pipeline(force=force, input_dir=input_dir, db_backend=db_backend)
        if not s1_res:
            logger.error("❌ Stage 1 流程執行失敗，終止後續管線。")
            return False

        # 段落二: Stage 2 Pipeline (直接傳遞記憶體中之 Stage 1 成果，若為 None 則自 DB 讀取全量)
        s2_success = run_stage2_pipeline(raw_df=s1_res.df, db_backend=db_backend, force=force)
        return s2_success
        
    except Exception as e:
        logger.error(f"🚨 ETL 流程發生未預期嚴重錯誤: {e}", exc_info=True)
        return False


__all__ = ["run_etl_pipeline", "run_extraction_pipeline", "run_stage2_pipeline", "refine_transactions", "Stage1Result"]

