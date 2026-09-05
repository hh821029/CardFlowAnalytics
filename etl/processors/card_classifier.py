# etl/processors/card_classifier.py
import pandas as pd
import logging
from typing import Optional
import const

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
            card_str_zfill = card_str.zfill(4) if card_str.isdigit() and len(card_str) <= 4 else card_str
            valid_card_nos = [card_str, card_str_zfill] if card_str != card_str_zfill else [card_str]

            vpc_val = input_vpc.get(idx, '').strip()
            if vpc_val.lower() in ['nan', 'none']:
                vpc_val = ''
            vpc_val_zfill = vpc_val.zfill(4) if vpc_val.isdigit() and len(vpc_val) <= 4 else vpc_val
            valid_vpc_nos = [vpc_val, vpc_val_zfill] if vpc_val != vpc_val_zfill else [vpc_val]

            match_rule = None

            if not self.rules.empty:
                # 1. 雙條件比對 (card_no + vpc_no)
                if vpc_val and 'vpc_no' in self.rules.columns:
                    cond_vpc = (self.rules['card_no'].isin(valid_card_nos)) & (self.rules['vpc_no'].isin(valid_vpc_nos))
                    matches = self.rules[cond_vpc]
                    if not matches.empty:
                        match_rule = matches.iloc[0]

                # 2. 實體卡 fallback 比對 (支援 vpc_type == CARD, vpc_no 與 card_no 相同, 或 vpc_no 標記為 CARD/空值)
                if match_rule is None and 'card_no' in self.rules.columns:
                    is_card_vpc = (
                        (self.rules['vpc_type'].astype(str).str.upper() == 'CARD') if 'vpc_type' in self.rules.columns else False
                    ) | (
                        (self.rules['vpc_no'].astype(str) == self.rules['card_no'].astype(str)) if 'vpc_no' in self.rules.columns else False
                    ) | (
                        self.rules['vpc_no'].fillna('').isin(['CARD', '', 'nan', 'None']) if 'vpc_no' in self.rules.columns else True
                    )
                    cond_card = (self.rules['card_no'].isin(valid_card_nos)) & is_card_vpc
                    matches = self.rules[cond_card]
                    if not matches.empty:
                        match_rule = matches.iloc[0]

                # 3. 代換前卡號舊相容比對
                if match_rule is None and '代換前卡號' in self.rules.columns:
                    cond_legacy = self.rules['代換前卡號'].isin(valid_card_nos)
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
        if const.COL_VPC_NO in df.columns:
            df = df.drop(columns=[const.COL_VPC_NO], errors='ignore')

        return df
