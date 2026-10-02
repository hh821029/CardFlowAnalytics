# etl/schemas/DBColMapper.py
"""
資料庫欄位映射器與標準資料表欄位定義 (DB Column Mapper & Standard Columns Schema)
以 const.TransactionColumn 為單一真相來源 (SSOT)
"""
import logging
import pandas as pd
from typing import List, Dict, Optional
import const

logger = logging.getLogger(__name__)

TC = const.TransactionColumn


class StandardColumns:
    """
    定義各階段與目標資料表之標準欄位清單 (Standard Columns Schema)
    以 const.TransactionColumn 為單一真相來源 (SSOT)
    """
    TC = const.TransactionColumn

    # 1. 核心交易事實表 (all_transactions) - 遵循 3NF 正規化，以 bank_no 與 card_id 為外鍵
    ALL_TRANSACTIONS_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.POST_DATE, TC.CONV_DATE, TC.STAT_MON,
        TC.BANK_NO, TC.CARD_ID, TC.CARD_NO, TC.MERCHANT, TC.LOCATION, 
        TC.TXN_TYPE, TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.VPC_TYPE,
        TC.CURRENCY, TC.CURR_AMOUNT, TC.PAY_CURR, TC.PAY_AMOUNT
    ]

    ALL_TRANSACTIONS: List[str] = [m.col_name for m in ALL_TRANSACTIONS_MEMBERS]

    # 2. RFM 分析專用表 / 視圖 (rfm_transactions)
    RFM_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.BANK_NO, TC.BANK_NAME, TC.CARD_ID, TC.CARD_TYPE,
        TC.MERCHANT, TC.LOCATION, TC.MERCHANT_DISPLAY, TC.VPC_TYPE, 
        TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.NORMALIZED_MERCHANT,
        TC.PAY_CURR, TC.PAY_AMOUNT, TC.TXN_TYPE,
        TC.EC_CATEGORY, TC.EC_SUB_CATEGORY, TC.CATEGORY, TC.SUB_CATEGORY
    ]
    RFM_TRANSACTIONS: List[str] = [m.col_name for m in RFM_MEMBERS]

    # 3. 回饋計算專用事實表 / 視圖 (rewards_transactions)
    REWARDS_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.POST_DATE, TC.STAT_MON, TC.BANK_NO, TC.BANK_NAME,
        TC.CARD_ID, TC.CARD_TYPE, TC.CARD_NO, TC.VPC_NO, TC.VPC_TYPE,
        TC.MERCHANT, TC.MERCHANT_DISPLAY, TC.LOCATION,
        TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.NORMALIZED_MERCHANT,
        TC.CURRENCY, TC.CURR_AMOUNT, TC.PAY_CURR, TC.PAY_AMOUNT, TC.TXN_TYPE
    ]
    REWARDS_TRANSACTIONS: List[str] = [m.col_name for m in REWARDS_MEMBERS]

    # 4. 商家維度事實表 (fact_transaction_merchants)
    MERCHANT_FACT_MEMBERS = [
        TC.TXN_ID, TC.NORMALIZED_MERCHANT, TC.PAYMENT_PROCESS, TC.EC_PLATFORM,
        TC.MERCHANT_DISPLAY, TC.CATEGORY, TC.SUB_CATEGORY
    ]
    MERCHANT_FACT_TRANSACTIONS: List[str] = [m.col_name for m in MERCHANT_FACT_MEMBERS]

    # 5. 全量/最大欄位聯集 (MAX / Refined Superset)
    MAX_TRANSACTIONS: List[str] = list(dict.fromkeys(
        ALL_TRANSACTIONS + RFM_TRANSACTIONS + REWARDS_TRANSACTIONS + MERCHANT_FACT_TRANSACTIONS
    ))

    # 6. 用於計算同日流水號 _seq 與生成 transaction_id 的基準欄位
    ID_GROUP_COLUMNS: List[str] = [
        TC.TXN_DATE.col_name,
        TC.MERCHANT.col_name,
        TC.CARD_NO.col_name,
        TC.PAY_AMOUNT.col_name,
        TC.TXN_TYPE.col_name
    ]


# 向下相容別名
STANDARD_COLUMNS: List[str] = StandardColumns.ALL_TRANSACTIONS


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
        mapped = self._apply_mapping(df, self.all_txn_mapping)
        # 確保 3NF 所有定義的 SQL 欄位皆存在於 DataFrame (缺者補 None)，保證資料表 Schema 完整並防止 View 崩潰
        for sql_col in self.all_txn_mapping.values():
            if sql_col not in mapped.columns:
                mapped[sql_col] = None
        return mapped

    def map_rfm_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出 RFM 分析資料表 DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.rfm_mapping)

    def map_rewards_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出回饋計算資料表 DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.rewards_mapping)

    def map_merchant_facts(self, df: pd.DataFrame) -> pd.DataFrame:
        """產出商家維度事實資料表 (fact_transaction_merchants) DataFrame (以 transaction_id 為外鍵)"""
        return self._apply_mapping(df, self.merchant_fact_mapping)


__all__ = ['StandardColumns', 'STANDARD_COLUMNS', 'DBColMapper']
