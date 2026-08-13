# etl/processors/refiner.py
import pandas as pd
import logging
import const
from typing import Optional
from .merchant import MerchantNormalizer, PaymentProcessTagger, ECPlatformTagger
from .classifier import CardClassifier, TransactionClassifier

logger = logging.getLogger(__name__)

class DataRefiner:
    def __init__(self, config_dir: str, configs: Optional[dict] = None):
        configs = configs or {}
        self.card_classifier = CardClassifier(config_dir, rules=configs.get('cards'), gateways=configs.get('gateways'))
        self.ec_tagger = ECPlatformTagger(config_dir, rules=configs.get('ec_platforms'))
        self.merchant_normalizer = MerchantNormalizer(config_dir, rules=configs.get('merchants'))
        self.payment_tagger = PaymentProcessTagger(config_dir, rules=configs.get('gateways'))
        self.classifier = TransactionClassifier(config_dir, config=configs.get('txn_types'))

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df

        if const.COL_LOCATION not in df.columns:
            df[const.COL_LOCATION] = 'TW'

        if const.COL_MERCHANT_DISPLAY not in df.columns:
            df[const.COL_MERCHANT_DISPLAY] = df[const.COL_MERCHANT]

        # 1. 卡片歸戶與支付分類 (Card & VPC Classifier)
        #    標記卡別、vpc_type 並完成第三方支付交叉流轉
        df = self.card_classifier.process(df)

        # 2. [新增] 電商平台識別 (EC Platform)
        #    在商家正規化之前，先標記電商平台
        df = self.ec_tagger.process(df)

        # 3. 支付管道識別 (Payment Gateway)
        #    注意：這裡只會填入 _Temp_Prefix 和 Mobile_Payment
        #    不會修改 Merchant，所以不會影響 Step 5 的 Regex 匹配
        df = self.payment_tagger.process(df)

        # 4. 商家正規化 (Merchant Normalization)
        #    依據 merchants.csv 替換商家名稱，結果存入 Merchant_Display
        res = self.merchant_normalizer.process(df, return_mask=True)
        if isinstance(res, tuple):
            df, processed_mask = res
        else:
            df = res
            processed_mask = pd.Series(False, index=df.index)

        # 4.5 [新增] Fallback 洗滌 (階層式補位)
        #     若沒被 dim_merchants 正規化處理，且有電商平台標籤，則將商家顯示名稱簡化為電商平台
        if const.COL_EC_PLATFORM in df.columns:
            fallback_mask = (~processed_mask) & (df[const.COL_EC_PLATFORM].fillna('') != '')
            if fallback_mask.any():
                df.loc[fallback_mask, const.COL_MERCHANT_DISPLAY] = df.loc[fallback_mask, const.COL_EC_PLATFORM]
                logger.info(f"💡 已為 {fallback_mask.sum()} 筆未匹配商家套用電商平台 Fallback 清洗")

        # 4.6 保存純正規化商家名稱 (無支付前綴與電商前綴)
        df[const.COL_NORMALIZED_MERCHANT] = df[const.COL_MERCHANT_DISPLAY]

        # 5. [新增] 最終前綴合併
        #    順序：ec_platform -> _Temp_Prefix -> Merchant_Display
        df = self._apply_final_prefixes(df)

        # 6. 交易分類 (Transaction Classification)
        #    根據 Merchant_Display (SSOT) 進行分類
        df = self.classifier.process(df)

        return df

    def _apply_final_prefixes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [標準化版本] 依照規範合併商家名稱
        公式：[支付前綴]－[電商平台]－[商家名稱]
        """
        def compose_display(row):
            parts = []

            # 1. 支付前綴 (來自 PaymentProcessTagger)
            prefix = str(row.get('_Temp_Prefix', '')).strip()
            if prefix and prefix.lower() != 'nan':
                # 移除可能已經存在的連字號，由程式統一添加
                prefix = prefix.rstrip('－- ')
                parts.append(prefix)

            # 2. 電商平台 (來自 ECPlatformTagger)
            ec = str(row.get(const.COL_EC_PLATFORM, '')).strip()
            if ec and ec.lower() != 'nan':
                parts.append(ec)

            # 3. 商家名稱 (已由 MerchantNormalizer 正規化 或 Fallback 為 EC 平台)
            merchant = str(row.get(const.COL_MERCHANT_DISPLAY, '')).strip()
            if merchant and merchant.lower() != 'nan':
                # [關鍵去重]：如果商家名稱跟電商平台完全一樣，就不重複添加了
                # 例如：MOMO網購 (電商) + MOMO網購 (商家) -> 只顯示一次
                if merchant != ec:
                    parts.append(merchant)

            # 使用全形連字號合併
            return "－".join(parts) if parts else merchant

        # 執行合併
        df[const.COL_MERCHANT_DISPLAY] = df.apply(compose_display, axis=1)

        # Log 紀錄
        logger.info("✅ 已依照規範 [支付前綴]－[電商平台]－[商家名稱] 完成 Merchant_Display 合併")

        # 移除暫存欄位 (Clean up)
        df = df.drop(columns=['_Temp_Prefix'], errors='ignore')

        return df
