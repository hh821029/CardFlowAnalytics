# etl/processors/classifier.py
import pandas as pd
import os
import logging
import yaml
import const
from typing import Optional

logger = logging.getLogger(__name__)

class CardClassifier:
    """
    [卡片與支付分類器]
    1. 載入 bridge_user_cards 對照規則，對照 card_no 與 vpc_no 標記 card_type 與 vpc_type。
    2. 交叉洗滌：若 vpc_type 中含有符合 dim_payment_process 的第三方支付類別，自動移至 payment_process 欄位並提供 process_prefix。
    """
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None, gateways: Optional[pd.DataFrame] = None):
        if rules is not None and not rules.empty:
            self.rules = self._preprocess_rules(rules)
            logger.info(f"✅ CardClassifier 已由外部載入 {len(self.rules)} 條持卡規則")
        else:
            try:
                from profiles.loaders.config_loader import ConfigLoader
                df = ConfigLoader.load_config(config_dir, 'bridge_user_cards', strategy='replace')
                if df.empty:
                    df = ConfigLoader.load_config(config_dir, 'dim_cards', strategy='replace')
                self.rules = self._preprocess_rules(df)
                logger.info(f"✅ CardClassifier 透過 ConfigLoader 載入 {len(self.rules)} 條持卡規則")
            except Exception as e:
                logger.warning(f"⚠️ 無法透過 ConfigLoader 載入卡片對照規則: {e}")
                self.rules = pd.DataFrame()

        # 載入第三方支付洗滌規則 (dim_payment_process)
        if gateways is not None and not gateways.empty:
            self.gateways = gateways
        else:
            try:
                from profiles.loaders.config_loader import ConfigLoader
                self.gateways = ConfigLoader.load_config(config_dir, 'dim_payment_process', strategy='append')
            except Exception:
                self.gateways = pd.DataFrame()

    def _preprocess_rules(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        try:
            df.columns = df.columns.astype(str).str.strip()
            for col in df.columns:
                df[col] = df[col].astype(str).str.strip()
                if col in ['card_no', 'vpc_no', '代換前卡號']:
                    df[col] = df[col].str.replace(r'\.0$', '', regex=True)
                    df[col] = df[col].str.replace(' ', '', regex=False)
            return df
        except Exception as e:
            logger.error(f"❌ 預處理卡片對照規則失敗: {e}")
            return pd.DataFrame()

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or const.COL_CARD_NO not in df.columns:
            return df

        # 初始化與標準化欄位
        df[const.COL_CARD_NO] = df[const.COL_CARD_NO].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        
        if const.COL_CARD_TYPE not in df.columns:
            df[const.COL_CARD_TYPE] = ''
        if const.COL_VPC_TYPE not in df.columns:
            df[const.COL_VPC_TYPE] = ''
        if const.COL_PAYMENT_PROCESS not in df.columns:
            df[const.COL_PAYMENT_PROCESS] = ''
        if '_Temp_Prefix' not in df.columns:
            df['_Temp_Prefix'] = ''

        # 暫存 vpc_no 以利比對（若 Parser 有輸出；若無則為空字串）
        if const.COL_VPC_NO in df.columns:
            input_vpc = df[const.COL_VPC_NO].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        else:
            input_vpc = pd.Series('', index=df.index)

        # 識別帳務紀錄 (手續費、繳款、退貨等非消費紀錄，排除行動支付前綴)
        exclude_keywords = ['手續費', '利息', '年費', '回饋', '繳款', '紅利折抵', '小樹點折抵', '退貨', '沖正']
        exclude_pattern = '|'.join(exclude_keywords)
        is_account_record = df[const.COL_MERCHANT].astype(str).str.contains(exclude_pattern, na=False)

        # 逐列比對卡片與 vpc 類型
        for idx, card_val in df[const.COL_CARD_NO].items():
            card_str = str(card_val).replace(' ', '')
            vpc_val = input_vpc.get(idx, '').strip()
            if vpc_val.lower() in ['nan', 'none']:
                vpc_val = ''

            match_rule = None

            if not self.rules.empty:
                # 1. 雙條件比對 (card_no + vpc_no)
                if vpc_val and 'vpc_no' in self.rules.columns:
                    cond_vpc = (self.rules['card_no'] == card_str) & (self.rules['vpc_no'] == vpc_val)
                    matches = self.rules[cond_vpc]
                    if not matches.empty:
                        match_rule = matches.iloc[0]

                # 2. 實體卡 fallback 比對
                if match_rule is None and 'card_no' in self.rules.columns:
                    cond_card = (self.rules['card_no'] == card_str) & (
                        self.rules['vpc_no'].fillna('').isin(['CARD', '', 'nan', 'None']) if 'vpc_no' in self.rules.columns else True
                    )
                    matches = self.rules[cond_card]
                    if not matches.empty:
                        match_rule = matches.iloc[0]

                # 3. 代換前卡號舊相容比對
                if match_rule is None and '代換前卡號' in self.rules.columns:
                    cond_legacy = self.rules['代換前卡號'] == card_str
                    matches = self.rules[cond_legacy]
                    if not matches.empty:
                        match_rule = matches.iloc[0]

            if match_rule is not None:
                # 填入卡別
                val_type = match_rule.get('card_type')
                if pd.notna(val_type) and str(val_type).lower() != 'nan':
                    df.at[idx, const.COL_CARD_TYPE] = str(val_type).strip()

                # 填入 vpc_type
                val_vpc_type = match_rule.get('vpc_type')
                if pd.notna(val_vpc_type) and str(val_vpc_type).lower() != 'nan':
                    df.at[idx, const.COL_VPC_TYPE] = str(val_vpc_type).strip()

        # 第三方支付交叉清洗：若 vpc_type 屬於 dim_payment_process 類別，移至 payment_process 並帶入前綴
        if not self.gateways.empty and 'payment_process_pattern' in self.gateways.columns:
            for idx in df.index:
                v_type = str(df.at[idx, const.COL_VPC_TYPE]).strip()
                if v_type and v_type not in ['', 'CARD', 'nan', 'None']:
                    for _, g_row in self.gateways.iterrows():
                        pat = str(g_row.get('payment_process_pattern', '')).strip()
                        if pat:
                            if pd.Series([v_type]).str.contains(pat, regex=True, na=False).iloc[0]:
                                p_proc = str(g_row.get('payment_process', '')).strip()
                                p_pref = str(g_row.get('process_prefix', '')).strip()
                                if not df.at[idx, const.COL_PAYMENT_PROCESS]:
                                    df.at[idx, const.COL_PAYMENT_PROCESS] = p_proc
                                if not is_account_record[idx] and p_pref and p_pref.lower() != 'nan':
                                    df.at[idx, '_Temp_Prefix'] = p_pref
                                df.at[idx, const.COL_VPC_TYPE] = ''
                                break

        # 移除 vpc_no 欄位 (確保下游不用關心 vpc_no)
        #if const.COL_VPC_NO in df.columns:
        #    df = df.drop(columns=[const.COL_VPC_NO], errors='ignore')

        return df

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
