import pandas as pd
import hashlib
import logging
import os
import const

logger = logging.getLogger(__name__)

class BillsToDB:
    """
    [資料處理層 - 準備寫入]
    負責在資料寫入資料庫前的最後加工：
    1. 生成唯一 Transaction ID (MD5 Hash)
    2. 移除重複交易 (Deduplication)
    3. 欄位名稱映射 (CamelCase -> snake_case)
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def all_transactions_col_mapping(self):
        TC = const.TransactionColumn
        return TC.get_mapping(
            TC.TXN_DATE, TC.POST_DATE, TC.CONV_DATE, TC.STAT_MON,
            TC.BANK_NAME, TC.CARD_TYPE, TC.CARD_NO, TC.MERCHANT, TC.LOCATION, 
            TC.TXN_TYPE, TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.VPC_NO, TC.VPC_TYPE,
            TC.CURRENCY, TC.CURR_AMOUNT, TC.PAY_CURR, TC.PAY_AMOUNT
        )    
    
    def _generate_transaction_id(self, row: pd.Series) -> str:
        """
        建立唯一的交易 ID (Hash)
        組合：日期 + 商家 + 金額 + 卡號 + 交易類型 + 同日流水號
        """
        def safe_str(val):
            return str(val).strip() if pd.notna(val) else ""

        unique_str = (
            safe_str(row.get(const.COL_TXN_DATE)) +
            safe_str(row.get(const.COL_MERCHANT)) +
            safe_str(row.get(const.COL_CARD_NO)) +
            safe_str(row.get(const.COL_PAY_AMOUNT)) + 
            safe_str(row.get(const.COL_TXN_TYPE)) +
            safe_str(row.get('_seq'))
        )
        return hashlib.md5(unique_str.encode('utf-8')).hexdigest()

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        執行寫入前的預處理邏輯，包含 ID 生成、去重與欄位映射。
        """
        if df.empty:
            logger.warning("⚠️ 沒有資料可供準備。")
            return df

        df_db = df.copy()

        # 1. 生成流水號與 Transaction ID
        group_cols = [
            const.COL_TXN_DATE, 
            const.COL_MERCHANT, 
            const.COL_CARD_NO, 
            const.COL_PAY_AMOUNT, 
            const.COL_TXN_TYPE
        ]
        
        # 確保分組欄位存在於 DF 中
        for col in group_cols:
            if col not in df_db.columns:
                df_db[col] = None

        # cumcount 會從 0 開始編號：第一杯咖啡是 0, 第二杯是 1...
        df_db['_seq'] = df_db.groupby(group_cols, dropna=False).cumcount().astype(str)
        
        # 生成 Primary Key (transaction_id)
        df_db['transaction_id'] = df_db.apply(self._generate_transaction_id, axis=1)

        # 2. 移除重複的交易 (Deduplication)
        duplicated_mask = df_db.duplicated(subset=['transaction_id'], keep='first')
        
        if duplicated_mask.any():
            df_duplicates = df_db[duplicated_mask].copy()
            logger.info(f"🧹 移除了 {len(df_duplicates)} 筆重複交易紀錄。")
            
            # [觀察用] 將被移除的資料輸出成 CSV
            debug_csv_path = os.path.join(self.output_dir, 'dropped_duplicates.csv')
            df_duplicates.to_csv(debug_csv_path, index=False, encoding='utf-8-sig')
            logger.info(f"🔍 被移除的重複資料已存至: {debug_csv_path}")
            
        # 正式執行移除 (只保留第一筆)
        df_db = df_db[~duplicated_mask]
        # [移除暫存欄位]
        df_db = df_db.drop(columns=['_seq'])

        # 3. 欄位映射與篩選 (Mapping to Snake Case)
        rename_map = self.all_transactions_col_mapping()
        available_cols = [c for c in rename_map.keys() if c in df_db.columns]
        
        # 建立最終要寫入的 DataFrame
        df_final = df_db[available_cols].rename(columns=rename_map)
        df_final['transaction_id'] = df_db['transaction_id']

        return df_final
