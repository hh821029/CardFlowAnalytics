# etl/loading.py
"""
ETL 模組 - Load (資料庫與檔案寫入、鍵值生成、資料表映射與視圖管理)
包含：
1. TransactionIdGenerator: 生成唯一 transaction_id (SHA-256 Hash) 與重複交易排除
2. DBColMapper: 依據 TransactionColumn 定義將 DataFrame 映射為不同資料表 (all_transactions, RFM, 回饋計算等)
3. load_data: 執行 STEP 3 (標準欄位收斂、型態執法、排序、輸出 CSV) 與 STEP 4 (入庫與視圖更新)
"""
import os
import hashlib
import logging
from typing import Optional, Dict, Any, List
import pandas as pd

import const

try:
    from database.loaders.db_factory import get_db_loader
    from database.loaders.sqlite_loader import SQLiteLoader
    from database.loaders.schema_enforcer import SchemaEnforcer
    from database.loaders.views_manager import ViewsManager
    from database.loaders.db_config import resolve_db_backend
except ImportError:
    get_db_loader = None
    SQLiteLoader = None
    SchemaEnforcer = None
    ViewsManager = None
    resolve_db_backend = None


from etl.schemas.transaction_id_generator import TransactionIdGenerator
from etl.schemas.db_col_mapper import DBColMapper, StandardColumns, STANDARD_COLUMNS
from etl.schemas.fx_normalizer import normalize_to_twd, load_fx_table, _standardize_fx_df
from etl.exceptions import save_anomaly_report

logger = logging.getLogger(__name__)

OUTPUT_DIR = const.OUTPUT_DIR
TC = const.TransactionColumn



# ==========================================
# 4. 主載入進入點 (Main Loader Pipeline)
# ==========================================
def load_data(
    final_df: pd.DataFrame, 
    force: bool = False, 
    db_backend: Optional[str] = None,
    output_dir: Optional[str] = None,
    db_path: Optional[str] = None
) -> bool:
    """
    執行 ETL 最終寫入 (STEP 3 & STEP 4)：
    1. Schema 強制型態與排序
    2. 生成 transaction_id 與重複排除
    3. 寫入 all_transactions (原始事實表)
    4. 進行雙幣交易匯率折算 (normalize_to_twd) 並寫入 rfm_transactions 與 rewards_transactions
    """
    if final_df is None or final_df.empty:
        logger.warning("⚠️ 無有效資料可執行 Load 階段。")
        return True

    target_output_dir = output_dir or OUTPUT_DIR
    os.makedirs(target_output_dir, exist_ok=True)
    effective_backend = resolve_db_backend(db_backend) if resolve_db_backend else (db_backend or 'sqlite').lower()

    try:
        # --- STEP 3: Filter & Sort (最終整理) ---
        available_cols = [c for c in StandardColumns.MAX_TRANSACTIONS if c in final_df.columns]
        sliced_df = final_df[available_cols].copy()
        df_enforce_target = pd.DataFrame(sliced_df)

        if SchemaEnforcer:
            df_enforce_target = SchemaEnforcer.enforce(df_enforce_target)

        if const.COL_TXN_DATE in df_enforce_target.columns:
            try:
                df_enforce_target = df_enforce_target.sort_values(by=const.COL_TXN_DATE)
            except Exception as e:
                logger.error(f"❌ 排序失敗: {e}")

        # 輸出最終 CSV
        csv_output_path = os.path.join(target_output_dir, 'result_final.csv')
        df_enforce_target.to_csv(csv_output_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 清洗完成，已輸出至 {csv_output_path}")

        # --- STEP 4: Load & 寫入資料庫 ---
        if get_db_loader is not None or SQLiteLoader is not None:
            logger.info(f"📦 準備載入資料庫 (目標後端: {effective_backend})...")
            
            # 1. 唯一鍵值生成與去重
            id_gen = TransactionIdGenerator(output_dir=target_output_dir)
            df_with_id = id_gen.generate_and_deduplicate(df_enforce_target)

            # 2. 取得 DB Loader
            if get_db_loader is not None:
                loader = get_db_loader(db_backend=effective_backend, db_path=db_path)
            elif SQLiteLoader is not None:
                loader = SQLiteLoader(db_path=db_path or const.DB_PATH)
            else:
                raise ImportError("無法取得任何有效的 DB Loader")

            # 3. 映射資料庫欄位
            col_mapper = DBColMapper()

            # (1) 原始帳單事實表 (保持原始 JPY/USD 與金額 SSOT)
            db_df = col_mapper.map_all_transactions(df_with_id)

            # (2) 進行本位幣 (TWD) 匯率折算 (僅針對 conversion_date 存在且 payment_currency != 'TWD' 的雙幣外幣交易)
            fx_df = load_fx_table()
            df_twd = normalize_to_twd(df_with_id, fx_df=fx_df, output_dir=target_output_dir)

            # (3) RFM 與 Rewards 表採用折算後台幣金額
            rfm_df = col_mapper.map_rfm_transactions(df_twd)
            reward_df = col_mapper.map_rewards_transactions(df_twd) 

            db_mode = 'replace' if force else 'append'
            common_indices = ['transaction_date', 'merchant_name', 'card_no', 'transaction_id']
            tables_to_load = [
                (db_df, 'all_transactions', common_indices),
                (rfm_df, 'rfm_transactions', common_indices),
                (reward_df, 'rewards_transactions', common_indices)
            ]

            for target_df, tbl_name, indices in tables_to_load:
                if target_df is None or target_df.empty:
                    logger.warning(f"⚠️ {tbl_name} 無有效資料，略過寫入。")
                    continue
                try:
                    logger.info(f"📦 開始寫入 {tbl_name} 表 (模式: {db_mode})...")
                    loader.load(target_df, table_name=tbl_name, mode=db_mode, indices=indices)
                    logger.info(f"✅ {tbl_name} 表載入成功 ({len(target_df)} 筆)")
                except Exception as tbl_err:
                    logger.error(f"❌ 寫入資料表 {tbl_name} 時發生錯誤: {tbl_err}")
                    save_anomaly_report(target_df, f"failed_load_{tbl_name}.csv", f"{tbl_name} 入庫失敗")
                    raise tbl_err

            # 4. 建立 3NF 複合索引 (bank_no, card_id) 與 (transaction_date)
            if ViewsManager is not None:
                try:
                    ViewsManager.create_indices(loader=loader, db_path=db_path)
                    ViewsManager.create_or_replace_views(loader=loader, db_path=db_path)
                except Exception as idx_err:
                    logger.warning(f"⚠️ 建立 3NF 複合索引或視圖略過: {idx_err}")

        else:
            logger.warning("⚠️ 載入器缺失，略過資料庫寫入。")

        return True

    except Exception as e:
        logger.error(f"🚨 Load 階段發生錯誤: {e}")
        save_anomaly_report(final_df, 'crash_dump_load.csv', "Load 階段崩潰，已備份資料")
        return False


__all__ = [
    'load_data',
    'TransactionIdGenerator',
    'DBColMapper',
    'StandardColumns',
    'STANDARD_COLUMNS',
    'normalize_to_twd',
    'load_fx_table',
    '_standardize_fx_df'
]


