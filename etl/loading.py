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
# 3. 匯率載入器與台幣本位幣轉換器 (FX Normalizer)
# ==========================================
def _standardize_fx_df(df: pd.DataFrame) -> pd.DataFrame:
    """標準化匯率表欄位名稱與型態"""
    if df is None or df.empty:
        return pd.DataFrame()
    df_clean = df.copy()
    
    # 匯率欄位相容 exchange_rate / fx_rate
    if 'exchange_rate' in df_clean.columns:
        if 'fx_rate' not in df_clean.columns:
            df_clean['fx_rate'] = df_clean['exchange_rate']
        else:
            df_clean['fx_rate'] = df_clean['fx_rate'].combine_first(df_clean['exchange_rate'])
        
    # 日期與幣別處理
    if 'conversion_date' in df_clean.columns:
        df_clean['conversion_date'] = df_clean['conversion_date'].astype(str).str.strip().str.split(' ').str[0]
    if 'currency_type' in df_clean.columns:
        df_clean['currency_type'] = df_clean['currency_type'].astype(str).str.strip().str.upper()
    if 'fx_rate' in df_clean.columns:
        df_clean['fx_rate'] = pd.to_numeric(df_clean['fx_rate'], errors='coerce')
        
    return df_clean.dropna(subset=['conversion_date', 'currency_type', 'fx_rate'])


def load_fx_table(config_dir: Optional[str] = None) -> pd.DataFrame:
    """
    雙軌載入匯率對照表：
    1. 優先從資料庫 (dim_fx_table) 讀取
    2. 備援從 profiles/.../configs/dim_fx_table.csv 讀取
    """
    # 1. 嘗試從 DB 讀取
    try:
        from database.loaders.db_reader import DBReader
        db_df = DBReader.read_sql("SELECT * FROM dim_fx_table")
        if db_df is not None and not db_df.empty:
            logger.debug("✅ 成功從資料庫 (dim_fx_table) 載入匯率資料")
            return _standardize_fx_df(db_df)
    except Exception as e:
        logger.debug(f"ℹ️ 從資料庫讀取 dim_fx_table 略過: {e}")

    # 2. 備援從 ConfigLoader 讀取 CSV
    try:
        from profiles.loaders.config_loader import ConfigLoader
        target_dir = config_dir or const.CONFIG_DIR
        csv_df = ConfigLoader.load_config(target_dir, "dim_fx_table", strategy='replace')
        if csv_df is not None and not csv_df.empty:
            logger.debug("✅ 成功從 ConfigLoader 載入 dim_fx_table.csv")
            return _standardize_fx_df(csv_df)
    except Exception as e:
        logger.warning(f"⚠️ 從 CSV 載入 dim_fx_table 失敗: {e}")

    return pd.DataFrame()


def normalize_to_twd(
    df: pd.DataFrame, 
    fx_df: Optional[pd.DataFrame] = None, 
    output_dir: Optional[str] = None
) -> pd.DataFrame:
    """
    將非 TWD 的雙幣交易依結匯日 (conversion_date) 匯率折算為台幣 (TWD)，供 RFM 與 Rewards 分析使用。
    嚴格業務規則：僅在 conversion_date 存在且 payment_currency != 'TWD' 時觸發折算。
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    df_result = df.copy()

    # 確保必要欄位存在
    if 'payment_currency' not in df_result.columns or 'payment_amount' not in df_result.columns:
        return df_result

    # 1. 判斷需要折算的條件：conversion_date 存在 且 payment_currency 非 TWD / 空值
    has_conv_date = (
        df_result['conversion_date'].notna() & 
        (df_result['conversion_date'].astype(str).str.strip() != '') & 
        (df_result['conversion_date'].astype(str).str.lower() != 'nan') &
        (df_result['conversion_date'].astype(str).str.lower() != 'none')
    )
    is_foreign_curr = (
        df_result['payment_currency'].notna() & 
        (df_result['payment_currency'].astype(str).str.strip().str.upper() != 'TWD') & 
        (df_result['payment_currency'].astype(str).str.strip() != '') &
        (df_result['payment_currency'].astype(str).str.lower() != 'nan')
    )
    
    mask_to_convert = has_conv_date & is_foreign_curr

    if not mask_to_convert.any():
        return df_result

    count_to_convert = mask_to_convert.sum()
    logger.info(f"💱 偵測到 {count_to_convert} 筆雙幣外幣交易 (具備 conversion_date 且非 TWD)，準備進行台幣折算...")

    if fx_df is None or fx_df.empty:
        fx_df = load_fx_table()

    # 建立匯率查找映射字典: (conversion_date, currency_type) -> fx_rate
    fx_map = {}
    if fx_df is not None and not fx_df.empty and 'conversion_date' in fx_df.columns and 'currency_type' in fx_df.columns and 'fx_rate' in fx_df.columns:
        for _, row in fx_df.iterrows():
            c_date = str(row['conversion_date']).strip().split(' ')[0]
            curr = str(row['currency_type']).strip().upper()
            try:
                rate = float(row['fx_rate'])
                fx_map[(c_date, curr)] = rate
            except (ValueError, TypeError):
                continue

    missing_fx_rows = []
    
    for idx in df_result[mask_to_convert].index:
        conv_date = str(df_result.at[idx, 'conversion_date']).strip().split(' ')[0]
        pay_curr = str(df_result.at[idx, 'payment_currency']).strip().upper()
        raw_amt = df_result.at[idx, 'payment_amount']

        key = (conv_date, pay_curr)
        # 如果 payment_currency 找不到，也可嘗試 currency_type (若有)
        if key not in fx_map and 'currency_type' in df_result.columns:
            curr_type = str(df_result.at[idx, 'currency_type']).strip().upper()
            key = (conv_date, curr_type)

        if key in fx_map:
            fx_rate = fx_map[key]
            try:
                amt_val = float(raw_amt)
                converted_amt = round(amt_val * fx_rate)  # 四捨五入至整數台幣
                df_result.at[idx, 'payment_amount'] = converted_amt
                df_result.at[idx, 'payment_currency'] = 'TWD'
                logger.debug(f"💱 [折算成功] 結匯日: {conv_date}, {raw_amt} {pay_curr} * {fx_rate} -> {converted_amt} TWD")
            except (ValueError, TypeError) as conv_err:
                logger.warning(f"⚠️ 金額轉換數值失敗 (row {idx}): {conv_err}")
        else:
            logger.warning(f"⚠️ 查無匯率對照: 結匯日 [{conv_date}], 幣別 [{pay_curr}], 交易: {df_result.at[idx, 'transaction_id'] if 'transaction_id' in df_result.columns else idx}")
            missing_fx_rows.append(df_result.loc[idx])

    if missing_fx_rows:
        df_missing = pd.DataFrame(missing_fx_rows)
        logger.error(f"❌ 共有 {len(missing_fx_rows)} 筆外幣交易查無匯率，請補錄 dim_fx_table！")
        target_out = output_dir or const.OUTPUT_DIR
        if target_out:
            os.makedirs(target_out, exist_ok=True)
            missing_path = os.path.join(target_out, 'missing_fx_rate_anomalies.csv')
            df_missing.to_csv(missing_path, index=False, encoding='utf-8-sig')
            logger.info(f"🔍 查無匯率之異常明細已存至: {missing_path}")

    return df_result


# ==========================================
# 4. 主載入進入點 (Main Loader Pipeline)
# ==========================================
def load_data(
    final_df: pd.DataFrame, 
    force: bool = False, 
    db_backend: Optional[str] = None,
    output_dir: Optional[str] = None
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

        else:
            logger.warning("⚠️ 載入器缺失，略過資料庫寫入。")

        return True

    except Exception as e:
        logger.error(f"🚨 Load 階段發生錯誤: {e}")
        save_anomaly_report(final_df, 'crash_dump_load.csv', "Load 階段崩潰，已備份資料")
        return False

