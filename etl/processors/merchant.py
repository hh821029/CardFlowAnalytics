# etl/processors/merchant.py
import pandas as pd
import logging
import re
import const
import warnings
from typing import Optional, Union, Tuple

warnings.filterwarnings("ignore", message=".*has match groups.*", category=UserWarning)
logger = logging.getLogger(__name__)

class MerchantNormalizer:
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None):
        """
        商戶名稱正規化處理器 (Step 4: 最內層特店識別)
        :param rules: 由外部注入的規則 DataFrame (包含 merchant_pattern, normalized_merchant, priority, category, sub_category)
        """
        self.rules = rules if rules is not None else pd.DataFrame()
        if not self.rules.empty and 'priority' in self.rules.columns:
            priority_series = pd.to_numeric(self.rules['priority'], errors='coerce')
            if isinstance(priority_series, pd.Series):
                self.rules['priority'] = priority_series.fillna(999)
            else:
                self.rules['priority'] = 999 if pd.isna(priority_series) else priority_series
            self.rules = self.rules.sort_values('priority', ascending=True)

    def process(self, df: pd.DataFrame, return_mask: bool = False) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.Series]]:
        if self.rules.empty or df.empty: 
            return (df, pd.Series(False, index=df.index)) if return_mask else df

        # 初始化必要欄位
        if const.COL_CATEGORY not in df.columns: 
            df[const.COL_CATEGORY] = None
        if const.COL_SUB_CATEGORY not in df.columns:
            df[const.COL_SUB_CATEGORY] = None
        if const.COL_NORMALIZED_MERCHANT not in df.columns:
            df[const.COL_NORMALIZED_MERCHANT] = None

        processed_mask = pd.Series(False, index=df.index)
        merchants = df[const.COL_MERCHANT].astype(str).str.strip()

        for _, rule in self.rules.iterrows():
            pattern = rule.get(const.COL_MERCHANT_PATTERN) or rule.get('merchant_pattern') or rule.get('merchant_patterns') or rule.get('pattern')
            replacement = rule.get(const.COL_NORMALIZED_MERCHANT) or rule.get('normalized_merchant') or rule.get('merchant')
            category = rule.get(const.COL_CATEGORY) or rule.get('category')
            sub_category = rule.get(const.COL_SUB_CATEGORY) or rule.get('sub_category')

            if not isinstance(pattern, str) or pattern == '': continue

            try:
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
            except re.error:
                logger.warning(f"⚠️ 無法解析商家正規化正則表達式: {pattern}")
                continue

            if mask.any():
                target_mask = mask & (~processed_mask)
                if target_mask.any():
                    if pd.notna(replacement) and str(replacement).strip() != '':
                        df.loc[target_mask, const.COL_NORMALIZED_MERCHANT] = str(replacement).strip()

                    if pd.notna(category) and str(category).strip() != '':
                        df.loc[target_mask, const.COL_CATEGORY] = str(category).strip()

                    if pd.notna(sub_category) and str(sub_category).strip() != '':
                        df.loc[target_mask, const.COL_SUB_CATEGORY] = str(sub_category).strip()

                    processed_mask |= target_mask

        return (df, processed_mask) if return_mask else df


class PaymentProcessTagger:
    """
    負責標記支付管道或處理方式 (Step 1: 最外層支付通路識別)
    如: LinePay, 街口, 悠遊付, 全支付
    """
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None):
        self.rules = rules if rules is not None else pd.DataFrame()
        if not self.rules.empty and 'priority' in self.rules.columns:
            priority_series = pd.to_numeric(self.rules['priority'], errors='coerce')
            if isinstance(priority_series, pd.Series):
                self.rules['priority'] = priority_series.fillna(999)
            else:
                self.rules['priority'] = 999 if pd.isna(priority_series) else priority_series
            self.rules = self.rules.sort_values('priority', ascending=True)

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.rules.empty or df.empty: return df

        if const.COL_PROCESS_PREFIX not in df.columns:
            df[const.COL_PROCESS_PREFIX] = ''
        else:
            df[const.COL_PROCESS_PREFIX] = df[const.COL_PROCESS_PREFIX].fillna('')

        if const.COL_PAYMENT_PROCESS not in df.columns:
            df[const.COL_PAYMENT_PROCESS] = ''
        else:
            df[const.COL_PAYMENT_PROCESS] = df[const.COL_PAYMENT_PROCESS].fillna('')

        merchants = df[const.COL_MERCHANT].astype(str).str.strip()
        oem_pay_keywords = ['Apple Pay', 'Google Pay', 'Samsung Pay', 'Garmin Pay', 'Hami Pay', 'Google Wallet']

        for _, rule in self.rules.iterrows():
            pattern = rule.get(const.COL_PROCESS_PATTERN) or rule.get('payment_process_pattern')
            prefix = rule.get(const.COL_PROCESS_PREFIX) or rule.get('process_prefix')
            process_name = rule.get(const.COL_PAYMENT_PROCESS) or rule.get('payment_process')

            if not isinstance(pattern, str) or pattern == '': continue

            try:
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
                if mask.any():
                    # 1. 填入前綴 (process_prefix)
                    if pd.notna(prefix):
                        prefix_str = str(prefix).strip()
                        empty_prefix = mask & (df[const.COL_PROCESS_PREFIX] == '')
                        if empty_prefix.any():
                            df.loc[empty_prefix, const.COL_PROCESS_PREFIX] = prefix_str

                    # 2. 判斷支付管道名稱 (payment_process) 或 OEM Pay (vpc_type)
                    if pd.notna(process_name):
                        val_process = str(process_name).strip()
                        is_oem = any(oem.lower() in val_process.lower() for oem in oem_pay_keywords)
                        if is_oem:
                            vpc_empty = mask & (df[const.COL_VPC_TYPE].fillna('') == '')
                            if vpc_empty.any():
                                df.loc[vpc_empty, const.COL_VPC_TYPE] = val_process
                        else:
                            empty_pay = mask & (df[const.COL_PAYMENT_PROCESS] == '')
                            if empty_pay.any():
                                df.loc[empty_pay, const.COL_PAYMENT_PROCESS] = val_process

            except re.error:
                continue

        return df


class ECPlatformTagger:
    """
    負責標記電商平台與電商分類 (Step 2: 中層電商平台識別)
    如: MOMO, 蝦皮, STEAM, PChome
    """
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None):
        self.rules = rules if rules is not None else pd.DataFrame()
        if not self.rules.empty and 'priority' in self.rules.columns:
            priority_series = pd.to_numeric(self.rules['priority'], errors='coerce')
            if isinstance(priority_series, pd.Series):
                self.rules['priority'] = priority_series.fillna(999)
            else:
                self.rules['priority'] = 999 if pd.isna(priority_series) else priority_series
            self.rules = self.rules.sort_values('priority', ascending=True)

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.rules.empty or df.empty: return df

        # 初始化電商相關欄位
        for col in [const.COL_EC_PLATFORM, const.COL_EC_PLATFORM_TYPE, const.COL_EC_CATEGORY, const.COL_EC_SUB_CATEGORY]:
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].fillna('')

        merchants = df[const.COL_MERCHANT].astype(str).str.strip()

        for _, rule in self.rules.iterrows():
            pattern = rule.get(const.COL_EC_PLATFORM_PATTERN) or rule.get('ec_platform_pattern')
            platform_name = rule.get(const.COL_EC_PLATFORM) or rule.get('ec_platform')
            platform_type = rule.get(const.COL_EC_PLATFORM_TYPE) or rule.get('ec_platform_type')
            ec_category = rule.get(const.COL_EC_CATEGORY) or rule.get('ec_category')
            ec_sub_category = rule.get(const.COL_EC_SUB_CATEGORY) or rule.get('ec_sub_category')

            if not isinstance(pattern, str) or pattern == '': continue

            try:
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
                if mask.any():
                    empty_mask = mask & (df[const.COL_EC_PLATFORM] == '')
                    if empty_mask.any():
                        if pd.notna(platform_name):
                            df.loc[empty_mask, const.COL_EC_PLATFORM] = str(platform_name).strip()
                        if pd.notna(platform_type):
                            df.loc[empty_mask, const.COL_EC_PLATFORM_TYPE] = str(platform_type).strip()
                        if pd.notna(ec_category):
                            df.loc[empty_mask, const.COL_EC_CATEGORY] = str(ec_category).strip()
                        if pd.notna(ec_sub_category):
                            df.loc[empty_mask, const.COL_EC_SUB_CATEGORY] = str(ec_sub_category).strip()

            except re.error:
                continue

        return df
