# etl/processors/transaction_classifier.py
import pandas as pd
import logging
from typing import Optional
import const
from etl.utils import save_anomaly_report

logger = logging.getLogger(__name__)


class TransactionClassifier:
    """
    [交易分類器]
    負責根據傳入的配置規則，對交易進行分類。
    """
    def __init__(self, config_dir: str, config: Optional[dict] = None):
        """
        :param config: 由外部注入的配置字典 (來自 transaction_types.yaml)
        """
        self.config = config if config is not None else {}

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df

        if const.COL_LOCATION not in df.columns:
            df[const.COL_LOCATION] = 'TW'

        if const.COL_TXN_TYPE not in df.columns:
            df[const.COL_TXN_TYPE] = ''
        
        # 確保 NaN 被轉為空字串，以利後續判斷
        df[const.COL_TXN_TYPE] = df[const.COL_TXN_TYPE].fillna('')

        # 依序執行分類標記 (一旦標記，後續步驟就不會覆蓋)
        df = self._mark_payment(df)
        df = self._mark_credits(df)   
        df = self._mark_fees(df)
        df = self._mark_refunds(df)   
        df = self._mark_foreign(df)
        df = self._mark_general(df)
        df = self._check_uncategorized(df)

        return df

    def _get_mask_empty_type(self, df):
        """輔助函式：找出 Transaction_Type 尚未被標記的行"""
        return df[const.COL_TXN_TYPE] == ''

    def _mark_payment(self, df: pd.DataFrame) -> pd.DataFrame:
        """1. 標記繳款/轉帳 (來自 payment_keywords)"""
        keywords = self.config.get('payment_keywords', [])
        if not keywords: return df
        
        pattern = '|'.join(keywords)
        mask_empty = self._get_mask_empty_type(df)
        mask_keyword = df[const.COL_MERCHANT].astype(str).str.contains(pattern, case=False, regex=True, na=False)
        
        target_mask = mask_empty & mask_keyword
        if target_mask.any():
            df.loc[target_mask, const.COL_TXN_TYPE] = const.TransactionType.PAYMENT.label

            # --- 資料整理: 繳款 ---
            # 1. 淨空卡片資訊
            df.loc[target_mask, [const.COL_CARD_TYPE, const.COL_CARD_NO]] = None
            
            # 2. 消費地標準化
            df.loc[target_mask, const.COL_LOCATION] = 'TW'
            
            # 3. 幣別與金額整理
            # currency_type 複製到 payment_currency
            df.loc[target_mask, const.COL_PAY_CURR] = df.loc[target_mask, const.COL_CURRENCY]
            
            # payment_amount 若無值則從 currency_amount 複製
            pay_amt_missing = target_mask & (df[const.COL_PAY_AMOUNT].isna() | (df[const.COL_PAY_AMOUNT] == ''))
            df.loc[pay_amt_missing, const.COL_PAY_AMOUNT] = df.loc[pay_amt_missing, const.COL_CURR_AMOUNT]
                
        return df

    def _mark_credits(self, df: pd.DataFrame) -> pd.DataFrame:
        """2. 標記紅利與折抵 (來自 credit_keywords)"""
        keywords = self.config.get('credit_keywords', [])
        if not keywords: return df
        
        pattern = '|'.join(keywords)
        mask_empty = self._get_mask_empty_type(df)
        mask_keyword = df[const.COL_MERCHANT].astype(str).str.contains(pattern, case=False, regex=True, na=False)
        
        target_mask = mask_empty & mask_keyword
        if target_mask.any():
            df.loc[target_mask, const.COL_TXN_TYPE] = const.TransactionType.REDEMPTION.label
            
            # --- 資料整理: 紅利折抵 ---
            # 1. 消費地標準化
            df.loc[target_mask, const.COL_LOCATION] = 'TW'
            
            # 2. 幣別整理: 優先互補，最後才補 TWD
            # 2-1. 若 Payment_Currency 為空，嘗試從 Currency_Type 複製
            pay_curr_empty = target_mask & (df[const.COL_PAY_CURR].isna() | (df[const.COL_PAY_CURR] == ''))
            df.loc[pay_curr_empty, const.COL_PAY_CURR] = df.loc[pay_curr_empty, const.COL_CURRENCY]
            
            # 3. 金額整理: Payment_Amount 若無值則從 Currency_Amount 複製
            pay_amt_empty = target_mask & (df[const.COL_PAY_AMOUNT].isna() | (df[const.COL_PAY_AMOUNT] == ''))
            df.loc[pay_amt_empty, const.COL_PAY_AMOUNT] = df.loc[pay_amt_empty, const.COL_CURR_AMOUNT]            
            
        return df

    def _mark_fees(self, df: pd.DataFrame) -> pd.DataFrame:
        """3. 標記各項費用 (來自 fee_keywords)"""
        keywords = self.config.get('fee_keywords', [])
        if not keywords: return df
        
        pattern = '|'.join(keywords)
        mask_empty = self._get_mask_empty_type(df)
        mask_keyword = df[const.COL_MERCHANT].astype(str).str.contains(pattern, case=False, regex=True, na=False)
        
        target_mask = mask_empty & mask_keyword
        if target_mask.any():
            df.loc[target_mask, const.COL_TXN_TYPE] = const.TransactionType.FEE.label
            
            # --- 資料整理: 各項費用 ---
            # 1. 消費地標準化
            df.loc[target_mask, const.COL_LOCATION] = 'TW'
            
            # 2. 幣別整理: 優先互補，最後才補 TWD
            pay_curr_empty = target_mask & (df[const.COL_PAY_CURR].isna() | (df[const.COL_PAY_CURR] == ''))
            df.loc[pay_curr_empty, const.COL_PAY_CURR] = df.loc[pay_curr_empty, const.COL_CURRENCY]
            
            df.loc[target_mask, const.COL_CURRENCY] = df.loc[target_mask, const.COL_PAY_CURR]
            
            # 3. 金額整理: 優先互補
            pay_amt_empty = target_mask & (df[const.COL_PAY_AMOUNT].isna() | (df[const.COL_PAY_AMOUNT] == ''))
            df.loc[pay_amt_empty, const.COL_PAY_AMOUNT] = df.loc[pay_amt_empty, const.COL_CURR_AMOUNT]
            
        return df

    def _mark_refunds(self, df: pd.DataFrame) -> pd.DataFrame:
        """4. 標記退刷 (金額小於 0)"""
        mask_empty = self._get_mask_empty_type(df)
        
        if const.COL_PAY_AMOUNT in df.columns:
            amount_col = const.COL_PAY_AMOUNT
        elif const.COL_CURR_AMOUNT in df.columns:
            amount_col = const.COL_CURR_AMOUNT
        else:
            return df

        numeric_amounts = pd.to_numeric(df[amount_col], errors='coerce')
        mask_negative = numeric_amounts < 0
        
        target_mask = mask_empty & mask_negative
        if target_mask.any():
            df.loc[target_mask, const.COL_TXN_TYPE] = const.TransactionType.REFUND.label
            
        return df

    def _mark_foreign(self, df: pd.DataFrame) -> pd.DataFrame:
        """5. 標記國外交易"""
        mask_empty = self._get_mask_empty_type(df)
        is_foreign_loc = (df[const.COL_LOCATION].fillna('TW') != 'TW')
        target_indices = df[mask_empty & is_foreign_loc].index
        
        if len(target_indices) > 0:
            if const.COL_CURRENCY in df.columns and const.COL_PAY_CURR in df.columns:
                mask_diff = df.loc[target_indices, const.COL_CURRENCY] != df.loc[target_indices, const.COL_PAY_CURR]
                df.loc[target_indices[mask_diff], const.COL_TXN_TYPE] = const.TransactionType.FOREIGN.label
                
                same_indices = target_indices[~mask_diff]
                if len(same_indices) > 0:
                    mask_twd = df.loc[same_indices, const.COL_CURRENCY] == 'TWD'
                    twd_indices = same_indices[mask_twd]
                    df.loc[twd_indices, const.COL_TXN_TYPE] = const.TransactionType.FOREIGN_TWD.label
                    
                    mask_foreign_curr = ~mask_twd
                    df.loc[same_indices[mask_foreign_curr], const.COL_TXN_TYPE] = const.TransactionType.FOREIGN_DUAL.label

        return df

    def _mark_general(self, df: pd.DataFrame) -> pd.DataFrame:
        """6. 剩下的標記為一般交易"""
        mask_empty = self._get_mask_empty_type(df)
        
        if mask_empty.any():
            df.loc[mask_empty, const.COL_TXN_TYPE] = const.TransactionType.GENERAL.label
            
        return df

    def _check_uncategorized(self, df: pd.DataFrame) -> pd.DataFrame:
        """檢查未分類交易並輸出異常報告"""
        if 'transaction_type' in df.columns:
            anomalies = df[df['transaction_type'].isin(['未分類', 'Unknown', '', None])]
            if not isinstance(anomalies, pd.DataFrame):
                anomalies = pd.DataFrame(anomalies)
            if not anomalies.empty:
                save_anomaly_report(anomalies, 'anomaly_uncategorized.csv', f"發現 {len(anomalies)} 筆未分類交易")
        return df
