# etl/loading.py
"""
ETL 模組 - Load (資料庫與檔案寫入、鍵值生成、資料表映射與視圖管理)
包含：
1. TransactionIdGenerator: 生成唯一 transaction_id (MD5 Hash) 與重複交易排除
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
except ImportError:
    get_db_loader = None
    SQLiteLoader = None
    SchemaEnforcer = None


from etl.utils import save_anomaly_report,STANDARD_COLUMNS,StandardColumns

logger = logging.getLogger(__name__)

OUTPUT_DIR = const.OUTPUT_DIR
TC = const.TransactionColumn


# ==========================================
# 1. 唯一鍵值生成與去重器 (Key Generator & Deduplicator)
# ==========================================
class TransactionIdGenerator:
    """
    負責在資料寫入資料庫前生成全域唯一的主鍵 (transaction_id)，並執行去重。
    """
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or const.OUTPUT_DIR
        self.group_cols = StandardColumns.ID_GROUP_COLUMNS

    def _generate_transaction_id(self, row: pd.Series) -> str:
        """
        動態串接 group_cols 欄位值 + 同日流水號 _seq 生成 MD5
        """
        def safe_str(val):
            return str(val).strip() if pd.notna(val) else ""
        # 動態取得所有分組欄位的值，最後再加上 _seq
        components = [safe_str(row.get(col)) for col in self.group_cols]
        components.append(safe_str(row.get('_seq')))
        
        unique_str = "".join(components)
        return hashlib.md5(unique_str.encode('utf-8')).hexdigest()

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


# ==========================================
# 2. 資料庫欄位映射器 (DB Column Mapper)
# ==========================================
class DBColMapper:
    """
    依據 TransactionColumn 定義將 DataFrame 轉換為特定目標資料表的欄位格式。
    所有衍生資料表均以 transaction_id 作為 Primary Key / Foreign Key。
    """
    def __init__(self):
        self.TC = const.TransactionColumn

        # 1. 核心交易事實表對照字典 (all_transactions)
        self.all_txn_mapping = self.TC.get_mapping(*StandardColumns.ALL_TRANSACTIONS_MEMBERS)

        # 2. RFM 分析專用資料表對照字典
        self.rfm_mapping = self.TC.get_mapping(*StandardColumns.RFM_MEMBERS)

        # 3. 回饋計算專用事實資料表對照字典
        self.rewards_mapping = self.TC.get_mapping(*StandardColumns.REWARDS_MEMBERS)

        # 4. 商家維度事實表對照字典 (fact_transaction_merchants)
        self.merchant_fact_mapping = self.TC.get_mapping(*StandardColumns.MERCHANT_FACT_MEMBERS)

    def _apply_mapping(self, df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
        """
        安全執行 DataFrame 欄位篩選、更名與複製 (防止 SettingWithCopyWarning 與型別推導報錯)
        """
        if df is None or df.empty:
            return pd.DataFrame()
        
        valid_cols = [col for col in mapping.keys() if col in df.columns]
        df_subset = pd.DataFrame(df[valid_cols])
        mapped_df = df_subset.rename(columns=mapping).copy()

        # 確保 transaction_id 存在
        if 'transaction_id' in df.columns and 'transaction_id' not in mapped_df.columns:
            mapped_df['transaction_id'] = df['transaction_id'].values

        return mapped_df

    def map_all_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出準備寫入 all_transactions 資料表的 DataFrame"""
        return self._apply_mapping(df, self.all_txn_mapping)

    def map_rfm_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出 RFM 分析資料表 DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.rfm_mapping)

    def map_rewards_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出回饋計算資料表 DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.rewards_mapping)

    def map_merchant_facts(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出商家維度事實資料表 (fact_transaction_merchants) DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.merchant_fact_mapping)

# ==========================================
# 3. Load 階段核心執行進入點 (load_data)
# ==========================================
def load_data(
    final_df: pd.DataFrame, 
    force: bool = True, 
    db_backend: Optional[str] = None,
    output_dir: Optional[str] = None
) -> bool:
    """
    執行 Load 階段完整流程：
    1. STEP 3: 標準 16 欄位收斂、SchemaEnforcer 型態執法、日期排序、輸出 result_final.csv
    2. STEP 4: Transaction ID 生成、去重、DBColMapper 欄位轉換、入庫 (PostgreSQL/SQLite)、視圖建立
    """
    if final_df is None or final_df.empty:
        logger.warning("⚠️ 無有效資料可執行 Load 階段。")
        return True

    target_output_dir = output_dir or OUTPUT_DIR
    os.makedirs(target_output_dir, exist_ok=True)

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
            logger.info("📦 準備載入資料庫...")
            
            # 1. 唯一鍵值生成與去重
            id_gen = TransactionIdGenerator(output_dir=target_output_dir)
            df_with_id = id_gen.generate_and_deduplicate(df_enforce_target)

            # 2. 取得 DB Loader
            if get_db_loader is not None:
                loader = get_db_loader(db_backend=db_backend)
            elif SQLiteLoader is not None:
                loader = SQLiteLoader(db_path=const.DB_PATH)
            else:
                raise ImportError("無法取得任何有效的 DB Loader")

            # 3. 映射資料庫欄位後寫入資料庫
            col_mapper = DBColMapper()
            db_df = col_mapper.map_all_transactions(df_with_id)
            rfm_df = col_mapper.map_rfm_transactions(df_with_id)
            reward_df = col_mapper.map_rewards_transactions(df_with_id) 

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



        else:
            logger.warning("⚠️ 載入器缺失，略過資料庫寫入。")

        return True

    except Exception as e:
        logger.error(f"🚨 Load 階段發生錯誤: {e}")
        save_anomaly_report(final_df, 'crash_dump_load.csv', "Load 階段崩潰，已備份資料")
        return False
