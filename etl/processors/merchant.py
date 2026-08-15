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
        商戶名稱正規化處理器
        :param rules: 由外部注入的規則 DataFrame (包含 pattern, merchant/merchant_display, category, priority)
        """
        # 如果沒有傳入規則，則初始化為空
        self.rules = rules if rules is not None else pd.DataFrame()
        # 根據 priority 排序 (1 為最高優先級)
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
        if const.COL_NORMALIZED_MERCHANT not in df.columns:
            df[const.COL_NORMALIZED_MERCHANT] = df[const.COL_MERCHANT]
        if const.COL_MERCHANT_DISPLAY not in df.columns:
            df[const.COL_MERCHANT_DISPLAY] = df[const.COL_MERCHANT]
        
        # 使用暫存欄位追蹤是否已處理過，避免重複匹配
        processed_mask = pd.Series(False, index=df.index)
        
        merchants = df[const.COL_MERCHANT].astype(str).str.strip()
        
        for _, rule in self.rules.iterrows():
            # 支援多種可能的欄位名稱 (相容新舊格式：merchant_pattern, merchant_patterns, pattern)
            pattern = rule.get(const.COL_MERCHANT_PATTERN) or rule.get('merchant_pattern') or rule.get('merchant_patterns') or rule.get('pattern')
            replacement = rule.get(const.COL_NORMALIZED_MERCHANT) or rule.get('normalized_merchant') or rule.get('merchant')
            category = rule.get(const.COL_CATEGORY) or rule.get('category')
            
            if not isinstance(pattern, str) or pattern == '': continue

            try:
                # 執行正則匹配
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
            except re.error:
                logger.warning(f"⚠️ 無法解析商家正規化正則表達式: {pattern}")
                continue

            if mask.any():
                # 僅針對「尚未被更高優先級規則處理」的交易進行更新
                target_mask = mask & (~processed_mask)
                
                if target_mask.any():
                    # 更新商家顯示名稱
                    if pd.notna(replacement) and str(replacement).strip() != '':
                        df.loc[target_mask, const.COL_NORMALIZED_MERCHANT] = replacement
                    
                    # 更新分類 (若規則有提供)
                    if pd.notna(category) and str(category).strip() != '':
                        df.loc[target_mask, const.COL_CATEGORY] = category
                    
                    # 標記為已處理
                    processed_mask |= target_mask
                    
        return (df, processed_mask) if return_mask else df


class PaymentProcessTagger:
    """
    負責標記支付管道或處理方式 (如 LinePay, 街口, 自動扣款)
    """
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None):
        """
        :param rules: 由外部注入的規則 DataFrame (包含 payment_process_pattern, process_prefix, payment_process)
        """
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

        if '_Temp_Prefix' not in df.columns:
            df['_Temp_Prefix'] = ''
        
        if const.COL_PAYMENT_PROCESS not in df.columns:
            df[const.COL_PAYMENT_PROCESS] = ''
        else:
            df[const.COL_PAYMENT_PROCESS] = df[const.COL_PAYMENT_PROCESS].fillna('')

        merchants = df[const.COL_MERCHANT].astype(str).str.strip()
        
        # 定義 OEM Pay 清單 (這些關鍵字會被歸類到 vpc_type 而非 payment_process)
        oem_pay_keywords = ['Apple Pay', 'Google Pay', 'Samsung Pay', 'Garmin Pay', 'Hami Pay', 'Google Wallet']

        for _, rule in self.rules.iterrows():
            # 使用新的統一命名規範
            pattern = rule.get(const.COL_PROCESS_PATTERN) or rule.get('payment_process_pattern')
            prefix = rule.get(const.COL_PROCESS_PREFIX) or rule.get('process_prefix')
            process_name = rule.get(const.COL_PAYMENT_PROCESS) or rule.get('payment_process')
            
            if not isinstance(pattern, str) or pattern == '': continue
            
            try:
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
                
                if mask.any():
                    if pd.notna(process_name):
                        val_process = str(process_name).strip()
                        # 判斷是否屬於 OEM Pay
                        is_oem = any(oem.lower() in val_process.lower() for oem in oem_pay_keywords)
                        
                        if is_oem:
                            # 填入 vpc_type (僅在原本為空時填入)
                            vpc_empty = mask & (df[const.COL_VPC_TYPE].fillna('') == '')
                            if vpc_empty.any():
                                df.loc[vpc_empty, const.COL_VPC_TYPE] = val_process
                    
                    if pd.notna(prefix):
                        # 檢查是否存在 _Temp_Prefix 欄位
                        if '_Temp_Prefix' not in df.columns:
                            df['_Temp_Prefix'] = ''
                        df.loc[mask, '_Temp_Prefix'] = prefix
                        
            except re.error:
                continue
                
        return df


class ECPlatformTagger:
    """
    負責標記電商平台 (如 MOMO, 蝦皮, STEAM)
    """
    def __init__(self, config_dir: str, rules: Optional[pd.DataFrame] = None):
        """
        :param rules: 由外部注入的規則 DataFrame (包含 ec_platform_pattern, ec_platform, priority)
        """
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

        if const.COL_EC_PLATFORM not in df.columns:
            df[const.COL_EC_PLATFORM] = ''
        else:
            df[const.COL_EC_PLATFORM] = df[const.COL_EC_PLATFORM].fillna('')

        merchants = df[const.COL_MERCHANT].astype(str).str.strip()

        for _, rule in self.rules.iterrows():
            pattern = rule.get(const.COL_EC_PLATFORM_PATTERN) or rule.get('ec_platform_pattern')
            platform_name = rule.get(const.COL_EC_PLATFORM) or rule.get('ec_platform')
            
            if not isinstance(pattern, str) or pattern == '': continue
            
            try:
                mask = merchants.str.contains(pattern, case=False, regex=True, na=False)
                
                if mask.any():
                    # 僅在原本為空時填入 (遵循 priority 順序)
                    empty_mask = mask & (df[const.COL_EC_PLATFORM] == '')
                    if empty_mask.any():
                        df.loc[empty_mask, const.COL_EC_PLATFORM] = platform_name
            except re.error:
                continue
                
        return df
