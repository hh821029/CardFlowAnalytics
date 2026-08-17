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

        # 1. 卡片歸戶與支付分類 (Card & VPC Classifier)
        #    標記卡別、vpc_type 並完成第三方支付交叉流轉
        df = self.card_classifier.process(df)

        # 2. 支付管道識別 (Payment Gateway - 最外層)
        #    標記 payment_process, process_prefix (以及 OEM vpc_type)
        df = self.payment_tagger.process(df)

        # 3. 電商平台識別 (EC Platform - 中層)
        #    標記 ec_platform, ec_platform_type, ec_category, ec_sub_category
        df = self.ec_tagger.process(df)

        # 4. 商家正規化 (Merchant Normalization - 最內層)
        #    依據 dim_merchants.csv 替換商家名稱，結果存入 normalized_merchant, category, sub_category
        res = self.merchant_normalizer.process(df, return_mask=True)
        if isinstance(res, tuple):
            df, processed_mask = res
        else:
            df = res
            processed_mask = pd.Series(False, index=df.index)

        # 5 階層式補位 (Stack Fallback & Cascade)
        # 5.1 特店名稱補位：未被 dim_merchants 匹配時，若有電商平台則以電商平台名稱為準
        if const.COL_NORMALIZED_MERCHANT in df.columns:
            has_ec = (df[const.COL_EC_PLATFORM].fillna('') != '')
            ec_fallback_mask = (~processed_mask) & has_ec
            if ec_fallback_mask.any():
                df.loc[ec_fallback_mask, const.COL_NORMALIZED_MERCHANT] = df.loc[ec_fallback_mask, const.COL_EC_PLATFORM]
                logger.info(f"💡 已為 {ec_fallback_mask.sum()} 筆未匹配商家套用電商平台 Fallback 清洗")

            # 5.2 若既無商家正規化也無電商平台，補為原始 merchant (銀行原始名稱)
            raw_fallback_mask = df[const.COL_NORMALIZED_MERCHANT].isna() | (df[const.COL_NORMALIZED_MERCHANT].astype(str).str.strip() == '')
            if raw_fallback_mask.any():
                df.loc[raw_fallback_mask, const.COL_NORMALIZED_MERCHANT] = df.loc[raw_fallback_mask, const.COL_MERCHANT]

        # 5.3 分類階層補位：若 category 為空且有 ec_category，則以 ec_category 補位
        if const.COL_EC_CATEGORY in df.columns and const.COL_CATEGORY in df.columns:
            cat_empty = df[const.COL_CATEGORY].isna() | (df[const.COL_CATEGORY].astype(str).str.strip() == '')
            cat_ec_has = df[const.COL_EC_CATEGORY].fillna('').astype(str).str.strip() != ''
            cat_fallback = cat_empty & cat_ec_has
            if cat_fallback.any():
                df.loc[cat_fallback, const.COL_CATEGORY] = df.loc[cat_fallback, const.COL_EC_CATEGORY]

        if const.COL_EC_SUB_CATEGORY in df.columns and const.COL_SUB_CATEGORY in df.columns:
            subcat_empty = df[const.COL_SUB_CATEGORY].isna() | (df[const.COL_SUB_CATEGORY].astype(str).str.strip() == '')
            subcat_ec_has = df[const.COL_EC_SUB_CATEGORY].fillna('').astype(str).str.strip() != ''
            subcat_fallback = subcat_empty & subcat_ec_has
            if subcat_fallback.any():
                df.loc[subcat_fallback, const.COL_SUB_CATEGORY] = df.loc[subcat_fallback, const.COL_EC_SUB_CATEGORY]

        # 6. 堆疊拼裝最終顯示名稱 (Compose Merchant Display)
        #    公式：[支付前綴]－[電商平台]－[正規化商家名稱]
        df = self._apply_final_prefixes(df)

        # 7. 交易分類 (Transaction Classification)
        #    根據 merchant_display / category 標記 transaction_type
        df = self.classifier.process(df)

        return df

    def _apply_final_prefixes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [標準化版本] 依照規範合併商家名稱
        公式：[支付前綴]－[電商平台]－[正規化商家名稱]
        """
        def compose_display(row):
            parts = []

            # 1. 支付前綴 (來自 process_prefix)
            prefix = str(row.get(const.COL_PROCESS_PREFIX, '')).strip()
            if prefix and prefix.lower() != 'nan':
                prefix = prefix.rstrip('－- ')
                parts.append(prefix)

            # 2. 電商平台 (來自 ec_platform)
            ec = str(row.get(const.COL_EC_PLATFORM, '')).strip()
            if ec and ec.lower() != 'nan':
                parts.append(ec)

            # 3. 正規化商家名稱 (來自 normalized_merchant)
            merchant = str(row.get(const.COL_NORMALIZED_MERCHANT, '')).strip()
            if merchant and merchant.lower() != 'nan':
                # [關鍵去重]：如果商家名稱跟電商平台完全一樣，就不重複添加
                # 例如：MOMO網購 (電商) + MOMO網購 (商家) -> 只顯示一次
                if merchant != ec:
                    parts.append(merchant)

            return "－".join(parts) if parts else merchant

        df[const.COL_MERCHANT_DISPLAY] = df.apply(compose_display, axis=1)
        logger.info("✅ 已依照規範 [支付前綴]－[電商平台]－[正規化商家] 完成 Merchant_Display 合併")

        return df
