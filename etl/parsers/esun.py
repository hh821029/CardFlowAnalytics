# etl/parsers/esun.py
from typing import Optional
import pandas as pd
import const
from .base import BaseCsvParser

class EsunParser(BaseCsvParser):
    def __init__(self, bank_id_or_keyword: Optional[str] = None, **kwargs):
        super().__init__(bank_id_or_keyword=bank_id_or_keyword, **kwargs)
        self.encoding = 'utf-8-sig'
        self.header_keyword = "消費日"
        self.stop_at_keyword = None  # 玉山通常不需要，或是你可以設 "本期消費明細"
        
        # 欄位映射
        self.mapping = {
            "消費日": const.COL_TXN_DATE,
            "入帳日": const.COL_POST_DATE,
            "消費明細   消費地  外幣折算日": const.COL_MERCHANT,
            "交易類別": const.COL_TXN_TYPE,
            "幣別": const.COL_CURRENCY,
            "金額": const.COL_CURR_AMOUNT,
            "繳款幣別": const.COL_PAY_CURR,
            "金額.1": const.COL_PAY_AMOUNT,
            "行動支付": const.COL_VPC_TYPE,
            "卡號末四碼": const.COL_CARD_NO
        }
        
        # 卡號提取設定
        self.card_extraction_config = {
            'trigger': '卡號：',
            'card_no': r'(\d{4})（',
            'card_type': r'（(.*?)－?(?:正卡|附卡)）'
        }

    def parse(self, filepath: str) -> pd.DataFrame:
        # 1. 讀取
        df = self.read_csv_smart(filepath, self.encoding, self.header_keyword)
        if df.empty: return df

        # 2. 映射
        # 先做一次簡單的 strip 避免欄位名對不上
        df.columns = df.columns.astype(str).str.strip()
        available = [c for c in self.mapping.keys() if c in df.columns]
        df_sliced = df[available]
        if isinstance(df_sliced, pd.DataFrame):
            df = df_sliced.rename(columns=self.mapping)
        else:
            df = pd.DataFrame(df_sliced).rename(columns=self.mapping)
        df[const.COL_BANK_NAME] = self.bank_name

        # 3. [新增] 全域空白清洗 (White Space Cleanup)
        # 在處理邏輯之前，先把所有欄位內容的前後空白修掉，並將空字串轉為 None
        df = self._cleanup_whitespace(df)

        # 4. [新增] 玉山行動支付特例處理 (玉山Wallet(掃碼) 轉為 payment_process)
        df = self._process_mobile_payment(df)

        # 5. 玉山專屬拆解 (消費地/日期)
        df = self._parse_details(df)

        # 6. e.Point 折抵處理 (需在卡號提取前，且金額欄位已清洗過)
        df = self._process_epoint(df)
        
        # 7. 卡號歸戶提取
        df = self.extract_card_info_generic(df, self.card_extraction_config)

        # 7. 日期標準化 + 雜訊過濾 (BaseParser 功能)
        df = self.transform_common_dates(df, filepath)
        
        # 8. 最終正規化 (補齊 TWD 等)
        df = self._finalize_normalization(df)

        return df

    def _cleanup_whitespace(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗 DataFrame 內所有字串欄位的空白
        並將純空白字串 '' 或 ' ' 轉為 None (NaN)
        """
        # 針對 object (字串) 類型的欄位做 strip
        str_cols = df.select_dtypes(include=['object']).columns
        df[str_cols] = df[str_cols].apply(lambda x: x.str.strip())
        
        # 將空字串取代為 NaN，方便後續處理
        df.replace('', pd.NA, inplace=True)
        return df

    def _process_mobile_payment(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        處理玉山帳單特有的『行動支付』欄位：
        若包含『玉山Wallet』或『掃碼』，本質為支付管道 (Payment Process)，應轉入 payment_process 欄位並清空 vpc_type。
        """
        if const.COL_VPC_TYPE not in df.columns:
            return df
        
        if const.COL_PAYMENT_PROCESS not in df.columns:
            df[const.COL_PAYMENT_PROCESS] = None

        vpc_series = df[const.COL_VPC_TYPE].fillna('').astype(str).str.strip()
        
        # 匹配玉山 Wallet (包含全半形、掃碼等)
        mask_wallet = vpc_series.str.contains(r'(?i)(?:玉山.*(?:wallet|電子支付|掃碼)|wallet.*掃碼)', regex=True)
        if mask_wallet.any():
            df.loc[mask_wallet, const.COL_PAYMENT_PROCESS] = '玉山Wallet'
            df.loc[mask_wallet, const.COL_VPC_TYPE] = None

        return df

    def _parse_details(self, df: pd.DataFrame) -> pd.DataFrame:
        """解析玉山特有的複合欄位"""
        if const.COL_MERCHANT not in df.columns: return df
        
        # 確保是字串 (因為前面可能轉成 NaN 了，這裡要防呆)
        merchant_series = df[const.COL_MERCHANT].fillna('').astype(str)
        
        # Regex: (商家名) (分隔) (消費地) (分隔) (日期)?
        pat = r'^(.*?)(?:\s{2,}|\t)(.*?)(?:\s+(\d{2}/\d{2}))?$'
        ext = merchant_series.str.extract(pat)
        
        # 回填
        has_match = ext[0].notna()
        
        # 更新商家名
        df.loc[has_match, const.COL_MERCHANT] = ext[0].str.strip()
        
        # 填入消費地
        df[const.COL_CONSUMPTION_PLACE] = None
        df.loc[has_match, const.COL_CONSUMPTION_PLACE] = ext[1].str.strip()
        df.loc[has_match, const.COL_LOCATION] = ext[1].str.strip()
        
        # 填入折算日
        df.loc[has_match, const.COL_CONV_DATE] = ext[2]
        
        return df

    def _process_epoint(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        處理玉山 e.Point 折抵
        問題點修正：COL_PAY_AMOUNT 可能是空值/空白字串，導致無法寫入。
        解決方案：先強制轉型為 numeric。
        """
        if const.COL_MERCHANT not in df.columns: return df
        if const.COL_PAY_AMOUNT not in df.columns: return df

        # 1. 預處理金額欄位：強制轉為數值 (非數字變 NaN)
        # 這樣才能寫入 float (例如 -100.0)
        df[const.COL_PAY_AMOUNT] = pd.to_numeric(
            df[const.COL_PAY_AMOUNT].astype(str).str.replace(',', ''), 
            errors='coerce'
        )

        # 2. 篩選出含有 "e point" (不分大小寫) 的交易
        mask = df[const.COL_MERCHANT].fillna('').astype(str).str.contains(r'e\s*point', case=False, regex=True)

        if mask.any():
            # 3. 定義 Regex (更寬鬆的匹配)
            # 匹配： "折" + (任意字元) + "現金" + (空白) + (數字/逗號) + (空白) + "元"
            pattern = r'折.*?現金\s*([0-9,]+)\s*元'

            
            # 4. 提取金額
            extracted = df.loc[mask, const.COL_MERCHANT].astype(str).str.extract(pattern)[0]
            
            # 5. 轉數值
            amounts = pd.to_numeric(extracted.str.replace(',', ''), errors='coerce')
            
            # 6. 回填
            # 找出有成功抓到金額的索引
            if isinstance(amounts, pd.Series):
                valid_idx = amounts.notna()
                target_index = df.loc[mask].loc[valid_idx].index
                
                # 填入負數
                df.loc[target_index, const.COL_PAY_AMOUNT] = -amounts.loc[valid_idx]
                
                # 標記交易類別 (選用)
                if const.COL_TXN_TYPE in df.columns:
                    df.loc[target_index, const.COL_TXN_TYPE] = '紅利折抵'

        return df
